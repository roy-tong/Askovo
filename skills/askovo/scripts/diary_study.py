"""Local pre-registered longitudinal diary entries with consent and aggregate export."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, time, timezone
from pathlib import Path

SCHEMA = "askovo.diary-study/1"
STATUS_SCHEMA = "askovo.diary-study-status/1"
EXPORT_SCHEMA = "askovo.diary-study-aggregate/1"
SPEC_NAME = "diary-study.json"
DB_NAME = "diary-study.sqlite3"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _instant(value):
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid ISO timestamp: %r" % value) from exc
    if parsed.tzinfo is None:
        raise ValueError("diary timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _day(value):
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("diary schedule dates must be ISO dates") from exc


def _validate(spec):
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError("diary schema must be %s" % SCHEMA)
    for key in ("study_id", "objective", "prompt", "consent_notice",
                    "registered_by", "registered_at"):
        if not str(spec.get(key) or "").strip():
            raise ValueError("diary.%s is required" % key)
    if not isinstance(spec.get("window"), dict):
        raise ValueError("diary.window must be an object")
    if _instant(spec["window"].get("end")) <= _instant(spec["window"].get("start")):
        raise ValueError("diary window must end after it starts")
    schedule = spec.get("schedule")
    if not isinstance(schedule, list) or not schedule:
        raise ValueError("diary.schedule must be a non-empty array")
    days = [_day(value) for value in schedule]
    if len(set(days)) != len(days) or days != sorted(days):
        raise ValueError("diary schedule must contain unique ascending dates")
    if days[0] < _instant(spec["window"]["start"]).date() or days[-1] >= _instant(spec["window"]["end"]).date():
        raise ValueError("diary schedule must be inside the registered window")
    participants = spec.get("participants")
    if not isinstance(participants, list) or not participants:
        raise ValueError("diary.participants must be a non-empty array")
    ids = set()
    for participant in participants:
        if not isinstance(participant, dict):
            raise ValueError("diary participants must be objects")
        for key in ("participant_ref", "screening_ref"):
            if not str(participant.get(key) or "").strip():
                raise ValueError("diary participant.%s is required" % key)
        if participant["participant_ref"] in ids:
            raise ValueError("duplicate diary participant_ref")
        ids.add(participant["participant_ref"])


def _connect(root):
    connection = sqlite3.connect(str(Path(root) / DB_NAME), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def create(spec, out_dir):
    _validate(spec)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError("refusing to overwrite diary study directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    (out / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    with _connect(out) as connection:
        connection.executescript("""
CREATE TABLE registration (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entries (
  entry_id TEXT PRIMARY KEY,
  participant_ref TEXT NOT NULL,
  scheduled_date TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  consent_state TEXT NOT NULL,
  data_json TEXT NOT NULL,
  entry_hash TEXT NOT NULL,
  UNIQUE(participant_ref,scheduled_date)
);
""")
        connection.execute("INSERT INTO registration(key,value) VALUES('spec_sha256',?)",
                           (_hash(spec),))
    return {"status": "created", "schema": SCHEMA, "study_id": spec["study_id"],
            "path": str(out), "network": "local_entry_import_only"}


def load_spec(root):
    spec = json.loads((Path(root) / SPEC_NAME).read_text(encoding="utf-8"))
    _validate(spec)
    with _connect(root) as connection:
        row = connection.execute(
            "SELECT value FROM registration WHERE key='spec_sha256'").fetchone()
    if row is None or row["value"] != _hash(spec):
        raise ValueError("registered design fingerprint mismatch; create a new diary revision")
    return spec


def load_entries(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(document, dict):
        document = [document] if document.get("entry_id") else document.get("entries")
    if not isinstance(document, list):
        raise ValueError("diary input must be an array or JSONL")
    return document


def _validate_entry(row, spec, participants):
    if not isinstance(row, dict):
        raise ValueError("diary entry must be an object")
    for key in ("entry_id", "participant_ref", "source_ref", "consent_ref"):
        if not str(row.get(key) or "").strip():
            raise ValueError("diary entry.%s is required" % key)
    if row["participant_ref"] not in participants:
        raise ValueError("diary participant is not registered")
    scheduled = _day(row.get("scheduled_date"))
    if str(scheduled) not in spec["schedule"]:
        raise ValueError("diary scheduled_date is not registered")
    if row.get("consent_state") not in ("accepted", "withdrawn"):
        raise ValueError("diary consent_state must be accepted or withdrawn")
    if row["consent_state"] == "accepted" and not str(row.get("response") or "").strip():
        raise ValueError("accepted diary entry requires a response")
    if row["consent_state"] == "withdrawn" and str(row.get("response") or ""):
        raise ValueError("withdrawal cannot contain a diary response")
    submitted = _instant(row.get("submitted_at"))
    if submitted < _instant(spec["window"]["start"]) or submitted >= _instant(spec["window"]["end"]):
        raise ValueError("diary entry is outside the registered window")


def import_entries(root, rows, *, imported_by):
    spec = load_spec(root)
    if not str(imported_by or "").strip():
        raise ValueError("imported_by is required")
    participants = {row["participant_ref"] for row in spec["participants"]}
    added = 0
    duplicates = 0
    with _connect(root) as connection:
        for row in rows:
            _validate_entry(row, spec, participants)
            entry_hash = _hash(row)
            existing = connection.execute(
                "SELECT entry_hash FROM entries WHERE entry_id=?", (row["entry_id"],)).fetchone()
            if existing:
                if existing["entry_hash"] != entry_hash:
                    raise ValueError("diary entry_id conflict")
                duplicates += 1
                continue
            withdrawn = connection.execute(
                "SELECT 1 FROM entries WHERE participant_ref=? AND consent_state='withdrawn'",
                (row["participant_ref"],)).fetchone()
            if withdrawn and row["consent_state"] == "accepted":
                raise ValueError("participant has withdrawn from the diary study")
            try:
                connection.execute(
                    "INSERT INTO entries(entry_id,participant_ref,scheduled_date,submitted_at,"
                    "consent_state,data_json,entry_hash) VALUES(?,?,?,?,?,?,?)",
                    (row["entry_id"], row["participant_ref"], str(_day(row["scheduled_date"])),
                     row["submitted_at"], row["consent_state"], _canonical(row), entry_hash))
            except sqlite3.IntegrityError as exc:
                raise ValueError("participant already has an entry for this scheduled_date") from exc
            added += 1
    return {"status": "imported", "added": added, "duplicates": duplicates,
            "imported_by": str(imported_by), "external_actions": False}


def _rows(root):
    with _connect(root) as connection:
        rows = connection.execute(
            "SELECT data_json,entry_hash FROM entries ORDER BY submitted_at,entry_id").fetchall()
    return [(json.loads(row["data_json"]), row["entry_hash"]) for row in rows]


def status(root, *, now=""):
    spec = load_spec(root)
    rows = _rows(root)
    accepted = [(row, digest) for row, digest in rows if row["consent_state"] == "accepted"]
    withdrawn = [(row, digest) for row, digest in rows if row["consent_state"] == "withdrawn"]
    per_date = []
    for scheduled in spec["schedule"]:
        own = [(row, digest) for row, digest in accepted if row["scheduled_date"] == scheduled]
        per_date.append({
            "scheduled_date": scheduled, "accepted_entries": len(own),
            "participants": len({row["participant_ref"] for row, _ in own}),
            "late_entries": sum(_instant(row["submitted_at"]).date() > _day(scheduled)
                                for row, _ in own),
        })
    current = _instant(now) if now else datetime.now(timezone.utc)
    accepted_cells = {(row["participant_ref"], row["scheduled_date"]) for row, _ in accepted}
    due_cells = []
    for participant in spec["participants"]:
        participant_ref = participant["participant_ref"]
        for scheduled in spec["schedule"]:
            if _day(scheduled) > current.date() or (participant_ref, scheduled) in accepted_cells:
                continue
            cutoff = datetime.combine(_day(scheduled), time.max, tzinfo=timezone.utc)
            has_withdrawn = any(row["participant_ref"] == participant_ref and
                                _instant(row["submitted_at"]) <= cutoff for row, _ in withdrawn)
            if not has_withdrawn:
                due_cells.append({"participant_ref": participant_ref, "scheduled_date": scheduled})
    return {
        "schema": STATUS_SCHEMA, "study_id": spec["study_id"],
        "schedule": per_date, "due_cells": due_cells,
        "totals": {
            "registered_participants": len(spec["participants"]),
            "registered_cells": len(spec["participants"]) * len(spec["schedule"]),
            "accepted_entries": len(accepted),
            "late_entries": sum(row["late_entries"] for row in per_date),
            "withdrawals": len(withdrawn),
        },
        "network": "local_entry_import_only", "external_reminders_sent": False,
        "causal_status": "descriptive_only",
        "boundary": "Longitudinal diary counts are descriptive. Missing cells are not negative evidence; participation, representativeness, demand and product acceptance remain unproven.",
    }


def export_aggregate(root):
    report = status(root)
    return {
        "schema": EXPORT_SCHEMA, "study_id": report["study_id"],
        "schedule": report["schedule"], "totals": report["totals"],
        "network": report["network"], "external_reminders_sent": False,
        "causal_status": report["causal_status"], "boundary": report["boundary"],
        "privacy": "Aggregate scheduled-date counts only; participant references and response text are excluded.",
    }


def write_aggregate(root, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(export_aggregate(root), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

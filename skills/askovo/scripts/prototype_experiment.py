"""Local, pre-registered prototype task observations and aggregate experiment export."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

SCHEMA = "askovo.prototype-experiment/1"
STATUS_SCHEMA = "askovo.prototype-experiment-status/1"
SPEC_NAME = "prototype-experiment.json"
DB_NAME = "prototype-experiment.sqlite3"


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
        raise ValueError("observation timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate(spec):
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError("prototype experiment schema must be %s" % SCHEMA)
    for key in ("experiment_id", "registered_by", "registered_at", "population",
                    "consent_notice"):
        if not str(spec.get(key) or "").strip():
            raise ValueError("prototype experiment.%s is required" % key)
    hypothesis = spec.get("hypothesis") if isinstance(spec.get("hypothesis"), dict) else {}
    for key in ("statement", "falsification_condition"):
        if not str(hypothesis.get(key) or "").strip():
            raise ValueError("hypothesis.%s is required" % key)
    if not isinstance(spec.get("window"), dict) or not isinstance(spec.get("comparability"), dict):
        raise ValueError("window and comparability must be objects")
    if _instant(spec["window"].get("end")) <= _instant(spec["window"].get("start")):
        raise ValueError("experiment window must end after it starts")
    if int(spec.get("planned_sample_per_arm", 0)) <= 0 or int(spec.get("max_participants", 0)) <= 0:
        raise ValueError("planned_sample_per_arm and max_participants must be positive")
    mode = str(spec.get("validation_mode") or "prototype")
    if mode not in ("prototype", "mvp_behavior"):
        raise ValueError("validation_mode must be prototype or mvp_behavior")
    if mode == "mvp_behavior":
        hours = spec.get("repeat_window_hours")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
            raise ValueError("mvp_behavior requires positive repeat_window_hours")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty array")
    ids = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("tasks must contain objects")
        for key in ("task_id", "instruction", "success_criteria"):
            if not str(task.get(key) or "").strip():
                raise ValueError("task.%s is required" % key)
        if task["task_id"] in ids:
            raise ValueError("duplicate task_id")
        ids.add(task["task_id"])


def _connect(root):
    connection = sqlite3.connect(str(Path(root) / DB_NAME), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db(root, spec):
    with _connect(root) as connection:
        connection.executescript("""
CREATE TABLE registration (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE observations (
  observation_id TEXT PRIMARY KEY,
  participant_ref TEXT NOT NULL,
  task_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  data_json TEXT NOT NULL,
  observation_hash TEXT NOT NULL,
  UNIQUE(participant_ref,task_id,attempt)
);
""")
        connection.execute("INSERT INTO registration(key,value) VALUES('spec_sha256',?)",
                           (_hash(spec),))


def create(spec, out_dir):
    _validate(spec)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError("refusing to overwrite prototype experiment directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    (out / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    _init_db(out, spec)
    return {"status": "created", "schema": SCHEMA,
            "experiment_id": spec["experiment_id"], "path": str(out),
            "network": "local_observation_import_only"}


def load_spec(root):
    spec = json.loads((Path(root) / SPEC_NAME).read_text(encoding="utf-8"))
    _validate(spec)
    with _connect(root) as connection:
        row = connection.execute(
            "SELECT value FROM registration WHERE key='spec_sha256'").fetchone()
    if row is None or row["value"] != _hash(spec):
        raise ValueError("registered design fingerprint mismatch; create a new experiment revision")
    return spec


def load_observations(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(document, dict):
        document = [document] if document.get("observation_id") else document.get("observations")
    if not isinstance(document, list):
        raise ValueError("observations input must be an array or JSONL")
    return document


def _validate_observation(row, spec, task_ids):
    if not isinstance(row, dict):
        raise ValueError("observation must be an object")
    for key in ("observation_id", "participant_ref", "task_id", "source_ref",
                "consent_ref", "observed_by"):
        if not str(row.get(key) or "").strip():
            raise ValueError("observation.%s is required" % key)
    if row["task_id"] not in task_ids:
        raise ValueError("observation task_id is not registered")
    observed = _instant(row.get("observed_at"))
    if observed < _instant(spec["window"]["start"]) or observed >= _instant(spec["window"]["end"]):
        raise ValueError("observation is outside the registered window")
    if not isinstance(row.get("success"), bool) or not isinstance(row.get("assistance_required"), bool):
        raise ValueError("success and assistance_required must be booleans")
    if isinstance(row.get("duration_seconds"), bool) or not isinstance(row.get("duration_seconds"), (int, float)) \
            or row["duration_seconds"] < 0:
        raise ValueError("duration_seconds must be a non-negative number")
    if isinstance(row.get("error_count"), bool) or not isinstance(row.get("error_count"), int) \
            or row["error_count"] < 0:
        raise ValueError("error_count must be a non-negative integer")
    if isinstance(row.get("attempt", 1), bool) or int(row.get("attempt", 1)) <= 0:
        raise ValueError("attempt must be a positive integer")


def import_observations(root, rows, *, imported_by):
    spec = load_spec(root)
    if not str(imported_by or "").strip():
        raise ValueError("imported_by is required")
    task_ids = {row["task_id"] for row in spec["tasks"]}
    added = 0
    duplicates = 0
    with _connect(root) as connection:
        participants = {row["participant_ref"] for row in connection.execute(
            "SELECT DISTINCT participant_ref FROM observations").fetchall()}
        incoming_participants = {str(row.get("participant_ref") or "") for row in rows
                                 if isinstance(row, dict)}
        if len(participants | incoming_participants) > int(spec["max_participants"]):
            raise ValueError("participant limit reached")
        for row in rows:
            _validate_observation(row, spec, task_ids)
            observation_hash = _hash(row)
            existing = connection.execute(
                "SELECT observation_hash FROM observations WHERE observation_id=?",
                (row["observation_id"],)).fetchone()
            if existing:
                if existing["observation_hash"] != observation_hash:
                    raise ValueError("observation_id conflict")
                duplicates += 1
                continue
            connection.execute(
                "INSERT INTO observations(observation_id,participant_ref,task_id,attempt,observed_at,data_json,observation_hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (row["observation_id"], row["participant_ref"], row["task_id"],
                 int(row.get("attempt", 1)), row["observed_at"], _canonical(row), observation_hash))
            added += 1
    return {"status": "imported", "added": added, "duplicates": duplicates,
            "imported_by": str(imported_by), "external_actions": False}


def _rows(root):
    with _connect(root) as connection:
        rows = connection.execute("SELECT data_json,observation_hash FROM observations "
                                  "ORDER BY observed_at,observation_id").fetchall()
    return [(json.loads(row["data_json"]), row["observation_hash"]) for row in rows]


def _mvp_projection(rows, spec):
    participants = {row["participant_ref"] for row, _ in rows}
    activated = 0
    retained = 0
    repeat_window = float(spec["repeat_window_hours"])
    for participant in participants:
        successes = sorted(_instant(row["observed_at"]) for row, _ in rows
                           if row["participant_ref"] == participant and row["success"])
        if not successes:
            continue
        activated += 1
        first_value = successes[0]
        if any((observed - first_value).total_seconds() >= repeat_window * 3600
               for observed in successes[1:]):
            retained += 1
    return {
        "participants": len(participants),
        "activated_participants": activated,
        "retained_participants": retained,
        "activation_rate": round(activated / len(participants), 6) if participants else None,
        "retention_rate_among_activated": round(retained / activated, 6) if activated else None,
        "repeat_window_hours": spec["repeat_window_hours"],
        "interpretation": "first successful registered task and a later successful task after the registered interval",
    }


def status(root):
    spec = load_spec(root)
    rows = _rows(root)
    tasks = []
    for contract in spec["tasks"]:
        own = [row for row, _ in rows if row["task_id"] == contract["task_id"]]
        successes = sum(row["success"] for row in own)
        tasks.append({
            "task_id": contract["task_id"], "instruction": contract["instruction"],
            "success_criteria": contract["success_criteria"],
            "observations": len(own), "participants": len({row["participant_ref"] for row in own}),
            "successes": successes,
            "success_rate": round(successes / len(own), 6) if own else None,
            "median_duration_seconds": median([row["duration_seconds"] for row in own]) if own else None,
            "assistance_required": sum(row["assistance_required"] for row in own),
            "errors": sum(row["error_count"] for row in own),
        })
    mvp = _mvp_projection(rows, spec) if spec.get("validation_mode") == "mvp_behavior" else None
    return {
        "schema": STATUS_SCHEMA, "experiment_id": spec["experiment_id"],
        "validation_mode": spec.get("validation_mode") or "prototype",
        "mvp": mvp,
        "tasks": tasks,
        "totals": {"observations": len(rows),
                   "participants": len({row["participant_ref"] for row, _ in rows}),
                   "successes": sum(row["success"] for row, _ in rows)},
        "causal_status": "descriptive_only",
        "network": "local_observation_import_only",
        "boundary": "Observed prototype task outcomes are descriptive. They do not prove demand, prevalence, usability for all users, causality or product acceptance.",
    }


def shared_design_hash(document):
    projection = {key: document.get(key) for key in
                  ("hypothesis", "design", "window", "stop_conditions")}
    return _hash(projection)


def export_experiment(root, origin_version):
    spec = load_spec(root)
    report = status(root)
    rows = _rows(root)
    observations = []
    for task in report["tasks"]:
        own = [(row, digest) for row, digest in rows if row["task_id"] == task["task_id"]]
        if not own:
            continue
        aggregate = dict(task)
        aggregate["event_hashes"] = sorted(digest for _, digest in own)
        observations.append({
            "observation_id": "aggregate:%s" % task["task_id"],
            "arm_id": "prototype", "metric_id": "task_success_rate",
            "subject_ref": "aggregate:%s" % task["task_id"],
            "observed_at": max(row["observed_at"] for row, _ in own),
            "value_number": task["success_rate"],
            "source_ref": "askovo-prototype:%s/%s/aggregate" % (
                spec["experiment_id"], task["task_id"]),
            "source_hash": _hash(aggregate), "evidence_grade": "observed",
            "eligible": True, "exclusion_reason": "",
        })
    if report.get("mvp") and rows:
        for metric_id, value in (("activation_rate", report["mvp"]["activation_rate"]),
                                 ("retention_rate", report["mvp"]["retention_rate_among_activated"])):
            if value is None:
                continue
            aggregate = dict(report["mvp"])
            aggregate["metric_id"] = metric_id
            aggregate["event_hashes"] = sorted(digest for _, digest in rows)
            observations.append({
                "observation_id": "aggregate:%s" % metric_id, "arm_id": "prototype",
                "metric_id": metric_id, "subject_ref": "aggregate:%s" % metric_id,
                "observed_at": max(row["observed_at"] for row, _ in rows),
                "value_number": value,
                "source_ref": "askovo-prototype:%s/%s/aggregate" % (spec["experiment_id"], metric_id),
                "source_hash": _hash(aggregate), "evidence_grade": "observed",
                "eligible": True, "exclusion_reason": "",
            })
    document = {
        "schema": "ovo.experiment-contract/1", "experiment_id": spec["experiment_id"],
        "origin_product": "askovo", "origin_version": str(origin_version),
        "task_id": spec["experiment_id"], "title": "Prototype experiment %s" % spec["experiment_id"],
        "state": "completed" if rows else "registered",
        "hypothesis": spec["hypothesis"],
        "design": {
            "experiment_type": "single_arm", "unit_of_analysis": "task_attempt",
            "population": spec["population"], "assignment": "none",
            "arms": [{"arm_id": "prototype", "role": "treatment",
                      "description": "Registered prototype tasks",
                      "planned_sample_size": spec["planned_sample_per_arm"]}],
            "primary_metrics": [{"metric_id": "task_success_rate",
                                 "definition": "Observed successful task attempts divided by observed attempts.",
                                 "unit": "ratio", "direction": "increase"}],
            "comparability": spec["comparability"],
        },
        "window": spec["window"],
        "stop_conditions": ["Stop at %d observed participants." % spec["max_participants"]],
        "external_actions": False, "authorization_refs": [],
        "registered_by": spec["registered_by"], "registered_at": spec["registered_at"],
        "observations": observations,
        "outcome": {
            "status": "inconclusive" if observations else "not_evaluated",
            "causality": "descriptive_association" if observations else "not_claimed",
            "evidence_refs": [row["observation_id"] for row in observations],
            "evaluated_by": "", "evaluated_at": "",
            "notes": "Aggregate task observations only; no demand, product acceptance or causal verdict is inferred.",
        },
    }
    if report.get("mvp"):
        document["design"]["primary_metrics"].extend([
            {"metric_id": "activation_rate", "definition": "Participants with a first successful registered task divided by observed participants.",
             "unit": "ratio", "direction": "increase"},
            {"metric_id": "retention_rate", "definition": "Activated participants with another success after the registered repeat window divided by activated participants.",
             "unit": "ratio", "direction": "increase"},
        ])
    document["design_sha256"] = shared_design_hash(document)
    return document


def write_shared_export(document, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

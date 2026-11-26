"""Loopback-only landing-page experiment execution with durable anonymous assignments."""
from __future__ import annotations

import copy
import hashlib
import html
import ipaddress
import json
import math
import random
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlsplit

SCHEMA = "askovo.landing-experiment/1"
STATUS_SCHEMA = "askovo.landing-experiment-status/1"
SPEC_NAME = "landing-experiment.json"
DB_NAME = "landing-experiment.sqlite3"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _instant(value, label):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("%s must be an ISO 8601 timestamp" % label) from exc
    if parsed.tzinfo is None:
        raise ValueError("%s must include a timezone" % label)
    return parsed


def _window_bounds(window, label="window"):
    if not isinstance(window, dict):
        raise ValueError("%s must be an object" % label)
    start = _instant(window.get("start"), label + ".start")
    end = _instant(window.get("end"), label + ".end")
    if end <= start:
        raise ValueError("%s must end after it starts" % label)
    return start, end


def _window_state(spec, kind, at=None):
    window = spec["window"] if kind == "enrollment" else spec.get("outcome_window") or spec["window"]
    start, end = _window_bounds(window, kind + "_window")
    current = _instant(at or _now(), "current time")
    if current < start:
        return kind + "_not_started"
    if current >= end:
        return kind + "_closed"
    return "active"


def _validate(spec):
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError("landing experiment schema must be %s" % SCHEMA)
    for key in ("experiment_id", "registered_by", "registered_at", "conversion_definition",
                "consent_notice", "population", "window", "comparability"):
        if not str(spec.get(key) or "").strip():
            raise ValueError("landing experiment.%s is required" % key)
    hypothesis = spec.get("hypothesis") if isinstance(spec.get("hypothesis"), dict) else {}
    for key in ("statement", "falsification_condition"):
        if not str(hypothesis.get(key) or "").strip():
            raise ValueError("hypothesis.%s is required" % key)
    try:
        maximum = int(spec.get("max_exposures"))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_exposures must be a positive integer") from exc
    if maximum <= 0:
        raise ValueError("max_exposures must be a positive integer")
    try:
        minimum = int(spec.get("min_exposures_per_arm", 30))
    except (TypeError, ValueError) as exc:
        raise ValueError("min_exposures_per_arm must be a positive integer") from exc
    if minimum <= 0:
        raise ValueError("min_exposures_per_arm must be a positive integer")
    try:
        planned = int(spec.get("planned_sample_per_arm"))
    except (TypeError, ValueError) as exc:
        raise ValueError("planned_sample_per_arm must be a positive integer") from exc
    if planned <= 0:
        raise ValueError("planned_sample_per_arm must be a positive integer")
    if not isinstance(spec.get("comparability"), dict):
        raise ValueError("comparability must be an object")
    _window_bounds(spec.get("window"))
    if spec.get("outcome_window") is not None:
        _window_bounds(spec["outcome_window"], "outcome_window")
    eligibility = spec.get("eligibility")
    if eligibility is not None:
        if not isinstance(eligibility, dict) \
                or not str(eligibility.get("screening_sha256") or "").startswith("sha256:"):
            raise ValueError("eligibility needs a screening_sha256")
        registry = eligibility.get("registry")
        if not isinstance(registry, list) or not registry:
            raise ValueError("eligibility.registry must be a non-empty array")
        tokens = set()
        participants = set()
        for row in registry:
            if not isinstance(row, dict) \
                    or not str(row.get("token_sha256") or "").startswith("sha256:") \
                    or not str(row.get("participant_ref_hash") or "").startswith("sha256:"):
                raise ValueError("eligibility registry entries need token and participant hashes")
            if row["token_sha256"] in tokens or row["participant_ref_hash"] in participants:
                raise ValueError("eligibility registry hashes must be unique")
            tokens.add(row["token_sha256"])
            participants.add(row["participant_ref_hash"])
    revision_keys = ("revision_of", "previous_design_sha256", "revision_reason")
    if any(spec.get(key) for key in revision_keys):
        if not all(str(spec.get(key) or "").strip() for key in revision_keys):
            raise ValueError("design revision needs revision_of, previous_design_sha256 and revision_reason")
        if not str(spec["previous_design_sha256"]).startswith("sha256:"):
            raise ValueError("previous_design_sha256 must be a SHA-256 reference")
    variants = spec.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        raise ValueError("at least two variants are required")
    ids = set()
    roles = set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError("variants must contain objects")
        for key in ("arm_id", "role", "title", "body", "cta_label"):
            if not str(variant.get(key) or "").strip():
                raise ValueError("variant.%s is required" % key)
        if variant["role"] not in ("control", "treatment"):
            raise ValueError("variant role must be control or treatment")
        if variant["arm_id"] in ids:
            raise ValueError("duplicate arm_id")
        ids.add(variant["arm_id"])
        roles.add(variant["role"])
    if roles != {"control", "treatment"}:
        raise ValueError("landing experiment needs control and treatment variants")
    _pricing(spec)


def _pricing(spec):
    mode = str(spec.get("validation_mode") or "concept")
    if mode not in ("concept", "price_sensitivity"):
        raise ValueError("validation_mode must be concept or price_sensitivity")
    if mode != "price_sensitivity":
        return None
    currency = str(spec.get("currency") or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha() or not str(spec.get("price_definition") or "").strip():
        raise ValueError("price_sensitivity requires a three-letter currency and price_definition")
    arms = []
    prices = set()
    for variant in spec["variants"]:
        value = variant.get("price_amount")
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value < 0:
            raise ValueError("variant.price_amount must be a finite non-negative number")
        if value in prices:
            raise ValueError("price_sensitivity variants need distinct price points")
        prices.add(value)
        arms.append({"arm_id": variant["arm_id"], "price_amount": value})
    return {"validation_mode": mode, "currency": currency,
            "price_definition": spec["price_definition"], "arms": arms,
            "evidence_boundary": "Observed registration intent is not payment or willingness-to-pay proof."}


def _connect(root):
    connection = sqlite3.connect(str(Path(root) / DB_NAME), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _spec_hash(spec):
    return "sha256:" + hashlib.sha256(_canonical(spec).encode("utf-8")).hexdigest()


def _init_db(root, spec=None):
    with _connect(root) as connection:
        connection.executescript("""
CREATE TABLE IF NOT EXISTS assignments (
  participant_id TEXT PRIMARY KEY,
  arm_id TEXT NOT NULL,
  assigned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  arm_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registration (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
""")
        if spec is not None:
            connection.execute(
                "INSERT INTO registration(key,value) VALUES('spec_sha256',?)",
                (_spec_hash(spec),))


def create(spec, out_dir):
    spec = copy.deepcopy(spec)
    spec.setdefault("min_exposures_per_arm", 30)
    _validate(spec)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError("refusing to overwrite experiment directory: %s" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    (out / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    _init_db(out, spec)
    return {"status": "created", "schema": SCHEMA,
            "experiment_id": spec["experiment_id"], "path": str(out),
            "network": "loopback_only"}


def load_spec(root):
    path = Path(root) / SPEC_NAME
    spec = json.loads(path.read_text(encoding="utf-8"))
    _validate(spec)
    with _connect(root) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS registration (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = connection.execute(
            "SELECT value FROM registration WHERE key='spec_sha256'").fetchone()
    if row is None or row["value"] != _spec_hash(spec):
        raise ValueError("registered design fingerprint mismatch; create a new revision instead")
    return spec


def _record_event(root, experiment_id, participant_id, arm_id, event_type, at=None):
    event_id = "%s:%s" % (event_type, participant_id)
    stamp = str(at or _now())
    event = {
        "event_id": event_id,
        "participant_id": participant_id,
        "arm_id": arm_id,
        "event_type": event_type,
        "occurred_at": stamp,
        "source_ref": "askovo-landing:%s/%s" % (experiment_id, event_id),
    }
    event["source_hash"] = "sha256:" + hashlib.sha256(_canonical(event).encode("utf-8")).hexdigest()
    with _connect(root) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO events(event_id,participant_id,arm_id,event_type,occurred_at,source_ref,source_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (event_id, participant_id, arm_id, event_type, stamp,
             event["source_ref"], event["source_hash"]))
    return event


def _variant(spec, arm_id):
    return next(row for row in spec["variants"] if row["arm_id"] == arm_id)


def _page(spec, variant, participant_id):
    consent = html.escape(spec["consent_notice"])
    title = html.escape(variant["title"])
    body = html.escape(variant["body"])
    cta = html.escape(variant["cta_label"])
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>%s</title><style>body{font:16px/1.6 system-ui;max-width:680px;margin:60px auto;padding:0 20px}button{padding:12px 18px}</style></head>
<body><main><h1>%s</h1><p>%s</p><form method='post' action='/convert'><button type='submit'>%s</button></form>
<p><small>%s</small></p></main></body></html>""" % (title, title, body, cta, consent)


class LandingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root):
        self.root = Path(root)
        self.spec = load_spec(self.root)
        seed = self.spec.get("assignment_seed")
        self.random = random.Random(seed) if seed is not None else secrets.SystemRandom()
        self.assignment_lock = threading.Lock()
        super().__init__(address, LandingHandler)


class LandingHandler(BaseHTTPRequestHandler):
    def _headers(self, status=200, content_type="text/html; charset=utf-8", cookie=""):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _cookie(self):
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ovo_landing_pid":
                return value
        return ""

    def _assign(self, participant_id, token=""):
        spec = self.server.spec
        with self.server.assignment_lock:
            with _connect(self.server.root) as connection:
                if participant_id:
                    row = connection.execute(
                        "SELECT arm_id FROM assignments WHERE participant_id=?", (participant_id,)).fetchone()
                    if row:
                        return participant_id, str(row["arm_id"]), ""
                eligibility = spec.get("eligibility")
                if eligibility:
                    token_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
                    registered = next((row for row in eligibility["registry"]
                                       if row["token_sha256"] == "sha256:" + token_hash), None)
                    if registered is None:
                        return "", "", "ineligible"
                    participant_id = token_hash
                    row = connection.execute(
                        "SELECT arm_id FROM assignments WHERE participant_id=?", (participant_id,)).fetchone()
                    if row:
                        return participant_id, str(row["arm_id"]), ""
                enrollment = _window_state(spec, "enrollment")
                if enrollment != "active":
                    return "", "", enrollment
                count = connection.execute("SELECT COUNT(*) AS n FROM assignments").fetchone()["n"]
                if count >= int(spec["max_exposures"]):
                    return "", "", "max_exposures_reached"
                participant_id = participant_id or uuid.uuid4().hex
                arm_id = self.server.random.choice(spec["variants"])["arm_id"]
                connection.execute(
                    "INSERT INTO assignments(participant_id,arm_id,assigned_at) VALUES (?,?,?)",
                    (participant_id, arm_id, _now()))
            _record_event(self.server.root, spec["experiment_id"], participant_id, arm_id, "exposure")
            return participant_id, arm_id, ""

    def do_GET(self):
        parsed = urlsplit(self.path)
        route = parsed.path
        token = parse_qs(parsed.query).get("token", [""])[0]
        if route == "/status.json":
            self._headers(content_type="application/json; charset=utf-8")
            self.wfile.write((json.dumps(status(self.server.root), ensure_ascii=False) + "\n").encode())
            return
        if route != "/":
            self._headers(404)
            self.wfile.write(b"Not found")
            return
        participant_id, arm_id, stopped = self._assign(self._cookie(), token=token)
        if stopped:
            self._headers(403 if stopped == "ineligible" else 503)
            self.wfile.write(("Experiment stopped: " + stopped).encode("utf-8"))
            return
        variant = _variant(self.server.spec, arm_id)
        cookie = "ovo_landing_pid=%s; HttpOnly; SameSite=Lax; Path=/" % participant_id
        self._headers(cookie=cookie)
        self.wfile.write(_page(self.server.spec, variant, participant_id).encode("utf-8"))

    def do_POST(self):
        if self.path != "/convert":
            self._headers(404)
            self.wfile.write(b"Not found")
            return
        participant_id = self._cookie()
        if not participant_id:
            self._headers(409)
            self.wfile.write(b"No experiment assignment")
            return
        with _connect(self.server.root) as connection:
            row = connection.execute(
                "SELECT arm_id FROM assignments WHERE participant_id=?", (participant_id,)).fetchone()
        if row is None:
            self._headers(409)
            self.wfile.write(b"No experiment assignment")
            return
        outcome = _window_state(self.server.spec, "outcome")
        if outcome != "active":
            self._headers(410)
            self.wfile.write(("Experiment outcome unavailable: " + outcome).encode("utf-8"))
            return
        _record_event(self.server.root, self.server.spec["experiment_id"],
                      participant_id, str(row["arm_id"]), "conversion")
        self._headers()
        self.wfile.write(b"<html><body><p>Response recorded. Thank you.</p></body></html>")

    def log_message(self, fmt, *args):
        return


def create_server(root, host="127.0.0.1", port=8000):
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("landing server requires a loopback host") from exc
        if not address.is_loopback:
            raise ValueError("landing server is loopback-only; public deployment needs separate authorization")
    return LandingServer((host, int(port)), root)


def events(root):
    load_spec(root)
    with _connect(root) as connection:
        rows = connection.execute(
            "SELECT event_id,arm_id,event_type,occurred_at,source_ref,source_hash FROM events "
            "ORDER BY occurred_at,event_id").fetchall()
    return [dict(row) for row in rows]


def wilson_interval(conversions, exposures, z=1.96):
    n = int(exposures)
    if n <= 0:
        return None
    x = int(conversions)
    proportion = x / n
    z2 = z * z
    denominator = 1 + z2 / n
    center = (proportion + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / n + z2 / (4 * n * n)) / denominator
    return {"method": "wilson_score_95", "lower": round(max(0, center - margin), 6),
            "upper": round(min(1, center + margin), 6)}


def compare_conversion_rates(treatment, control):
    result = {"method": "newcombe_hybrid_score_95"}
    if not treatment.get("exposures") or not control.get("exposures"):
        result.update({"difference": None, "interval_95": None})
        return result
    treatment_rate = treatment["conversions"] / treatment["exposures"]
    control_rate = control["conversions"] / control["exposures"]
    treatment_interval = wilson_interval(treatment["conversions"], treatment["exposures"])
    control_interval = wilson_interval(control["conversions"], control["exposures"])
    difference = treatment_rate - control_rate
    lower = difference - math.sqrt(
        (treatment_rate - treatment_interval["lower"]) ** 2
        + (control_interval["upper"] - control_rate) ** 2)
    upper = difference + math.sqrt(
        (treatment_interval["upper"] - treatment_rate) ** 2
        + (control_rate - control_interval["lower"]) ** 2)
    result.update({
        "difference": round(difference, 6),
        "interval_95": {"lower": round(max(-1, lower), 6),
                        "upper": round(min(1, upper), 6)},
    })
    return result


def status(root):
    spec = load_spec(root)
    arms = []
    with _connect(root) as connection:
        for variant in spec["variants"]:
            arm_id = variant["arm_id"]
            assignments = connection.execute(
                "SELECT COUNT(*) AS n FROM assignments WHERE arm_id=?", (arm_id,)).fetchone()["n"]
            exposures = connection.execute(
                "SELECT COUNT(*) AS n FROM events WHERE arm_id=? AND event_type='exposure'",
                (arm_id,)).fetchone()["n"]
            conversions = connection.execute(
                "SELECT COUNT(*) AS n FROM events WHERE arm_id=? AND event_type='conversion'",
                (arm_id,)).fetchone()["n"]
            arms.append({
                "arm_id": arm_id, "role": variant["role"], "assignments": assignments,
                "exposures": exposures, "conversions": conversions,
                "conversion_rate": round(conversions / exposures, 6) if exposures else None,
                "wilson_interval_95": wilson_interval(conversions, exposures),
            })
    totals = {key: sum(row[key] for row in arms)
              for key in ("assignments", "exposures", "conversions")}
    stopped = totals["assignments"] >= int(spec["max_exposures"])
    enrollment = _window_state(spec, "enrollment")
    stop_reason = "max_exposures_reached" if stopped else (enrollment if enrollment != "active" else "")
    minimum = int(spec.get("min_exposures_per_arm", 30))
    comparisons = []
    controls = [row for row in arms if row["role"] == "control"]
    treatments = [row for row in arms if row["role"] == "treatment"]
    for treatment in treatments:
        for control in controls:
            comparison = compare_conversion_rates(treatment, control)
            comparison.update({
                "treatment_arm": treatment["arm_id"],
                "control_arm": control["arm_id"],
                "min_exposures_per_arm": minimum,
                "sample_status": ("sufficient" if treatment["exposures"] >= minimum
                                  and control["exposures"] >= minimum else "insufficient"),
            })
            comparisons.append(comparison)
    return {
        "schema": STATUS_SCHEMA,
        "experiment_id": spec["experiment_id"],
        "state": "stopped" if stop_reason else "accepting_new_visitors",
        "stop_reason": stop_reason,
        "conversion_definition": spec["conversion_definition"],
        "pricing": _pricing(spec),
        "arms": arms,
        "totals": totals,
        "analysis": {
            "comparisons": comparisons,
            "causal_status": "descriptive_only",
            "note": "Intervals describe uncertainty under the observed assignment; they do not automatically establish a winner, demand truth or business value.",
        },
        "causal_status": "descriptive_only",
        "evidence_boundary": "Observed local registration behavior is not payment, market prevalence or an automatic demand verdict.",
        "network": "loopback_only",
    }


def shared_design_hash(document):
    projection = {key: document.get(key) for key in
                  ("hypothesis", "design", "window", "stop_conditions")}
    return "sha256:" + hashlib.sha256(_canonical(projection).encode("utf-8")).hexdigest()


def export_experiment(root, export_spec, origin_version):
    if not isinstance(export_spec, dict):
        raise ValueError("landing export design must be an object")
    for key in ("population", "window", "comparability"):
        if not export_spec.get(key):
            raise ValueError("landing export requires %s" % key)
    try:
        planned = int(export_spec.get("planned_sample_per_arm"))
    except (TypeError, ValueError) as exc:
        raise ValueError("planned_sample_per_arm must be a positive integer") from exc
    if planned <= 0:
        raise ValueError("planned_sample_per_arm must be a positive integer")
    source = load_spec(root)
    if any(export_spec[key] != source[key] for key in ("population", "window", "comparability")) \
            or planned != int(source["planned_sample_per_arm"]):
        raise ValueError("registered design mismatch; create a new revision before changing the design")
    current = status(root)
    pricing = _pricing(source)
    raw_events = events(root)
    observations = []
    for arm in current["arms"]:
        if not arm["exposures"]:
            continue
        own = [row for row in raw_events if row["arm_id"] == arm["arm_id"]]
        aggregate = {
            "experiment_id": source["experiment_id"],
            "arm_id": arm["arm_id"],
            "assignments": arm["assignments"],
            "exposures": arm["exposures"],
            "conversions": arm["conversions"],
            "conversion_rate": arm["conversion_rate"],
            "event_hashes": sorted(row["source_hash"] for row in own),
        }
        if pricing:
            price = next(row["price_amount"] for row in pricing["arms"]
                         if row["arm_id"] == arm["arm_id"])
            aggregate.update(price_amount=price, currency=pricing["currency"])
        observations.append({
            "observation_id": "aggregate:%s" % arm["arm_id"],
            "arm_id": arm["arm_id"],
            "metric_id": "registration_conversion_rate",
            "subject_ref": "aggregate:%s" % arm["arm_id"],
            "observed_at": max(row["occurred_at"] for row in own),
            "value_number": arm["conversion_rate"],
            "source_ref": "askovo-landing:%s/%s/aggregate" % (
                source["experiment_id"], arm["arm_id"]),
            "source_hash": "sha256:" + hashlib.sha256(
                _canonical(aggregate).encode("utf-8")).hexdigest(),
            "evidence_grade": "observed",
            "eligible": True,
            "exclusion_reason": "",
        })
    has_two_arms = len(observations) >= 2
    document = {
        "schema": "ovo.experiment-contract/1",
        "experiment_id": source["experiment_id"],
        "origin_product": "askovo",
        "origin_version": str(origin_version),
        "task_id": str(export_spec.get("task_id") or source["experiment_id"]),
        "title": str(export_spec.get("title") or "Landing experiment %s" % source["experiment_id"]),
        "state": "completed" if current["state"] == "stopped" else "running",
        "hypothesis": copy.deepcopy(source["hypothesis"]),
        "design": {
            "experiment_type": "controlled_trial",
            "unit_of_analysis": "anonymous_participant",
            "population": str(source["population"]),
            "assignment": "randomized",
            "arms": [{
                "arm_id": variant["arm_id"],
                "role": variant["role"],
                "description": variant["title"],
                "planned_sample_size": planned,
            } for variant in source["variants"]],
            "primary_metrics": [{
                "metric_id": "registration_conversion_rate",
                "definition": source["conversion_definition"] + " Aggregate conversions divided by deduplicated exposures.",
                "unit": "ratio",
                "direction": "increase",
            }],
            "comparability": copy.deepcopy(source["comparability"]),
        },
        "window": copy.deepcopy(source["window"]),
        "stop_conditions": ["Stop new assignments after %d unique exposures." % source["max_exposures"]],
        "external_actions": False,
        "authorization_refs": [],
        "registered_by": source["registered_by"],
        "registered_at": source["registered_at"],
        "observations": observations,
        "outcome": {
            "status": "inconclusive" if has_two_arms else "not_evaluated",
            "causality": "descriptive_association" if has_two_arms else "not_claimed",
            "evidence_refs": [row["observation_id"] for row in observations],
            "evaluated_by": "",
            "evaluated_at": "",
            "notes": "Aggregate loopback observations only; registration intent is not payment. No winner, statistical significance, payment or causal verdict is inferred.",
        },
    }
    if pricing:
        for arm in document["design"]["arms"]:
            amount = next(row["price_amount"] for row in pricing["arms"]
                          if row["arm_id"] == arm["arm_id"])
            arm["price"] = {"amount": amount, "currency": pricing["currency"],
                            "definition": pricing["price_definition"]}
    if source.get("revision_of"):
        document["design"]["revision"] = {
            "revision_of": source["revision_of"],
            "previous_design_sha256": source["previous_design_sha256"],
            "reason": source["revision_reason"],
            "registered_at": source["registered_at"],
        }
    if export_spec.get("decision"):
        document["decision"] = copy.deepcopy(export_spec["decision"])
    document["design_sha256"] = shared_design_hash(document)
    return document


def write_shared_export(document, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

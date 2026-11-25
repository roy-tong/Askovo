"""Loopback-only primary-research survey execution and candidate export."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

SCHEMA = "askovo.survey-experiment/1"
STATUS_SCHEMA = "askovo.survey-experiment-status/1"
SPEC_NAME = "survey-experiment.json"
DB_NAME = "survey-experiment.sqlite3"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate(spec):
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError("survey schema must be %s" % SCHEMA)
    for key in ("survey_id", "title", "context_key", "consent_notice", "registered_by", "registered_at"):
        if not str(spec.get(key) or "").strip():
            raise ValueError("survey.%s is required" % key)
    if int(spec.get("max_responses", 0)) <= 0:
        raise ValueError("max_responses must be positive")
    questions = spec.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("survey questions must be a non-empty array")
    ids = set()
    for question in questions:
        if not isinstance(question, dict) or not ID_RE.fullmatch(str(question.get("question_id") or "")):
            raise ValueError("invalid question_id")
        if question["question_id"] in ids:
            raise ValueError("duplicate question_id")
        ids.add(question["question_id"])
        if not str(question.get("text") or "").strip() or question.get("kind") not in ("single_choice", "text"):
            raise ValueError("question text/kind is invalid")
        if question["kind"] == "single_choice" and (
                not isinstance(question.get("options"), list) or len(question["options"]) < 2):
            raise ValueError("single_choice needs at least two options")


def _connect(root):
    connection = sqlite3.connect(str(Path(root) / DB_NAME), timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def create(spec, out_dir):
    _validate(spec)
    out = Path(out_dir)
    if out.exists():
        raise FileExistsError("refusing to overwrite survey directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    (out / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    with _connect(out) as connection:
        connection.executescript("""
CREATE TABLE participants (participant_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE responses (
  participant_id TEXT PRIMARY KEY, submitted_at TEXT NOT NULL,
  answers_json TEXT NOT NULL, response_hash TEXT NOT NULL, source_ref TEXT NOT NULL
);
""")
    return {"status": "created", "schema": SCHEMA, "survey_id": spec["survey_id"],
            "path": str(out), "network": "loopback_only"}


def load_spec(root):
    spec = json.loads((Path(root) / SPEC_NAME).read_text(encoding="utf-8"))
    _validate(spec)
    return spec


def _participant(root, participant_id=""):
    with _connect(root) as connection:
        if participant_id:
            row = connection.execute("SELECT participant_id FROM participants WHERE participant_id=?",
                                     (participant_id,)).fetchone()
            if row:
                return participant_id
        participant_id = uuid.uuid4().hex
        connection.execute("INSERT INTO participants(participant_id,created_at) VALUES (?,?)",
                           (participant_id, _now()))
    return participant_id


def _page(spec):
    rows = ["""<h1>%s</h1><form method='post' action='/submit'>
<p><label><input type='checkbox' name='consent' value='accept' required> Consent: %s</label></p>""" % (
        html.escape(spec["title"]), html.escape(spec["consent_notice"]))]
    for question in spec["questions"]:
        qid = html.escape(question["question_id"])
        rows.append("<fieldset><legend>%s</legend>" % html.escape(question["text"]))
        if question["kind"] == "single_choice":
            for option in question["options"]:
                value = html.escape(str(option))
                rows.append("<label><input type='radio' name='%s' value='%s'> %s</label><br>" % (
                    qid, value, value))
        else:
            rows.append("<textarea name='%s' rows='5' cols='60'></textarea>" % qid)
        rows.append("</fieldset>")
    rows.append("<button type='submit'>Submit response</button></form>")
    return "<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body>%s</body></html>" % (
        html.escape(spec["title"]), "".join(rows))


class SurveyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root):
        self.root = Path(root)
        self.spec = load_spec(root)
        super().__init__(address, SurveyHandler)


class SurveyHandler(BaseHTTPRequestHandler):
    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ovo_survey_pid":
                return value
        return ""

    def _headers(self, status=200, cookie="", content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; form-action 'self'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        if self.path == "/status.json":
            self._headers(content_type="application/json; charset=utf-8")
            self.wfile.write((json.dumps(status(self.server.root), ensure_ascii=False) + "\n").encode())
            return
        if self.path != "/":
            self._headers(404)
            self.wfile.write(b"Not found")
            return
        participant = _participant(self.server.root, self._cookie())
        cookie = "ovo_survey_pid=%s; HttpOnly; SameSite=Lax; Path=/" % participant
        self._headers(cookie=cookie)
        self.wfile.write(_page(self.server.spec).encode("utf-8"))

    def do_POST(self):
        if self.path != "/submit":
            self._headers(404)
            self.wfile.write(b"Not found")
            return
        participant = self._cookie()
        if not participant:
            self._headers(409)
            self.wfile.write(b"No survey participant")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("invalid form size")
            form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            values = {key: items[0].strip() for key, items in form.items() if items}
            answers = _answers(self.server.spec, values)
        except (ValueError, UnicodeDecodeError) as exc:
            self._headers(400)
            self.wfile.write(("Invalid response: %s" % html.escape(str(exc))).encode())
            return
        try:
            result = _submit(self.server.root, self.server.spec, participant, answers)
        except ValueError as exc:
            status_code = 409 if "already" in str(exc) else 503
            self._headers(status_code)
            self.wfile.write(str(exc).encode())
            return
        self._headers()
        self.wfile.write(b"<html><body><p>Response recorded. Thank you.</p></body></html>")

    def log_message(self, fmt, *args):
        return


def _answers(spec, values):
    if values.get("consent") != "accept":
        raise ValueError("consent is required")
    answers = {}
    for question in spec["questions"]:
        qid = question["question_id"]
        value = str(values.get(qid) or "").strip()
        if question.get("required", True) and not value:
            raise ValueError("%s is required" % qid)
        if question["kind"] == "single_choice" and value and value not in question["options"]:
            raise ValueError("%s has an invalid choice" % qid)
        if len(value) > int(question.get("max_length", 2000)):
            raise ValueError("%s is too long" % qid)
        answers[qid] = value
    return answers


def _submit(root, spec, participant, answers):
    with _connect(root) as connection:
        known = connection.execute("SELECT participant_id FROM participants WHERE participant_id=?",
                                   (participant,)).fetchone()
        if not known:
            raise ValueError("No survey participant")
        duplicate = connection.execute("SELECT participant_id FROM responses WHERE participant_id=?",
                                       (participant,)).fetchone()
        if duplicate:
            raise ValueError("Response already recorded")
        count = connection.execute("SELECT COUNT(*) AS n FROM responses").fetchone()["n"]
        if count >= int(spec["max_responses"]):
            raise ValueError("Survey response limit reached")
        submitted = _now()
        source_ref = "askovo-survey:%s/response:%s" % (spec["survey_id"], participant)
        payload = {"survey_id": spec["survey_id"], "participant_id": participant,
                   "answers": answers, "consent": "accepted", "submitted_at": submitted}
        response_hash = "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO responses(participant_id,submitted_at,answers_json,response_hash,source_ref) VALUES (?,?,?,?,?)",
            (participant, submitted, json.dumps(answers, ensure_ascii=False), response_hash, source_ref))
    return {"status": "recorded", "submitted_at": submitted}


def create_server(root, host="127.0.0.1", port=8000):
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("survey server requires a loopback host") from exc
        if not address.is_loopback:
            raise ValueError("survey server is loopback-only")
    return SurveyServer((host, int(port)), root)


def status(root):
    spec = load_spec(root)
    with _connect(root) as connection:
        rows = connection.execute("SELECT answers_json FROM responses").fetchall()
    answers = [json.loads(row["answers_json"]) for row in rows]
    questions = {}
    for question in spec["questions"]:
        qid = question["question_id"]
        if question["kind"] == "single_choice":
            questions[qid] = {"kind": "single_choice",
                              "options": {str(option): sum(1 for row in answers if row.get(qid) == option)
                                          for option in question["options"]}}
        else:
            questions[qid] = {"kind": "text",
                              "text_responses": sum(1 for row in answers if str(row.get(qid) or "").strip())}
    return {"schema": STATUS_SCHEMA, "survey_id": spec["survey_id"],
            "responses": len(answers), "max_responses": spec["max_responses"],
            "questions": questions, "network": "loopback_only",
            "boundary": "Aggregate response counts only; no prevalence, representativeness or demand verdict is inferred."}


def export_candidates(root):
    spec = load_spec(root)
    with _connect(root) as connection:
        rows = connection.execute(
            "SELECT participant_id,submitted_at,answers_json,source_ref FROM responses ORDER BY submitted_at").fetchall()
    candidates = []
    for row in rows:
        answers = json.loads(row["answers_json"])
        text = "\n".join("%s\n%s" % (question["text"], answers.get(question["question_id"], ""))
                         for question in spec["questions"])
        candidates.append({
            "candidate_id": "survey-%s-%s" % (spec["survey_id"], row["participant_id"][:12]),
            "context_key": spec["context_key"], "behavior_ref": "",
            "alternative_behavior": "", "consequence": "", "counter_evidence": [],
            "user_voice": text, "note": "Survey candidate; named human review is still required.",
            "source_ref": row["source_ref"], "collected_at": row["submitted_at"],
            "consent_ref": "survey-consent:%s" % row["participant_id"],
            "participant_ref": "survey:%s" % row["participant_id"],
        })
    return candidates


def write_candidates(root, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(export_candidates(root), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

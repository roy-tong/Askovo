from __future__ import annotations

import http.client
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
sys.path.insert(0, str(ROOT / "skills/askovo/scripts"))
import survey_experiment  # noqa: E402


class SurveyExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "survey"
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def spec(self, maximum=10):
        return {
            "schema": "askovo.survey-experiment/1",
            "survey_id": "survey-demo", "title": "Research survey",
            "context_key": "synthetic-mobile-check",
            "consent_notice": "Consent to anonymous local research storage",
            "registered_by": "research-owner", "registered_at": "2026-11-24T00:00:00Z",
            "max_responses": maximum,
            "questions": [
                {"question_id": "q_role", "text": "What is your role?", "kind": "single_choice",
                 "required": True, "options": ["founder", "researcher"]},
                {"question_id": "q_pain", "text": "Describe the problem <script>alert(1)</script>",
                 "kind": "text", "required": True, "max_length": 500},
            ],
        }

    def start(self, maximum=10):
        survey_experiment.create(self.spec(maximum), self.root)
        server = survey_experiment.create_server(self.root, port=0)
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        return server

    @staticmethod
    def request(server, method="GET", data=None, cookie=""):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request(method, "/submit" if method == "POST" else "/", body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        result = (response.status, dict(response.getheaders()), payload)
        connection.close()
        return result

    @staticmethod
    def answers():
        return {"consent": "accept", "q_role": "founder",
                "q_pain": "The current workflow requires repeated manual checks."}

    def test_valid_response_is_deduplicated_and_aggregated(self):
        server = self.start()
        status, headers, body = self.request(server)
        self.assertEqual(200, status)
        self.assertIn("Consent", body)
        self.assertNotIn("<script>alert(1)</script>", body)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(200, self.request(server, "POST", self.answers(), cookie)[0])
        self.assertEqual(409, self.request(server, "POST", self.answers(), cookie)[0])
        report = survey_experiment.status(self.root)
        self.assertEqual(1, report["responses"])
        self.assertEqual(1, report["questions"]["q_role"]["options"]["founder"])
        self.assertEqual(1, report["questions"]["q_pain"]["text_responses"])
        candidates = survey_experiment.export_candidates(self.root)
        self.assertEqual(1, len(candidates))
        self.assertEqual("synthetic-mobile-check", candidates[0]["context_key"])
        self.assertNotIn("evidence_level", candidates[0])
        self.assertTrue(candidates[0]["consent_ref"])

    def test_required_answer_and_choice_are_validated(self):
        server = self.start()
        _, headers, _ = self.request(server)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        missing = dict(self.answers(), q_pain="")
        self.assertEqual(400, self.request(server, "POST", missing, cookie)[0])
        invalid = dict(self.answers(), q_role="other")
        self.assertEqual(400, self.request(server, "POST", invalid, cookie)[0])
        no_consent = dict(self.answers(), consent="no")
        self.assertEqual(400, self.request(server, "POST", no_consent, cookie)[0])
        self.assertEqual(0, survey_experiment.status(self.root)["responses"])

    def test_response_limit_stops_new_submissions(self):
        server = self.start(maximum=1)
        _, headers, _ = self.request(server)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.request(server, "POST", self.answers(), cookie)
        _, other_headers, _ = self.request(server)
        other_cookie = other_headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(503, self.request(server, "POST", self.answers(), other_cookie)[0])

    def test_non_loopback_bind_is_refused(self):
        survey_experiment.create(self.spec(), self.root)
        with self.assertRaisesRegex(ValueError, "loopback"):
            survey_experiment.create_server(self.root, host="0.0.0.0", port=0)

    def test_cli_create_status_and_candidate_export(self):
        spec_path = Path(self.tmp.name) / "survey.json"
        spec_path.write_text(json.dumps(self.spec()), encoding="utf-8")
        created = subprocess.run([
            sys.executable, str(CLI), "experiment", "survey", "create",
            "--spec", str(spec_path), "--out", str(self.root),
        ], text=True, capture_output=True)
        self.assertEqual(0, created.returncode, created.stderr + created.stdout)
        status = subprocess.run([
            sys.executable, str(CLI), "experiment", "survey", "status", "--dir", str(self.root),
        ], text=True, capture_output=True)
        self.assertEqual(0, status.returncode, status.stderr + status.stdout)
        out = Path(self.tmp.name) / "candidates.json"
        exported = subprocess.run([
            sys.executable, str(CLI), "experiment", "survey", "export-candidates",
            "--dir", str(self.root), "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(0, exported.returncode, exported.stderr + exported.stdout)
        self.assertEqual([], json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()

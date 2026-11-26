from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import landing_experiment  # noqa: E402
import participant_screening  # noqa: E402


class LandingExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "experiment"
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def spec(self, maximum=10):
        spec = {
            "schema": "askovo.landing-experiment/1",
            "experiment_id": "landing-demo",
            "hypothesis": {
                "statement": "Concept B earns more qualified registrations than concept A.",
                "falsification_condition": "Concept B does not exceed concept A on qualified registration.",
            },
            "registered_by": "research-owner",
            "registered_at": "2026-11-24T00:00:00Z",
            "conversion_definition": "Visitor submits the explicit registration-intent form.",
            "consent_notice": "Synthetic local test; anonymous assignment and conversion counts only.",
            "max_exposures": maximum,
            "assignment_seed": 42,
            "variants": [
                {"arm_id": "control", "role": "control", "title": "Concept A",
                 "body": "Existing workflow", "cta_label": "Register interest"},
                {"arm_id": "treatment", "role": "treatment", "title": "Concept B <script>alert(1)</script>",
                 "body": "New workflow", "cta_label": "Register interest"},
            ],
        }
        spec.update(self.export_design())
        return spec

    def export_design(self):
        return {
            "task_id": "A-T03",
            "title": "Synthetic landing demand test",
            "population": "Synthetic qualified local visitors",
            "planned_sample_per_arm": 3,
            "window": {"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
            "comparability": {
                "same_task_set": True,
                "same_acceptance_rubric": True,
                "same_budget": False,
                "controlled_variables": ["Registration definition", "Local runtime"],
                "known_differences": ["Landing concept", "Budget not measured"],
            },
        }

    def start(self, maximum=10, spec=None):
        landing_experiment.create(spec or self.spec(maximum), self.root)
        server = landing_experiment.create_server(self.root, port=0)
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        return server

    @staticmethod
    def request(server, method="GET", path="/", cookie=""):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        result = (response.status, dict(response.getheaders()), body)
        connection.close()
        return result

    def test_http_assignment_deduplicates_events_and_escapes_content(self):
        server = self.start(maximum=3)
        status, headers, body = self.request(server)
        self.assertEqual(200, status)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("anonymous assignment", body)
        source_hash = "sha256:" + hashlib.sha256(
            (self.root / landing_experiment.SPEC_NAME).read_bytes()).hexdigest()
        self.assertIn(source_hash, body)
        self.request(server, cookie=cookie)
        second_status, _, _ = self.request(server)
        self.assertEqual(200, second_status)
        converted, _, _ = self.request(server, method="POST", path="/convert", cookie=cookie)
        self.assertEqual(200, converted)
        self.request(server, method="POST", path="/convert", cookie=cookie)
        report = landing_experiment.status(self.root)
        self.assertEqual(2, report["totals"]["assignments"])
        self.assertEqual(2, report["totals"]["exposures"])
        self.assertEqual(1, report["totals"]["conversions"])
        self.assertTrue(all((row["conversion_rate"] is not None) if row["assignments"]
                            else (row["conversion_rate"] is None) for row in report["arms"]))
        events = landing_experiment.events(self.root)
        self.assertTrue(all(row["source_hash"].startswith("sha256:") for row in events))

    def test_unassigned_conversion_and_non_loopback_bind_are_refused(self):
        server = self.start()
        status, _, _ = self.request(server, method="POST", path="/convert")
        self.assertEqual(409, status)
        with self.assertRaisesRegex(ValueError, "loopback"):
            landing_experiment.create_server(self.root, host="0.0.0.0", port=0)

    def test_max_exposures_stops_new_assignments(self):
        server = self.start(maximum=1)
        self.assertEqual(200, self.request(server)[0])
        self.assertEqual(503, self.request(server)[0])
        report = landing_experiment.status(self.root)
        self.assertEqual("max_exposures_reached", report["stop_reason"])

    def test_restart_preserves_assignment_and_conversion_counts(self):
        server = self.start(maximum=2)
        status, headers, _ = self.request(server)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.request(server, method="POST", path="/convert", cookie=cookie)
        server.shutdown()
        server.server_close()
        self.servers.remove(server)
        restarted = landing_experiment.create_server(self.root, port=0)
        self.servers.append(restarted)
        thread = threading.Thread(target=restarted.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.request(restarted, cookie=cookie)
        report = landing_experiment.status(self.root)
        self.assertEqual(1, report["totals"]["assignments"])
        self.assertEqual(1, report["totals"]["exposures"])
        self.assertEqual(1, report["totals"]["conversions"])

    def test_shared_export_contains_aggregate_observations_without_participant_ids(self):
        server = self.start(maximum=6)
        for _ in range(6):
            status, headers, _ = self.request(server)
            self.assertEqual(200, status)
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            self.request(server, method="POST", path="/convert", cookie=cookie)
        document = landing_experiment.export_experiment(
            self.root, self.export_design(), "2.24.0")
        self.assertEqual("ovo.experiment-contract/1", document["schema"])
        self.assertEqual("askovo", document["origin_product"])
        self.assertEqual("inconclusive", document["outcome"]["status"])
        self.assertEqual("descriptive_association", document["outcome"]["causality"])
        self.assertTrue(document["observations"])
        self.assertTrue(all(row["eligible"] for row in document["observations"]))
        self.assertNotIn("participant_id", json.dumps(document))
        self.assertEqual(document["design_sha256"],
                         landing_experiment.shared_design_hash(document))

    def test_post_exposure_export_cannot_replace_registered_design(self):
        server = self.start(maximum=6)
        self.request(server)
        changed = self.export_design()
        changed["population"] = "A different post-hoc population"
        changed["planned_sample_per_arm"] = 50
        with self.assertRaisesRegex(ValueError, "registered design mismatch"):
            landing_experiment.export_experiment(self.root, changed, "2.24.0")

    def test_registered_spec_file_drift_is_rejected(self):
        landing_experiment.create(self.spec(), self.root)
        path = self.root / landing_experiment.SPEC_NAME
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["population"] = "Post-hoc population"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "registered design fingerprint mismatch"):
            landing_experiment.load_spec(self.root)

    def test_price_sensitivity_freezes_structured_price_points(self):
        spec = self.spec()
        spec["validation_mode"] = "price_sensitivity"
        spec["currency"] = "USD"
        spec["price_definition"] = "Monthly subscription price shown before registration"
        spec["variants"][0]["price_amount"] = 10
        spec["variants"][1]["price_amount"] = 20
        landing_experiment.create(spec, self.root)
        report = landing_experiment.status(self.root)
        self.assertEqual("USD", report["pricing"]["currency"])
        self.assertEqual([10, 20], [row["price_amount"] for row in report["pricing"]["arms"]])
        document = landing_experiment.export_experiment(self.root, self.export_design(), "2.24.0")
        self.assertEqual([10, 20], [row["price"]["amount"] for row in document["design"]["arms"]])
        self.assertEqual("USD", document["design"]["arms"][0]["price"]["currency"])
        self.assertNotIn("pricing", document["design"])
        self.assertIn("not payment", document["outcome"]["notes"])

    def test_price_sensitivity_rejects_invalid_or_duplicate_price_points(self):
        for index, (first, second) in enumerate(((10, 10), (10, "unknown"), (-1, 20))):
            spec = self.spec()
            spec["validation_mode"] = "price_sensitivity"
            spec["currency"] = "USD"
            spec["price_definition"] = "Monthly price"
            spec["variants"][0]["price_amount"] = first
            spec["variants"][1]["price_amount"] = second
            with self.subTest(first=first, second=second):
                with self.assertRaises(ValueError):
                    landing_experiment.create(spec, self.root / ("invalid-%d" % index))

    def test_empty_landing_export_stays_unevaluated(self):
        landing_experiment.create(self.spec(), self.root)
        document = landing_experiment.export_experiment(
            self.root, self.export_design(), "2.24.0")
        self.assertEqual([], document["observations"])
        self.assertEqual("not_evaluated", document["outcome"]["status"])
        self.assertEqual("not_claimed", document["outcome"]["causality"])

    def test_cli_exports_new_shared_contract(self):
        landing_experiment.create(self.spec(), self.root)
        design_path = Path(self.tmp.name) / "export-design.json"
        design_path.write_text(json.dumps(self.export_design()), encoding="utf-8")
        out = Path(self.tmp.name) / "shared-experiment.json"
        argv = [
            sys.executable, str(CLI), "experiment", "landing", "export",
            "--dir", str(self.root), "--design", str(design_path), "--out", str(out),
        ]
        result = subprocess.run(argv, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual("ovo.experiment-contract/1", payload["schema"])
        second = subprocess.run(argv, text=True, capture_output=True)
        self.assertEqual(1, second.returncode)

    def test_enrollment_window_rejects_late_new_participants(self):
        spec = self.spec()
        spec["window"] = {"start": "2026-11-20T00:00:00Z", "end": "2026-11-21T00:00:00Z"}
        landing_experiment.create(spec, self.root)
        with mock.patch.object(landing_experiment, "_now", return_value="2026-11-22T00:00:00Z"):
            server = landing_experiment.create_server(self.root, port=0)
            self.servers.append(server)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            status, _, body = self.request(server)
            self.assertEqual(503, status)
            self.assertIn("enrollment_closed", body)
            report = landing_experiment.status(self.root)
            self.assertEqual(0, report["totals"]["assignments"])
            self.assertEqual("enrollment_closed", report["stop_reason"])

    def test_existing_participant_can_convert_during_outcome_window(self):
        spec = self.spec()
        spec["window"] = {"start": "2026-11-20T00:00:00Z", "end": "2026-11-21T00:00:00Z"}
        spec["outcome_window"] = {"start": "2026-11-20T00:00:00Z", "end": "2026-11-25T00:00:00Z"}
        with mock.patch.object(landing_experiment, "_now", return_value="2026-11-20T12:00:00Z"):
            server = self.start(spec=spec)
            status, headers, _ = self.request(server)
        self.assertEqual(200, status)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        with mock.patch.object(landing_experiment, "_now", return_value="2026-11-23T12:00:00Z"):
            self.assertEqual(503, self.request(server)[0])
            self.assertEqual(200, self.request(server, method="POST", path="/convert", cookie=cookie)[0])
        report = landing_experiment.status(self.root)
        self.assertEqual(1, report["totals"]["assignments"])
        self.assertEqual(1, report["totals"]["conversions"])

    def test_conversion_after_outcome_window_is_not_recorded(self):
        spec = self.spec()
        spec["window"] = {"start": "2026-11-20T00:00:00Z", "end": "2026-11-21T00:00:00Z"}
        spec["outcome_window"] = {"start": "2026-11-20T00:00:00Z", "end": "2026-11-25T00:00:00Z"}
        with mock.patch.object(landing_experiment, "_now", return_value="2026-11-20T12:00:00Z"):
            server = self.start(spec=spec)
            status, headers, _ = self.request(server)
        self.assertEqual(200, status)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        with mock.patch.object(landing_experiment, "_now", return_value="2026-11-26T12:00:00Z"):
            status, _, body = self.request(server, method="POST", path="/convert", cookie=cookie)
            self.assertEqual(410, status)
            self.assertIn("outcome_closed", body)
        self.assertEqual(0, landing_experiment.status(self.root)["totals"]["conversions"])

    def test_registered_eligibility_token_is_required_and_deduplicated(self):
        token = "eligible-token"
        spec = self.spec()
        spec["eligibility"] = {
            "screening_sha256": "sha256:" + "a" * 64,
            "registry": [{"token_sha256": "sha256:" + hashlib.sha256(token.encode()).hexdigest(),
                          "participant_ref_hash": "sha256:" + "b" * 64}],
        }
        server = self.start(spec=spec)
        self.assertEqual(403, self.request(server)[0])
        self.assertEqual(403, self.request(server, path="/?token=wrong")[0])
        status, headers, _ = self.request(server, path="/?token=" + token)
        self.assertEqual(200, status)
        first_cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, headers, _ = self.request(server, path="/?token=" + token)
        self.assertEqual(200, status)
        self.assertEqual(first_cookie, headers["Set-Cookie"].split(";", 1)[0])
        self.assertEqual(1, landing_experiment.status(self.root)["totals"]["assignments"])
        self.assertNotIn(token, json.dumps(landing_experiment.export_experiment(
            self.root, self.export_design(), "2.25.0")))

    def test_screening_issues_tokens_only_to_research_ready_participants(self):
        document = participant_screening.build(
            {"plan_id": "p1", "target_participants": {"criteria": "target user", "count": 2}},
            [{"participant_ref": "ready", "source_ref": "screen-1", "reason": "qualified",
              "eligible": True, "evidence_refs": ["evidence-1"], "consent_state": "accepted"},
             {"participant_ref": "pending", "source_ref": "screen-2", "reason": "consent pending",
              "eligible": True, "evidence_refs": ["evidence-2"], "consent_state": "pending"}],
            reviewed_by="research-owner")
        issue = getattr(participant_screening, "issue_tokens", None)
        self.assertIsNotNone(issue)
        invitations = issue(document, "landing-demo")
        self.assertEqual(1, len(invitations["invitations"]))
        self.assertEqual(1, len(invitations["eligibility"]["registry"]))
        self.assertNotIn("pending", json.dumps(invitations))
        self.assertNotIn("ready", json.dumps(invitations["eligibility"]))

    def deployment_spec(self):
        digest = hashlib.sha256((self.root / landing_experiment.SPEC_NAME).read_bytes()).hexdigest()
        return {
            "schema": "askovo.landing-deployment/1",
            "deployment_id": "deploy-local-1",
            "source_sha256": "sha256:" + digest,
            "authorization": {"authorized_by": "owner", "authorization_ref": "deploy-approval-1"},
            "argv": ["fake-deploy"], "timeout_seconds": 5,
            "external_deployment": False,
        }

    def test_deploy_adapter_binds_source_and_returns_public_url(self):
        landing_experiment.create(self.spec(), self.root)
        self.assertIsNotNone(importlib.util.find_spec("landing_deployment"))
        import landing_deployment
        result = landing_deployment.deploy(
            self.deployment_spec(), self.root,
            process_runner=lambda **kwargs: {"exit_code": 0, "error": "",
                "stdout": b'{"url":"https://example.test/experiment","deployment_id":"deploy-local-1","observed_at":"2026-11-26T00:00:00Z"}',
                "stderr": b""})
        self.assertEqual("DEPLOYMENT_REPORTED", result["status"])
        self.assertEqual("https://example.test/experiment", result["url"])
        self.assertFalse(result["deployment_verified"])
        self.assertFalse(result["external_deployment_executed"])

    def test_deploy_verifies_public_page_against_frozen_source(self):
        landing_experiment.create(self.spec(), self.root)
        import landing_deployment
        spec = self.deployment_spec()
        spec["verify_url"] = True
        body = ("<html><head><meta name='askovo-source-sha256' content='%s'></head></html>"
                % spec["source_sha256"]).encode("utf-8")
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit=-1):
                return body
        opened = []
        def opener(url, timeout):
            opened.append((url, timeout))
            return Response()
        result = landing_deployment.deploy(
            spec, self.root,
            process_runner=lambda **kwargs: {"exit_code": 0, "error": "",
                "stdout": b'{"url":"https://example.test/experiment","deployment_id":"deploy-local-1","observed_at":"2026-11-26T00:00:00Z"}',
                "stderr": b""}, url_opener=opener)
        self.assertEqual("DEPLOYMENT_VERIFIED", result["status"])
        self.assertTrue(result["deployment_verified"])
        self.assertEqual([("https://example.test/experiment", 5.0)], opened)

    def test_deploy_verification_rejects_a_different_experiment_version(self):
        landing_experiment.create(self.spec(), self.root)
        import landing_deployment
        spec = self.deployment_spec()
        spec["verify_url"] = True
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit=-1):
                return b"<meta name='askovo-source-sha256' content='sha256:other'>"
        result = landing_deployment.deploy(
            spec, self.root,
            process_runner=lambda **kwargs: {"exit_code": 0, "error": "",
                "stdout": b'{"url":"https://example.test/experiment","deployment_id":"deploy-local-1","observed_at":"2026-11-26T00:00:00Z"}',
                "stderr": b""}, url_opener=lambda url, timeout: Response())
        self.assertEqual("DEPLOYMENT_REPORTED", result["status"])
        self.assertFalse(result["deployment_verified"])
        self.assertEqual("source_hash_mismatch", result["verification_error"])

    def test_cli_deploys_through_explicit_adapter(self):
        landing_experiment.create(self.spec(), self.root)
        script = Path(self.tmp.name) / "deployer.py"
        script.write_text(
            "import json\nprint(json.dumps({'url':'https://example.test/experiment',"
            "'deployment_id':'deploy-local-1','observed_at':'2026-11-26T00:00:00Z'}))\n",
            encoding="utf-8")
        spec = self.deployment_spec()
        spec["argv"] = [sys.executable, str(script)]
        adapter = Path(self.tmp.name) / "adapter.json"
        adapter.write_text(json.dumps(spec), encoding="utf-8")
        out = Path(self.tmp.name) / "deployment.json"
        result = subprocess.run([
            sys.executable, str(CLI), "experiment", "landing", "deploy",
            "--dir", str(self.root), "--adapter", str(adapter), "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertEqual("DEPLOYMENT_REPORTED", json.loads(out.read_text())["status"])

    def test_cli_create_and_status(self):
        spec_path = Path(self.tmp.name) / "spec.json"
        spec_path.write_text(json.dumps(self.spec()), encoding="utf-8")
        created = subprocess.run([
            sys.executable, str(CLI), "experiment", "landing", "create",
            "--spec", str(spec_path), "--out", str(self.root),
        ], text=True, capture_output=True)
        self.assertEqual(0, created.returncode, created.stderr + created.stdout)
        status = subprocess.run([
            sys.executable, str(CLI), "experiment", "landing", "status",
            "--dir", str(self.root),
        ], text=True, capture_output=True)
        self.assertEqual(0, status.returncode, status.stderr + status.stdout)
        payload = json.loads(status.stdout)
        self.assertEqual("askovo.landing-experiment-status/1", payload["schema"])
        self.assertEqual("descriptive_only", payload["causal_status"])


if __name__ == "__main__":
    unittest.main()

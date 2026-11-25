from __future__ import annotations

import http.client
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import landing_experiment  # noqa: E402


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

    def start(self, maximum=10):
        landing_experiment.create(self.spec(maximum), self.root)
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

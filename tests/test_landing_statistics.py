from __future__ import annotations

import http.client
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/askovo/scripts"))
import landing_experiment


class LandingStatisticsTest(unittest.TestCase):
    def test_wilson_interval_has_known_bounds(self):
        interval = landing_experiment.wilson_interval(60, 100)
        self.assertAlmostEqual(0.5020, interval["lower"], places=3)
        self.assertAlmostEqual(0.6906, interval["upper"], places=3)
        self.assertEqual("wilson_score_95", interval["method"])

    def test_newcombe_difference_uses_both_arm_intervals(self):
        treatment = {"conversions": 60, "exposures": 100}
        control = {"conversions": 40, "exposures": 100}
        comparison = landing_experiment.compare_conversion_rates(treatment, control)
        self.assertAlmostEqual(0.2, comparison["difference"], places=4)
        self.assertLess(comparison["interval_95"]["lower"], 0.2)
        self.assertGreater(comparison["interval_95"]["upper"], 0.2)
        self.assertEqual("newcombe_hybrid_score_95", comparison["method"])

    def test_zero_denominator_stays_unknown(self):
        self.assertIsNone(landing_experiment.wilson_interval(0, 0))
        comparison = landing_experiment.compare_conversion_rates(
            {"conversions": 0, "exposures": 0}, {"conversions": 1, "exposures": 2})
        self.assertIsNone(comparison["difference"])
        self.assertIsNone(comparison["interval_95"])

    def test_status_marks_minimum_sample_and_reports_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "experiment"
            spec = {
                "schema": "askovo.landing-experiment/1",
                "experiment_id": "stats-demo",
                "hypothesis": {"statement": "B exceeds A", "falsification_condition": "B does not exceed A"},
                "registered_by": "owner", "registered_at": "2026-11-24T00:00:00Z",
                "conversion_definition": "registration", "consent_notice": "local test",
                "max_exposures": 2, "min_exposures_per_arm": 1, "assignment_seed": 4,
                "population": "local statistics fixture", "planned_sample_per_arm": 1,
                "window": {"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"},
                "comparability": {"same_task_set": True, "same_acceptance_rubric": True,
                                  "same_budget": True, "controlled_variables": [], "known_differences": []},
                "variants": [
                    {"arm_id": "control", "role": "control", "title": "A", "body": "A", "cta_label": "Go"},
                    {"arm_id": "treatment", "role": "treatment", "title": "B", "body": "B", "cta_label": "Go"},
                ],
            }
            landing_experiment.create(spec, root)
            server = landing_experiment.create_server(root, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for _ in range(2):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    response.read()
                    connection.close()
                report = landing_experiment.status(root)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
            comparison = report["analysis"]["comparisons"][0]
            self.assertEqual("sufficient", comparison["sample_status"])
            self.assertEqual(1, comparison["min_exposures_per_arm"])
            for arm in report["arms"]:
                self.assertIsNotNone(arm["wilson_interval_95"])


if __name__ == "__main__":
    unittest.main()

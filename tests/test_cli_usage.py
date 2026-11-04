"""Packaged CLI discovery regressions."""
import unittest

from askovo.cli import USAGE


class CliUsageTests(unittest.TestCase):
    def test_decision_command_is_discoverable_in_short_usage(self):
        self.assertIn("decision <action> <study>", USAGE)
        self.assertIn("record/list/replay", USAGE)


if __name__ == "__main__":
    unittest.main()

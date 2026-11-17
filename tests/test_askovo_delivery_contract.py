#!/usr/bin/env python3
"""Delivery contract (review 2026-11-17 §2.3/§5): machine-readable and visible
at first interaction, not buried in an audit report."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
CONTRACT = ROOT / "docs/delivery-contract.json"

TERMINAL_STATES = ("DELIVERED", "DELIVERED_WITH_GAP", "BLOCKED_USER_INPUT",
                   "UNSUPPORTED", "FAILED_UNRESOLVED")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(CLI), *args],
                          check=False, capture_output=True, text=True, timeout=120, env=env)


class DeliveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.bare = run_cli()
        cls.banner = cls.bare.stdout + cls.bare.stderr

    def test_contract_file_is_wellformed(self) -> None:
        contract = self.contract
        self.assertEqual("askovo.delivery-contract/1", contract["schema"])
        self.assertEqual(set(TERMINAL_STATES), set(contract["terminal_states"]))
        self.assertTrue(contract["supported_intents"])
        self.assertTrue(contract["excluded"])
        self.assertTrue(contract["evidence_requirements"])
        for intent in contract["supported_intents"]:
            self.assertIn("intent", intent)
            self.assertIn("entry", intent)

    def test_first_interaction_matches_the_contract(self) -> None:
        self.assertEqual(2, self.bare.returncode, self.banner)
        for state in TERMINAL_STATES:
            self.assertIn(state, self.banner)
        for intent in self.contract["supported_intents"]:
            self.assertIn(intent["intent"].split("：")[0].split(":")[0], self.banner)
        self.assertIn("docs/delivery-contract.json", self.banner)
        for piece in self.contract["first_interaction"]["must_mention"]:
            self.assertIn(piece, self.banner)

    def test_procurement_branch_is_explicit_and_never_executes(self) -> None:
        branch = self.contract["requires_procurement"]
        self.assertEqual("BLOCKED_USER_INPUT", branch["terminal_state"])
        self.assertTrue(branch["requires_procurement"])
        self.assertFalse(branch["transaction_executed"])
        self.assertTrue(self.contract["procurement"]["preferred_alternatives"])
        self.assertFalse(self.contract["procurement"]["automatic_purchase_allowed"])
        self.assertIn("requires_procurement", self.banner)

    def test_unsupported_requests_route_instead_of_pretending(self) -> None:
        excluded = " ".join(item["what"] for item in self.contract["excluded"])
        for marker in ("发布", "投放", "收款", "采购"):
            self.assertIn(marker, excluded)
        self.assertIn("UNSUPPORTED", self.banner)


if __name__ == "__main__":
    unittest.main()

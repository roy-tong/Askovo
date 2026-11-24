from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "skills/askovo/assets/open-source-connectors.json"
CLI = ROOT / "skills/askovo/scripts/askovo.py"


class ArcticShiftConnectorTests(unittest.TestCase):
    def test_reddit_access_bases_include_historical_archive(self) -> None:
        spec = importlib.util.spec_from_file_location("askovo_arctic_access_test", CLI)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertIn("historical_archive", module.REDDIT_ACCESS_BASES)

    def test_historical_connector_is_registered(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        connector = next(row for row in registry["connectors"] if row["id"] == "reddit-arctic-shift-historical")
        self.assertEqual("historical_only", connector["decision"])
        self.assertEqual(["historical_archive"], connector["allowed_access_bases"])
        self.assertEqual("9f04bcc88857dbefb4ce752f68a4c51720d10528", connector["reviewed_revision"])

    def test_existing_hmc_adapter_config_is_accepted(self) -> None:
        spec = importlib.util.spec_from_file_location("askovo_arctic_test", CLI)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        config = {
            "connector_id": "reddit-arctic-shift-historical",
            "connector_revision": "9f04bcc88857dbefb4ce752f68a4c51720d10528",
            "connector_license": "MIT",
            "collection_mode": "historical_search",
            "access_basis": "historical_archive",
            "policy_status": "historical_data_only",
            "data_rights_reviewed_at": "2026-11-22",
        }
        self.assertEqual([], module._validate_connector_selection("reddit", config))


if __name__ == "__main__":
    unittest.main()

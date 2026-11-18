#!/usr/bin/env python3
"""CDP transport design contract.

Regression for the 2026-11-17 live-chain finding: the platform catalog marked
kickstarter (and five other platforms) cdp: true, the capture transport
accepted them, but no study design could ever pass — the scripted-connector
enums had no access basis for them and the registry held only blocked
scrapers. The first-party CDP transport declaration
(connector_id=cdp-authorized-visible-page, access_basis=cdp_authorized_visible_page)
is now validated against the platform catalog instead, and the scaffolded
canonical stores must parse through the strict reader from line one.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


askovo = _load("askovo_cdp_design_test", SCRIPTS / "askovo.py")
write_integrity = _load("write_integrity_cdp_design_test", SCRIPTS / "write_integrity.py")


def _adapter(**overrides):
    base = {
        "enabled": True,
        "researcher_role": "external_third_party",
        "connector_id": "cdp-authorized-visible-page",
        "connector_revision": askovo.sure_engine.VERSION,
        "connector_license": "MIT",
        "collection_mode": "authorized_visible_page",
        "access_basis": "cdp_authorized_visible_page",
        "policy_status": "approved_for_study",
        "terms_reviewed_at": "2026-11-17",
        "data_rights_reviewed_at": "2026-11-17",
        "data_rights_basis": "authorized visible pages via the operator's browser session",
        "retention_rule": "study-local; deleted with the study",
        "backer_data_policy": "no backer personal data; public page text only",
        "allow_personal_data": False,
        "min_unique_campaigns": 5,
        "min_unique_creators": 3,
        "max_campaign_share": 0.3,
        "max_creator_share": 0.3,
        "max_single_day_share": 0.25,
        "require_original_source": True,
        "treat_ai_summaries_as_discovery_only": True,
    }
    base.update(overrides)
    return base


class CdpTransportDesignTests(unittest.TestCase):
    def test_kickstarter_cdp_transport_passes_design(self):
        study = {"source_adapters": {"kickstarter": _adapter()}}
        errors = askovo._validate_kickstarter_config(study)
        self.assertEqual([], errors)

    def test_scripted_kickstarter_scrapers_stay_blocked(self):
        # The registry connector is decision=blocked with no access bases; a
        # scripted declaration must still fail exactly as before.
        study = {"source_adapters": {"kickstarter": _adapter(
            connector_id="kickstarter-ksinsights",
            connector_revision="2bf2cb25750127a1420a46062f4235d6009326a8",
            connector_license="MIT",
            collection_mode="historical_search",
            access_basis="historical_dataset",
            policy_status="historical_data_only",
        )}}
        errors = askovo._validate_kickstarter_config(study)
        self.assertTrue(errors)
        self.assertTrue(any("blocked" in message or "access_basis" in message
                            for message in errors))

    def test_cdp_basis_on_non_cdp_platform_is_rejected(self):
        reddit_adapter = _adapter(
            min_unique_subreddits=3,
            min_unique_threads=20,
            max_subreddit_share=0.5,
            max_thread_share=0.15,
        )
        study = {"source_adapters": {"reddit": reddit_adapter}}
        errors = askovo._validate_source_adapter_config(
            study, "reddit", askovo.REDDIT_CONFIG_REQUIRED, askovo.REDDIT_ACCESS_BASES)
        self.assertTrue(any("cdp: true" in message for message in errors), errors)

    def test_cdp_transport_requires_engine_revision(self):
        study = {"source_adapters": {"kickstarter": _adapter(connector_revision="0.0.0")}}
        errors = askovo._validate_kickstarter_config(study)
        self.assertTrue(any("engine version" in message for message in errors))

    def test_cdp_transport_requires_dedicated_collection_mode(self):
        study = {"source_adapters": {"kickstarter": _adapter(collection_mode="live_monitoring")}}
        errors = askovo._validate_kickstarter_config(study)
        self.assertTrue(any("collection_mode" in message for message in errors))


class ScaffoldedCanonicalStoresTests(unittest.TestCase):
    def test_every_template_jsonl_parses_through_the_strict_reader(self):
        template = ROOT / "skills/askovo/assets/study-template"
        stores = list(template.rglob("*.jsonl"))
        self.assertTrue(stores, "expected scaffolded JSONL stores to exist")
        for store in stores:
            with self.subTest(store=store.relative_to(template)):
                # A freshly scaffolded study must survive its first canonical
                # write path (e.g. `capture accept`) without repair.
                records = write_integrity.read_jsonl(store, label=str(store))
                self.assertIsInstance(records, list)


if __name__ == "__main__":
    unittest.main()

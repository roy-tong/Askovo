#!/usr/bin/env python3
"""C-01 §3 error-registry contract: exactly ten reason codes, no more, no less.

Contract source: `ai输出/ovo-C01-委托语义合同-v1-20261115.md` §3 (the frozen
delegation-semantics contract shared by Askovo, Growovo and Verovo).

Why this file exists: `reason_code` is the machine-readable half of "correct
refusal". A caller decides from it whether to supply input, ask for human review,
inspect a diff or stop — and every projection compares it by equality. Nothing
else in the suite would notice an eleventh code appearing or one silently
disappearing, because each individual test only asserts the code it expects.

The ten codes are frozen; changing them is a contract change (three repositories,
version bump), not a local edit.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import decide  # noqa: E402
import decision_brief  # noqa: E402
import external_bridge  # noqa: E402
import issue_structuring  # noqa: E402
import research_delta  # noqa: E402

#: C-01 §3, verbatim and in contract order.
C01_REASON_CODES = (
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
    "REVIEW_REQUIRED",
    "UNSUPPORTED_SCOPE",
    "POLICY_DENIED",
    "RATE_LIMITED",
    "STALE_SOURCE",
    "INDETERMINATE_EXTERNAL_ACTION",
    "ARTIFACT_PARTIAL",
    "INTERNAL_ERROR",
)

#: Detail codes are **not** reason codes: they live under
#: `stale_reasons[].detail_code` and never on the top-level `reason_code`.
DETAIL_ONLY_CODES = ("BROKEN_REFERENCE", "INPUT_DRIFT")

REFUSAL_CLASSES = (
    (decide, "DecideError"),
    (issue_structuring, "IssueError"),
    (decision_brief, "BriefError"),
    (research_delta, "DeltaError"),
    (external_bridge, "BridgeError"),
)


class ReasonCodeContractTests(unittest.TestCase):

    def test_registry_equals_the_c01_contract(self) -> None:
        self.assertEqual(sorted(C01_REASON_CODES), sorted(decide.REASON_CODES),
                         "Askovo's REASON_CODES drifted from the C-01 registry")

    def test_registry_has_no_duplicates_and_exactly_ten_codes(self) -> None:
        self.assertEqual(len(C01_REASON_CODES), len(set(C01_REASON_CODES)))
        self.assertEqual(10, len(decide.REASON_CODES),
                         "an eleventh code (or a removed one) is a three-repository "
                         "contract change, not a local edit")
        self.assertEqual(10, len(set(decide.REASON_CODES)))

    def test_every_refusal_class_defaults_into_the_registry(self) -> None:
        for module, name in REFUSAL_CLASSES:
            error = getattr(module, name)
            instance = error("contract probe")
            self.assertIn(instance.reason_code, C01_REASON_CODES,
                          f"{module.__name__}.{name} defaults outside the C-01 registry")

    def test_no_script_emits_a_code_outside_the_registry(self) -> None:
        """Static scan: every literal `reason_code` emitted by the scripts is registered."""
        patterns = (
            re.compile(r'"reason_code"\s*:\s*"([A-Z_]+)"'),
            re.compile(r'reason_code\s*=\s*"([A-Z_]+)"'),
        )
        emitted: dict[str, set] = {}
        for path in sorted(SCRIPTS.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for pattern in patterns:
                for code in pattern.findall(source):
                    emitted.setdefault(code, set()).add(path.name)
        unknown = {code: sorted(files) for code, files in emitted.items()
                   if code not in C01_REASON_CODES}
        self.assertEqual({}, unknown,
                         "reason codes outside the C-01 registry: "
                         + repr(sorted(unknown.items())))
        self.assertTrue(emitted, "the scan found no reason_code literal at all")

    def test_detail_codes_never_occupy_the_reason_code_field(self) -> None:
        self.assertNotIn("INPUT_DRIFT", C01_REASON_CODES)
        self.assertNotIn("BROKEN_REFERENCE", C01_REASON_CODES)
        source = (SCRIPTS / "decision_brief.py").read_text(encoding="utf-8")
        for code in DETAIL_ONLY_CODES:
            self.assertNotIn(f'"code": "{code}"', source,
                             f"{code} must stay a detail code, not a reason code")
            self.assertIn(f'"detail_code": "{code}"', source,
                          f"{code} must remain visible as a detail code")


if __name__ == "__main__":
    unittest.main()

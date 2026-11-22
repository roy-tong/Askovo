from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DecisionProofPagesTest(unittest.TestCase):
    def test_decision_replay_pages_expose_real_safe_hold_flow(self):
        for relative in ("examples/decision-replay.html", "en/examples/decision-replay.html"):
            page = ROOT / "website" / relative
            self.assertTrue(page.is_file(), relative)
            text = page.read_text(encoding="utf-8")
            for token in ("deterministic_safe_hold", "decision", "record", "replay",
                          "contradiction", "Synthetic", "test_new_mapped_contradiction"):
                self.assertIn(token, text)
            self.assertNotIn("<script", text)

    def test_bilingual_homepages_link_story_and_decision_proof(self):
        for relative, prefix in (("index.html", "./"), ("en/index.html", "./")):
            text = (ROOT / "website" / relative).read_text(encoding="utf-8")
            self.assertIn("Generate Anything. Prove What Matters.", text)
            self.assertIn(prefix + "examples/decision-replay.html", text)


if __name__ == "__main__":
    unittest.main()

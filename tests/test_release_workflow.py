from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_branch_without_tag_skips_instead_of_failing(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        block = text[text.index("TARGET_SHA="):text.index("git checkout --detach")]
        self.assertIn('if [[ "$GITHUB_REF" == refs/heads/release/* ]]; then', block)
        self.assertIn("rev-parse --verify --quiet", block)
        self.assertIn("exit 0", block)
        self.assertIn("exit 2", block)

    def test_tag_push_still_checks_out_the_tag(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("git checkout --detach \"${TARGET_SHA}\"", text)


if __name__ == "__main__":
    unittest.main()

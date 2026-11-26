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

    def test_whole_release_job_is_skipped_until_tag_exists(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("id: ready", text)
        self.assertIn('echo "ready=false" >> "$GITHUB_OUTPUT"', text)
        self.assertIn("if: needs.release-guard.outputs.ready == 'true'", text)

    def test_tag_push_still_checks_out_the_tag(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("git checkout --detach \"${TARGET_SHA}\"", text)

    def test_guard_exposes_ready_to_dependent_jobs(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        guard = text[text.index("  release-guard:"):text.index("  release:")]
        self.assertIn("outputs:", guard)
        self.assertIn("ready: ${{ steps.ready.outputs.ready }}", guard)

    def test_pypi_skip_checks_the_exact_candidate_version(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn('https://pypi.org/pypi/askovo/${VER}/json', text)

    def test_rc_github_release_is_marked_as_prerelease(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn('if [[ "$TAG" == *rc* ]]; then PRERELEASE="--prerelease"; fi', text)
        self.assertIn('gh release edit "$TAG" -R "$GITHUB_REPOSITORY" --notes-file /tmp/notes.md $PRERELEASE', text)
        self.assertIn('dist/*.whl dist/*.tar.gz $PRERELEASE', text)


if __name__ == "__main__":
    unittest.main()

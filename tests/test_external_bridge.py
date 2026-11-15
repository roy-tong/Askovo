#!/usr/bin/env python3
"""A-06 external research bridge safety boundary (AC A29-A33).

Frozen acceptance tests for `askovo external-research`. The bridge runs a host
adapter as a subprocess, so every assertion here runs a **real** child process
against a temporary script and a temporary study: no mocks stand in for "we did
not pass the environment variable".

The boundary under test: an explicit env allowlist (A29), a signed command
registry instead of an arbitrary `--command` (A30), bounded stdout/stderr (A31),
a per-run id that never overwrites an older result (A32), output paths that
cannot escape the study (A30), and URLs that stay candidates without any attempt
to verify them over the network (A33).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/askovo/scripts/askovo.py"
SAMPLE = ROOT / "examples/sample-study"
SCRIPTS = ROOT / "skills/askovo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import external_bridge  # noqa: E402

SECRET = "ASKOVO_TEST_SECRET_DO_NOT_LEAK"

# The child dumps its own environment to a file the test controls, so the proof
# is a real subprocess's view — not the parent's claim about what it passed.
ENV_DUMP = """
import json
import os
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(dict(os.environ), ensure_ascii=False), encoding="utf-8")
print(json.dumps({"sources": [{"url": "https://example.com/a", "title": "T",
                               "excerpt": "E", "claim": "C"}], "notes": ["n"]}))
"""


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("ASKOVO_AUTHOR_SALT", "a-06-frozen-test-salt")
    if env:
        merged.update(env)
    return subprocess.run([sys.executable, str(CLI), "external-research", *args],
                          capture_output=True, text=True, timeout=180, env=merged)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class BridgeHelpers:
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.study = self.dir / "study"
        shutil.copytree(SAMPLE, self.study)
        self.runs = self.study / "04-findings" / "external-research"
        self.registry_path = self.study / "01-sources" / "external-research.json"
        self.dump_path = self.dir / "child-env.json"

    # -- fixture plumbing -------------------------------------------------- #

    def write_script(self, body: str, name: str = "adapter.py") -> Path:
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        return path

    def write_registry(self, entries: list[dict], **overrides) -> Path:
        payload = {
            "schema_version": "1.0",
            "updated_at": "2026-11-15",
            "commands": entries,
        }
        payload.update(overrides)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
        return self.registry_path

    def register(self, script: Path, *, command_id: str = "env-dumper",
                 extra_env: list[str] | None = None) -> dict:
        entry = {
            "id": command_id,
            "label": "synthetic environment dumper",
            "adapter": str(script),
            "argv": [sys.executable, str(script), str(self.dump_path)],
            "sha256": sha256_file(script),
            "access_basis": "synthetic local adapter; no network",
            "reviewed_at": "2026-11-15",
            "reviewed_by": "research-lead",
            "timeout_seconds": 60,
        }
        if extra_env:
            entry["extra_env"] = extra_env
        self.write_registry([entry])
        return entry

    def child_env(self) -> dict:
        return json.loads(self.dump_path.read_text(encoding="utf-8"))

    def run_entry(self, *extra: str, env: dict | None = None
                  ) -> tuple[subprocess.CompletedProcess, dict]:
        completed = run_cli(str(self.study), "--authorize", "--json", *extra, env=env)
        try:
            return completed, json.loads(completed.stdout)
        except json.JSONDecodeError:
            return completed, {"raw": completed.stdout, "stderr": completed.stderr}

    def run_files(self) -> list[Path]:
        if not self.runs.is_dir():
            return []
        return sorted(path for path in self.runs.glob("*.json") if path.is_file())


class EnvAllowlistTests(BridgeHelpers, unittest.TestCase):
    """A29: the child only sees the allowlist, never the parent environment."""

    def test_child_cannot_read_unauthorized_env_secret(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        completed, record = self.run_entry("--command", "env-dumper",
                                   env={SECRET: "leak-me"})
        self.assertEqual(0, completed.returncode, record)
        child_env = self.child_env()
        self.assertNotIn(SECRET, child_env, "an unauthorized secret must not reach the adapter")
        self.assertNotIn("leak-me", json.dumps(child_env))
        self.assertTrue(child_env.get("PATH"), "PATH is on the allowlist and must be present")

    def test_env_is_built_from_the_allowlist_not_inherited(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, record = self.run_entry("--command", "env-dumper")
        child_env = set(self.child_env())
        # The record lists exactly what the bridge passed; anything else in the
        # child's view was injected by the platform, not by Askovo.
        platform_injected = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}
        self.assertEqual(set(), child_env - set(record["env_keys"]) - platform_injected,
                         "the bridge must not pass a variable it did not list")
        allowed = set(external_bridge.DEFAULT_ENV_ALLOWLIST) | set(
            external_bridge.CONTEXT_ENV_KEYS) | platform_injected
        self.assertTrue(child_env <= allowed, f"unexpected env keys: {sorted(child_env - allowed)}")
        for key in external_bridge.CONTEXT_ENV_KEYS:
            self.assertIn(key, child_env)
        self.assertEqual(sorted(set(record["env_keys"])), record["env_keys"])

    def test_registry_can_allow_one_extra_variable_explicitly(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script, extra_env=["MY_ADAPTER_TOKEN"])
        completed, record = self.run_entry("--command", "env-dumper",
                                   env={"MY_ADAPTER_TOKEN": "token-123"})
        self.assertEqual(0, completed.returncode, record)
        self.assertEqual("token-123", self.child_env().get("MY_ADAPTER_TOKEN"))
        self.assertIn("MY_ADAPTER_TOKEN", record["env_allowlist"])
        self.assertNotIn("token-123", json.dumps(record),
                         "the run record lists allowlisted keys, never their secret values")

    def test_run_record_lists_the_effective_allowlist(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, record = self.run_entry("--command", "env-dumper")
        self.assertIn("PATH", record["env_allowlist"])
        self.assertNotIn(SECRET, record["env_allowlist"])


class CommandWhitelistTests(BridgeHelpers, unittest.TestCase):
    """A30: only a signed registry entry may run."""

    def test_unregistered_command_is_refused(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.write_registry([])
        completed = run_cli(str(self.study), "--authorize", "--json",
                            "--command", f"{sys.executable} {script} {self.dump_path}")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertIn("external-research.json", body["reason"])
        self.assertEqual([], self.run_files())

    def test_registered_command_runs(self) -> None:
        script = self.write_script(ENV_DUMP)
        entry = self.register(script)
        completed, record = self.run_entry("--command", entry["id"])
        self.assertEqual(0, completed.returncode, record)
        self.assertEqual(entry["id"], record["command_id"])
        self.assertEqual(1, len(self.run_files()))

    def test_tampered_adapter_hash_is_refused(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        script.write_text(ENV_DUMP + "\nprint('tampered')\n", encoding="utf-8")
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertIn("sha256", body["reason"].lower())

    def test_registry_entry_needs_an_access_basis(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.write_registry([{
            "id": "no-basis",
            "adapter": str(script),
            "argv": [sys.executable, str(script), str(self.dump_path)],
            "sha256": sha256_file(script),
        }])
        completed, body = self.run_entry("--command", "no-basis")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertIn("access_basis", body["reason"])

    def test_trusted_local_requires_authorize(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.write_registry([])
        completed = run_cli(str(self.study), "--trusted-local", "--json",
                            "--command", f"{sys.executable} {script} {self.dump_path}")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)

    def test_trusted_local_is_recorded_in_the_run(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.write_registry([])
        completed, record = self.run_entry(
            "--trusted-local", "--command", f"{sys.executable} {script} {self.dump_path}")
        self.assertEqual(0, completed.returncode, record)
        self.assertTrue(record["trusted_local"])
        self.assertTrue(record["command_sha256"].startswith("sha256:"))
        self.assertIn("trusted-local", json.dumps(record["notes"], ensure_ascii=False))


class OutputCapTests(BridgeHelpers, unittest.TestCase):
    """A31: an oversized stream fails clearly; it is never truncated into success."""

    def test_oversized_stdout_fails_clearly(self) -> None:
        script = self.write_script(
            "import json\nprint(json.dumps({'sources': [{'url': 'https://e.com/a',"
            " 'title': 'T', 'excerpt': 'x' * 400000, 'claim': 'C'}]}))\n")
        self.register(script)
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("RATE_LIMITED", body["reason_code"])
        self.assertIn("stdout", body["reason"])
        self.assertEqual([], self.run_files(), "an oversized run must not leave a record")

    def test_oversized_stderr_fails_clearly(self) -> None:
        script = self.write_script(
            "import sys\nsys.stderr.write('e' * 200000)\n"
            "print('{\"sources\": []}')\n")
        self.register(script)
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("RATE_LIMITED", body["reason_code"])
        self.assertIn("stderr", body["reason"])

    def test_cap_can_only_be_lowered(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        completed, record = self.run_entry("--command", "env-dumper",
                                           "--max-stdout-bytes", "1048576")
        self.assertEqual(0, completed.returncode, record)
        self.assertEqual(external_bridge.DEFAULT_MAX_STDOUT_BYTES,
                         record["limits"]["max_stdout_bytes"],
                         "an operator cannot raise the cap above the registry default")


class RunIdTests(BridgeHelpers, unittest.TestCase):
    """A32: every run gets its own id and never overwrites an older result."""

    def test_two_runs_in_the_same_second_do_not_overwrite(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, first = self.run_entry("--command", "env-dumper")
        _, second = self.run_entry("--command", "env-dumper")
        self.assertNotEqual(first["run_id"], second["run_id"])
        files = self.run_files()
        self.assertEqual(2, len(files), "both runs must be kept")
        for path in files:
            json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(any(first["run_id"] in path.name for path in files))
        self.assertTrue(any(second["run_id"] in path.name for path in files))

    def test_run_record_carries_the_run_identity(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, record = self.run_entry("--command", "env-dumper")
        self.assertTrue(record["run_id"].startswith("ext-"))
        self.assertTrue(record["started_at"])
        self.assertTrue(record["finished_at"])
        self.assertEqual("askovo.external-research/1", record["schema"])


class PathEscapeTests(BridgeHelpers, unittest.TestCase):
    """A30: the output path cannot leave the authorized study directory."""

    def _run_with_output(self, target: str) -> tuple[subprocess.CompletedProcess, dict]:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        return self.run_entry("--command", "env-dumper", "--output", target)

    def test_parent_traversal_output_is_refused(self) -> None:
        completed, body = self._run_with_output("../../evil.json")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertFalse((self.dir.parent / "evil.json").exists())

    def test_absolute_output_outside_study_is_refused(self) -> None:
        outside = self.dir / "outside.json"
        completed, body = self._run_with_output(str(outside))
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertFalse(outside.exists())

    def test_symlink_escape_is_refused(self) -> None:
        link = self.study / "04-findings" / "linked"
        link.symlink_to(self.dir, target_is_directory=True)
        completed, body = self._run_with_output("04-findings/linked/escaped.json")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertFalse((self.dir / "escaped.json").exists())

    def test_inside_output_is_allowed(self) -> None:
        completed, record = self._run_with_output("04-findings/custom-run.json")
        self.assertEqual(0, completed.returncode, record)
        self.assertTrue((self.study / "04-findings" / "custom-run.json").is_file())


class CandidateOnlyTests(BridgeHelpers, unittest.TestCase):
    """A33: URLs are candidates; nothing is fetched and no evidence level moves."""

    def test_urls_stay_candidates(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, record = self.run_entry("--command", "env-dumper")
        source = record["sources"][0]
        self.assertIsNone(source["evidence_level"])
        self.assertEqual("candidate", source["status"])
        self.assertTrue(record["review_required"])
        self.assertEqual("not_attempted", source["url_verification"])

    def test_no_network_is_attempted(self) -> None:
        script = self.write_script(ENV_DUMP)
        entry = self.register(script)
        import socket
        import urllib.request

        original_socket = socket.socket
        original_urlopen = urllib.request.urlopen

        def blocked(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("the bridge must not open a socket or fetch a URL")

        socket.socket = blocked
        urllib.request.urlopen = blocked
        try:
            record = external_bridge.run(
                self.study, entry["id"], authorize=True, trusted_local=False,
                question="q")
        finally:
            socket.socket = original_socket
            urllib.request.urlopen = original_urlopen
        self.assertEqual("askovo.external-research/1", record["schema"])
        self.assertEqual(1, len(record["sources"]))

    def test_non_http_url_is_refused(self) -> None:
        script = self.write_script(
            "import json\nprint(json.dumps({'sources': [{'url': 'file:///etc/passwd',"
            " 'title': 'T', 'excerpt': 'E', 'claim': 'C'}]}))\n")
        self.register(script)
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("INPUT_REQUIRED", body["reason_code"])

    def test_malformed_payload_is_refused(self) -> None:
        script = self.write_script("print('not json')\n")
        self.register(script)
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("INPUT_REQUIRED", body["reason_code"])

    def test_missing_sources_is_refused(self) -> None:
        script = self.write_script("import json\nprint(json.dumps({'sources': []}))\n")
        self.register(script)
        completed, body = self.run_entry("--command", "env-dumper")
        self.assertEqual(2, completed.returncode, body)
        self.assertEqual("INPUT_REQUIRED", body["reason_code"])

    def test_boundary_says_the_link_is_unverified(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.register(script)
        _, record = self.run_entry("--command", "env-dumper")
        self.assertIn("候选", record["boundary"])
        self.assertIn("未定级", record["boundary"])


class LegacyCompatibilityTests(BridgeHelpers, unittest.TestCase):
    """The pre-A-06 `--command` path is refused with a migration hint."""

    def test_legacy_invocation_requires_trusted_local(self) -> None:
        script = self.write_script(ENV_DUMP)
        self.write_registry([])
        completed = run_cli(str(self.study), "--authorize", "--json",
                            "--command", f"{sys.executable} {script} {self.dump_path}")
        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual("POLICY_DENIED", body["reason_code"])
        self.assertIn("--trusted-local", (body.get("suggestion") or "") + body["reason"])


if __name__ == "__main__":
    unittest.main()

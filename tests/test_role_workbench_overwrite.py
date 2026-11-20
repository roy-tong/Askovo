from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/askovo/scripts"
CLI = SCRIPTS / "askovo.py"
NODES = ("scene", "user", "pain", "need", "feature", "product", "business")


def load_roles():
    spec = importlib.util.spec_from_file_location("role_catalog_overwrite_under_test", SCRIPTS / "role_catalog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


roles = load_roles()


def run_cli(*arguments: str):
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def make_study(study: Path) -> None:
    study.mkdir(parents=True)
    chain = {
        "id": "PR01",
        "title": "candidate",
        "nodes": {
            node: {"statement": f"statement-{node}", "rationale": "test rationale", "evidence_ids": [], "assumptions": []}
            for node in NODES
        },
    }
    (study / "04-findings").mkdir()
    (study / "04-findings/product-reasoning.json").write_text(json.dumps({"chains": [chain]}), encoding="utf-8")
    (study / "04-findings/demand-judgments.json").write_text("[]\n", encoding="utf-8")
    (study / "02-data").mkdir()
    (study / "02-data/evidence.jsonl").write_text("", encoding="utf-8")
    (study / "study.json").write_text(json.dumps({
        "study_id": "role-overwrite-test",
        "title": "AI Agent 任务研究",
        "product_domain": "software",
        "decision": {"question": "是否进入该市场"},
    }), encoding="utf-8")


def workbench_files(study: Path) -> dict[str, bytes]:
    root = study / "01-sources" / "role-workbench"
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def backups(study: Path) -> list[Path]:
    return sorted((study / "01-sources").glob("role-workbench.bak-*"))


class RoleWorkbenchOverwriteTest(unittest.TestCase):
    def test_existing_workbench_refuses_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            first = run_cli("roles", "scaffold", str(study), "--role", "R52", "--json")
            self.assertEqual(0, first.returncode, first.stderr)
            second = run_cli("roles", "scaffold", str(study), "--role", "R52")
            self.assertEqual(2, second.returncode)
            self.assertIn("--overwrite --confirm", second.stderr)

    def test_force_alone_still_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            roles.scaffold_workplan(study, ["R52"])
            with self.assertRaisesRegex(ValueError, "--overwrite --confirm"):
                roles.scaffold_workplan(study, ["R52"], force=True)
            forced = run_cli("roles", "scaffold", str(study), "--role", "R52", "--force")
            self.assertEqual(2, forced.returncode)
            self.assertIn("--overwrite --confirm", forced.stderr)

    def test_overwrite_without_confirm_only_previews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            created = run_cli("roles", "scaffold", str(study), "--role", "R52", "--json")
            self.assertEqual(0, created.returncode, created.stderr)
            workplan_path = study / "01-sources" / "role-workbench" / "workplan.json"
            plan = json.loads(workplan_path.read_text(encoding="utf-8"))
            plan["roles"][0]["owner"] = "alice"
            workplan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = workbench_files(study)
            previewed = run_cli("roles", "scaffold", str(study), "--role", "R52", "--overwrite", "--json")
            self.assertEqual(0, previewed.returncode, previewed.stderr)
            result = json.loads(previewed.stdout)
            self.assertEqual("preview", result["status"])
            self.assertIsNone(result["backup"])
            self.assertFalse(result["backup_created"])
            changed = {item["path"]: item for item in result["changes"]}
            self.assertIn("workplan.json", changed)
            self.assertEqual("modified", changed["workplan.json"]["change"])
            self.assertGreaterEqual(changed["workplan.json"]["changed_lines"], 1)
            self.assertTrue(changed["workplan.json"]["before_sha256"])
            self.assertTrue(changed["workplan.json"]["after_sha256"])
            self.assertTrue(changed["workplan.json"]["preview"])
            self.assertEqual(before, workbench_files(study))
            self.assertEqual([], backups(study))

    def test_overwrite_confirm_backs_up_and_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            created = run_cli("roles", "scaffold", str(study), "--role", "R52", "--json")
            self.assertEqual(0, created.returncode, created.stderr)
            workplan_path = study / "01-sources" / "role-workbench" / "workplan.json"
            plan = json.loads(workplan_path.read_text(encoding="utf-8"))
            plan["roles"][0]["owner"] = "alice"
            workplan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written = run_cli("roles", "scaffold", str(study), "--role", "R52", "--overwrite", "--confirm", "--json")
            self.assertEqual(0, written.returncode, written.stderr)
            result = json.loads(written.stdout)
            self.assertEqual("written", result["status"])
            self.assertTrue(result["backup_created"])
            backup_path = Path(result["backup"])
            self.assertTrue(backup_path.is_dir())
            self.assertEqual("role-workbench", backup_path.name.split(".bak-")[0])
            backup_plan = json.loads((backup_path / "workplan.json").read_text(encoding="utf-8"))
            self.assertEqual("alice", backup_plan["roles"][0]["owner"])
            new_plan = json.loads(workplan_path.read_text(encoding="utf-8"))
            self.assertIsNone(new_plan["roles"][0]["owner"])
            self.assertEqual(1, len(backups(study)))

    def test_rerun_with_same_content_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            make_study(study)
            created = run_cli("roles", "scaffold", str(study), "--role", "R52", "--json")
            self.assertEqual(0, created.returncode, created.stderr)
            first = run_cli("roles", "scaffold", str(study), "--role", "R52", "--overwrite", "--confirm", "--json")
            self.assertEqual("unchanged", json.loads(first.stdout)["status"], first.stderr)
            self.assertEqual(0, len(backups(study)))
            second = run_cli("roles", "scaffold", str(study), "--role", "R52", "--overwrite", "--confirm", "--json")
            self.assertEqual(0, second.returncode, second.stderr)
            result = json.loads(second.stdout)
            self.assertEqual("unchanged", result["status"])
            self.assertEqual([], result["changes"])
            self.assertFalse(result["backup_created"])
            self.assertEqual(0, len(backups(study)))


if __name__ == "__main__":
    unittest.main()

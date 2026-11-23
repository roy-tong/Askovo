import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "skills/askovo/scripts/sure_engine.py"


class RuntimeImportIsolationTests(unittest.TestCase):
    def test_sure_engine_has_only_the_explicit_cdp_dynamic_loader(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertLessEqual(
            source.count("importlib.util.spec_from_file_location"), 1,
            "sibling modules should use standard imports; only lazy CDP may load by path",
        )

    def test_thin_package_and_direct_engine_load_do_not_shadow_each_other(self):
        code = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
import askovo
package_file = Path(askovo.__file__).resolve()
spec = importlib.util.spec_from_file_location('askovo_isolated_engine', root / 'skills/askovo/scripts/sure_engine.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert Path(sys.modules['askovo'].__file__).resolve() == package_file
assert package_file.name == '__init__.py', package_file
assert module.study_context.current_study_context() is None
print('ok')
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("ok", completed.stdout)


if __name__ == "__main__":
    unittest.main()

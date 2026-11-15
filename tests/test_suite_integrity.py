#!/usr/bin/env python3
"""Repository-level guard: no test may be silently skipped.

Twice in the A lane a test class was declared **without** `unittest.TestCase`, so
its methods were never collected while the suite stayed green (A-05: six tests;
A-06: seven tests). The mistake is invisible in a green run, which makes it a
missing check rather than a slip. This guard turns it into an immediate red:

1. every `tests/test_*.py` must collect exactly as many cases as it defines
   `def test_` — a mismatch names the module and the difference;
2. a class that defines `test_*` methods but does not inherit
   `unittest.TestCase` is reported by name (the case the count alone only implies);
3. `@unittest.skip*` decorators must be whitelisted with a reason — an optional
   dependency is the only accepted reason;
4. a module-level `load_tests` / `setUpModule` / `tearDownModule` hook is
   flagged, because each can hide or skip tests outside the definition count.

Deliberately static for 3-4 (a runtime skip inside a test body is caught by the
count, not by inspection) and dynamic for 1-2 (`TestLoader` is the authority on
what unittest actually collects).
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: `(module file name, test name) -> reason substring`. Adding a skip means
#: adding an entry here, so a skip can never be silent.
SKIP_WHITELIST = {
    ("test_askovo_tools.py", "test_xlsx_formula_is_a_string_and_small_pool_is_retained"):
        "openpyxl optional dependency is not installed",
    ("test_askovo_tools.py", "test_github_yaml_parses"):
        "PyYAML is not installed",
}

_HIDING_HOOKS = ("load_tests", "setUpModule", "tearDownModule")


def load_module(path: Path):
    """Import a test module the same way discovery does, tolerating both roots."""
    for name in (path.stem, f"tests.{path.stem}"):
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name not in (path.stem, "tests", f"tests.{path.stem}"):
                raise
    spec = importlib.util.spec_from_file_location(f"_integrity_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(f"_integrity_{path.stem}", module)
    spec.loader.exec_module(module)
    return module


def count_cases(suite) -> int:
    """Count leaf cases in a (possibly nested) suite."""
    total = 0
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            total += count_cases(item)
        else:
            total += 1
    return total


def defined_tests(tree: ast.AST) -> list:
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")]


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _skip_reason(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    for keyword in node.keywords:
        if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    for argument in node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
    return ""


class SuiteIntegrityTests(unittest.TestCase):
    """The guard itself. Each assertion is a check that was missing twice."""

    def test_every_module_collects_exactly_what_it_defines(self) -> None:
        problems: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            defined = defined_tests(tree)
            collected = count_cases(
                unittest.TestLoader().loadTestsFromModule(load_module(path)))
            if len(defined) != collected:
                problems.append(
                    f"{path.name}: defines {len(defined)} `def test_` but unittest collects "
                    f"{collected} (difference {len(defined) - collected})")
        self.assertEqual(
            [], problems,
            "silently skipped tests — a class is probably missing `unittest.TestCase`:\n"
            + "\n".join(problems))

    def test_every_test_class_is_a_testcase(self) -> None:
        problems: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            module = load_module(path)
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if not any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and item.name.startswith("test_") for item in node.body):
                    continue
                candidate = getattr(module, node.name, None)
                if not (isinstance(candidate, type) and issubclass(candidate, unittest.TestCase)):
                    problems.append(
                        f"{path.name}::{node.name} defines test_* methods but is not a "
                        f"unittest.TestCase — its tests are never collected")
        self.assertEqual([], problems, "non-TestCase test classes:\n" + "\n".join(problems))

    def test_skip_decorators_are_whitelisted_with_a_reason(self) -> None:
        problems: list[str] = []
        seen: set[tuple[str, str]] = set()
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in defined_tests(tree):
                for decorator in getattr(node, "decorator_list", []):
                    name = _decorator_name(decorator)
                    if not name.startswith("unittest.skip"):
                        continue
                    reason = _skip_reason(decorator)
                    key = (path.name, node.name)
                    seen.add(key)
                    allowed = SKIP_WHITELIST.get(key)
                    if allowed is None:
                        problems.append(
                            f"{path.name}::{node.name} uses {name} without a whitelist entry")
                    elif allowed not in reason:
                        problems.append(
                            f"{path.name}::{node.name} skip reason {reason!r} does not record "
                            f"the whitelisted reason {allowed!r}")
        stale = sorted(set(SKIP_WHITELIST) - seen)
        self.assertEqual([], problems, "unlisted skips:\n" + "\n".join(problems))
        self.assertEqual([], stale,
                         "whitelist entries that no longer skip anything: " + ", ".join(
                             f"{module}::{name}" for module, name in stale))

    def test_no_module_level_hook_can_hide_tests(self) -> None:
        problems: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {node.name for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for hook in _HIDING_HOOKS:
                if hook in names:
                    problems.append(
                        f"{path.name} defines {hook}() — it can skip or hide tests outside the "
                        f"definition count; move the logic into a TestCase")
        self.assertEqual([], problems, "module-level hooks:\n" + "\n".join(problems))

    def test_definition_total_matches_the_documented_suite_size(self) -> None:
        """A second, independent count: the repo total must equal the sum per file."""
        per_file = {}
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            per_file[path.name] = len(defined_tests(tree))
        collected = 0
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            collected += count_cases(
                unittest.TestLoader().loadTestsFromModule(load_module(path)))
        self.assertEqual(sum(per_file.values()), collected,
                         f"definition sum {sum(per_file.values())} != collected {collected}")


if __name__ == "__main__":
    unittest.main()

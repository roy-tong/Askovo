"""`sure` entry point.

Stage 1 packaging: expose the existing runtime and assets as one command.
Editable installs only; stage 2 moves the runtime into this package.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent


def _runtime_root() -> Path:
    packaged = PACKAGE_DIR / "runtime"
    if (packaged / "scripts" / "sure.py").is_file():
        return packaged
    return ROOT / "skills" / "user-demand-research"


SKILL = _runtime_root()
CLI = SKILL / "scripts" / "sure.py"
MCP = SKILL / "scripts" / "sure_mcp.py"
VERSION_FILE = PACKAGE_DIR / "VERSION" if (PACKAGE_DIR / "VERSION").is_file() else ROOT / "VERSION"

USAGE = """usage: sure <command> [options]

one entry:
  "<需求>"           shorthand for `do`: route + scaffold in one line
  do "<需求>"        route product domain/stage/method and scaffold a study
  route "<需求>"     route only, no writes
  platforms "<需求>" rank platforms by data availability and access

research:
  instruments <study>  generate interview/observation/test kits
  collect <study>      run a supported collector or plan an export
  analyze <study>      normalize, dedup and describe collected material
  import <study> <file> import interviews/CSV/JSONL/text
  codebook <study>     scaffold claim-type codebook
  deliver <study>      memo / report / PRD input / post-launch tracker
  audit <study>        gates + signals + per-claim verdicts
  plan <study>         legacy platform/feasibility plan
  demo                 run the bundled offline sample
  doctor               check runtime, catalog, packs and version
  mcp                  start the MCP stdio server
  --version            print the SURE version
"""


def _require(path: Path) -> None:
    if not path.is_file():
        sys.exit(f"sure: runtime not found at {path}\nreinstall with: pipx install --editable .")


def _run(path: Path, argv: list[str]) -> None:
    sys.argv = [str(path), *argv]
    runpy.run_path(str(path), run_name="__main__")


def _doctor() -> int:
    file_version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "missing"
    checks = [
        ("python>=3.9", sys.version_info >= (3, 9), sys.version.split()[0]),
        ("VERSION", file_version == __version__, f"{__version__} (file: {file_version})"),
        ("sure.py", CLI.is_file(), str(CLI)),
        ("sure_mcp.py", MCP.is_file(), str(MCP)),
        ("sample-study", any(
            (path / "examples" / "sample-study" / "study.json").is_file()
            for path in (SKILL, ROOT)
        ), ""),
        ("connector-registry", (SKILL / "assets" / "open-source-connectors.json").is_file(), ""),
        ("method-catalog", (SKILL / "assets" / "method-catalog.json").is_file(), ""),
        ("domain-packs", len(list((SKILL / "assets" / "domain-packs").glob("*.json"))) == 5, ""),
        ("platform-catalog", (SKILL / "assets" / "platform-catalog.json").is_file(), ""),
    ]
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}".rstrip())
    return 0 if all(ok for _, ok, _ in checks) else 1


def main() -> int:
    argv = sys.argv[1:]

    if argv[:1] in (["--version"], ["-V"]):
        print(f"sure {__version__}")
        return 0

    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd == "doctor":
        return _doctor()

    if cmd == "mcp":
        _require(MCP)
        _run(MCP, rest)
        return 0

    _require(CLI)
    _run(CLI, [cmd, *rest])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

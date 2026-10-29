"""`sure` entry point.

Stage 1 packaging: expose the existing runtime and assets as one command.
Editable installs only; stage 2 moves the runtime into this package.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "user-demand-research"
CLI = SKILL / "scripts" / "sure.py"
MCP = SKILL / "scripts" / "sure_mcp.py"
VERSION_FILE = ROOT / "VERSION"

USAGE = """usage: sure <command> [options]

commands:
  audit <study>    gates + signals + per-claim verdicts (start here)
  plan <study>     create a study workspace from a goal
  report <study>   assemble the research-status report
  demo             run the bundled offline sample
  doctor           check the local runtime
  mcp              start the MCP stdio server
  --version        print the SURE version

see also: check / signals / lexicon / connectors / stage
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
        ("sample-study", (ROOT / "examples" / "sample-study" / "study.json").is_file(), ""),
        ("connector-registry", (SKILL / "assets" / "open-source-connectors.json").is_file(), ""),
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

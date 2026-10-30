"""`askovo-mcp` entry point."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
PACKAGED = PACKAGE_DIR / "runtime" / "scripts" / "askovo_mcp.py"
MCP = PACKAGED if PACKAGED.is_file() else ROOT / "skills" / "askovo" / "scripts" / "askovo_mcp.py"


def main() -> None:
    if not MCP.is_file():
        sys.exit(f"askovo-mcp: runtime not found at {MCP}")
    sys.argv = [str(MCP), *sys.argv[1:]]
    runpy.run_path(str(MCP), run_name="__main__")


if __name__ == "__main__":
    main()

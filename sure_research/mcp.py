"""`sure-mcp` entry point."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "skills" / "user-demand-research" / "scripts" / "sure_mcp.py"


def main() -> None:
    if not MCP.is_file():
        sys.exit(f"sure-mcp: runtime not found at {MCP}")
    sys.argv = [str(MCP)]
    runpy.run_path(str(MCP), run_name="__main__")

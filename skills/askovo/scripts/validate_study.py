#!/usr/bin/env python3
"""Backward-compatible full-study validator.

Prefer `askovo.py check STUDY_DIR --stage full --write-report` for new work.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 直接加载同目录的 CLI 真身，绕开 askovo 薄包：薄包 cli.main 经 runpy 回到
# 本目录脚本，构成 scripts -> 发布包 -> scripts 的跨树环（A-4，review
# 2026-11-09）。本文件与 askovo.py 同属 scripts 树，不应经发布包折返。
_CLI = Path(__file__).resolve().parent / "askovo.py"
_spec = importlib.util.spec_from_file_location("askovo_validate_target", _CLI)
_cli = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _cli  # askovo.py 执行期即查 sys.modules[自身名]
_spec.loader.exec_module(_cli)
main = _cli.main


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate_study.py STUDY_DIR", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(["check", sys.argv[1], "--stage", "full"]))

#!/usr/bin/env python3
"""Backward-compatible full-study validator.

Prefer `askovo.py check STUDY_DIR --stage full --write-report` for new work.
"""

from __future__ import annotations

import sys

from askovo import main


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate_study.py STUDY_DIR", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(["check", sys.argv[1], "--stage", "full"]))

#!/usr/bin/env python3
"""Build a month-balanced analysis view of an existing dataset.

Provenance (consolidation lineage):

- Base: ``projects/灵泷视界/用户研究/scripts/build_month_balanced_dataset.py`` — the
  most evolved of the three variants: on top of the per-month cap it adds a
  per-platform-month cap and a per-source-family-month cap, so a single busy
  platform cannot dominate any month even when the month itself stays under
  the month cap.
- From ``projects/Tiiny用户研究/scripts/build_month_balanced_dataset.py`` (identical
  to the AI眼镜 variant except default filenames): the per-month seeded
  downsample, the ``analysis_view`` stamping, and the "analysis view only,
  full dataset unchanged" summary note.
- Project-agnostic changes: explicit paths (no ``ROOT``), ``.jsonl.gz`` IO,
  caps configurable per CLI (0 disables a cap).

I/O contract: dataset JSONL(.gz) → ``data/processed/*_month_balanced.jsonl.gz`` +
summary JSON. Deterministic for a fixed --seed and input order.

Output is an ANALYSIS VIEW with reweighting, not a re-collection claim; month
counts here must not be read as trend magnitudes without the weights.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from common import ensure_parent, read_jsonl, write_jsonl


def cap_group(
    rows: List[Dict[str, Any]],
    key_field: str,
    cap: int,
    rng: random.Random,
) -> List[Dict[str, Any]]:
    """Cap each value of ``key_field`` at ``cap`` rows (seeded sample)."""
    if cap <= 0:
        return list(rows)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key_field) or "unknown")].append(row)
    out: List[Dict[str, Any]] = []
    for key in sorted(groups):
        candidates = groups[key]
        if len(candidates) > cap:
            candidates = rng.sample(candidates, cap)
        out.extend(candidates)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a month/platform/source-family balanced analysis view."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("data/processed/feedback_month_balanced.jsonl.gz")
    )
    parser.add_argument(
        "--summary", type=Path, default=Path("data/processed/month_balanced_summary.json")
    )
    parser.add_argument("--per-month-cap", type=int, default=5000)
    parser.add_argument("--per-platform-month-cap", type=int, default=1000)
    parser.add_argument(
        "--per-source-family-month-cap",
        type=int,
        default=1200,
        help="caps per source_family (falls back to source_platform) per month; 0 disables any cap",
    )
    parser.add_argument("--family-fallback-field", default="source_family")
    parser.add_argument("--seed", type=int, default=20260708)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    by_month: Dict[str, List[Dict[str, Any]]] = {}
    for row in read_jsonl(args.input):
        month = str(row.get("month_bucket") or "unknown")
        by_month.setdefault(month, []).append(row)

    out_rows: List[Dict[str, Any]] = []
    for month in sorted(by_month):
        rows = cap_group(by_month[month], "source_platform", args.per_platform_month_cap, rng)
        # family fallback: records without the family field group under their platform
        patched: List[Dict[str, Any]] = []
        for row in rows:
            if not row.get(args.family_fallback_field):
                row = dict(row)
                row[args.family_fallback_field] = row.get("source_platform") or "unknown"
            patched.append(row)
        rows = cap_group(patched, args.family_fallback_field, args.per_source_family_month_cap, rng)
        if args.per_month_cap > 0 and len(rows) > args.per_month_cap:
            rows = rng.sample(rows, args.per_month_cap)
        for row in rows:
            row = dict(row)
            row["analysis_view"] = "month_balanced"
            row["analysis_view_per_month_cap"] = args.per_month_cap
            row["analysis_view_per_platform_month_cap"] = args.per_platform_month_cap
            row["analysis_view_per_source_family_month_cap"] = args.per_source_family_month_cap
            out_rows.append(row)

    write_jsonl(args.out, out_rows, append=False)
    summary = {
        "record_count": len(out_rows),
        "source_input": str(args.input),
        "per_month_cap": args.per_month_cap,
        "per_platform_month_cap": args.per_platform_month_cap,
        "per_source_family_month_cap": args.per_source_family_month_cap,
        "seed": args.seed,
        "month_counts": dict(
            sorted(Counter(str(r.get("month_bucket") or "unknown") for r in out_rows).items())
        ),
        "source_counts": dict(
            Counter(str(r.get("source_platform") or "unknown") for r in out_rows)
        ),
        "source_family_counts": dict(
            Counter(
                str(
                    r.get(args.family_fallback_field)
                    or r.get("source_platform")
                    or "unknown"
                )
                for r in out_rows
            )
        ),
        "note": "Analysis view only. The full primary dataset remains unchanged.",
    }
    ensure_parent(args.summary)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(out_rows)} month-balanced records -> {args.out}")
    print(f"summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Rule-based labeling stage: raw/imported records → labeled JSONL + summary.

Provenance (consolidation lineage):

- Base: ``projects/灵泷视界/用户研究/scripts/label_feedback.py`` and
  ``projects/AI眼镜用户研究/scripts/label_feedback.py`` (the two are near-identical;
  both delegate labeling to ``common.annotate_research_dimensions`` and write
  per-dimension counters plus source/product cross-tabs into summary.json).
  The 灵泷 variant is taken as the wording base because its default input is
  an explicit path rather than "all raw records".
- From ``projects/Tiiny用户研究/scripts/label_feedback.py``: the first variant of
  the family — inline MOTIVATION/STRATEGY/SEGMENT rule tables with a plain
  ``label_text``. Its rule-table approach is preserved but the tables
  themselves now load from the taxonomy JSON config (灵泷's
  ``config/adjacent_user_lexicon.json`` was the in-family precedent for
  config-driven rules).
- Project-agnostic changes: paths are explicit CLI arguments (no ``ROOT``),
  summary dimensions are derived from the taxonomy instead of hardcoded
  (scenario/pain/feature/... or motivation/strategy/segment — whichever the
  study configures), and input/output support ``.jsonl.gz``.

I/O contract: ``data/raw/*.jsonl(.gz)`` (or an explicit --input) →
``data/processed/feedback_labeled.jsonl(.gz)`` + ``summary.json``.

Rule labels are candidate discovery signals for spot-checking (see
audit_workbook.py), never gold truth on their own.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from common import (
    Taxonomy,
    base_quality_flags,
    clean_text,
    ensure_parent,
    iter_raw_records,
    read_jsonl,
    write_jsonl,
)


def iter_input_records(input_path: Path | None, raw_dir: Path) -> Any:
    if input_path is None:
        yield from iter_raw_records(raw_dir)
        return
    yield from read_jsonl(input_path)


def build_summary(
    rows: List[Dict[str, Any]],
    dimensions: List[str],
    scalar_fields: List[str],
    input_desc: str,
    taxonomy: Taxonomy,
) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "record_count": len(rows),
        "input": input_desc,
        "taxonomy": taxonomy.summary(),
        "source_platforms": dict(
            Counter(str(row.get("source_platform") or "unknown") for row in rows)
        ),
    }
    for field in scalar_fields:
        summary[field] = dict(
            Counter(str(row.get(field) or "unknown") for row in rows).most_common(80)
        )
    for dimension in dimensions:
        summary[dimension] = dict(
            Counter(
                label
                for row in rows
                for label in (row.get(dimension) or ["unlabeled"])
            )
        )
        cross: Dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            source = str(row.get("source_platform") or "unknown")
            for label in row.get(dimension) or ["unlabeled"]:
                cross[source][label] += 1
        summary[f"by_source_and_{dimension}"] = {k: dict(v) for k, v in cross.items()}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Label raw feedback records with taxonomy rule dimensions."
    )
    parser.add_argument("--taxonomy", type=Path, required=True, help="taxonomy JSON config")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="explicit JSONL(.gz) input; defaults to every file under --raw-dir",
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/feedback_labeled.jsonl.gz"),
        help="labeled output (.jsonl or .jsonl.gz)",
    )
    parser.add_argument(
        "--summary", type=Path, default=Path("data/processed/label_summary.json")
    )
    parser.add_argument(
        "--scalar-fields",
        default="sample_bucket,product_hint,language_hint",
        help="comma-separated non-list fields to count in the summary",
    )
    args = parser.parse_args()

    taxonomy = Taxonomy.load(args.taxonomy)
    dimensions = sorted(taxonomy.label_rules.keys())
    scalar_fields = [f.strip() for f in args.scalar_fields.split(",") if f.strip()]

    rows: List[Dict[str, Any]] = []
    seen = set()
    for row in iter_input_records(args.input, args.raw_dir):
        rid = row.get("record_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        text = clean_text(row.get("text"))
        row["text"] = text
        flags = set(row.get("quality_flags") or [])
        flags.update(
            base_quality_flags(text, row.get("created_at"), taxonomy.primary_after_utc)
        )
        row["quality_flags"] = sorted(flags)
        taxonomy.annotate(row)
        rows.append(row)

    write_jsonl(args.out, rows, append=False)

    input_desc = str(args.input) if args.input else f"{args.raw_dir}/**/*.jsonl(.gz)"
    summary = build_summary(rows, dimensions, scalar_fields, input_desc, taxonomy)
    ensure_parent(args.summary)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"labeled {len(rows)} records -> {args.out}")
    print(f"summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

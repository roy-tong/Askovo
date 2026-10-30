#!/usr/bin/env python3
"""Export a labeled dataset to a metadata-detail CSV for spreadsheet review.

Provenance (consolidation lineage):

- Base: ``projects/灵泷视界/用户研究/scripts/export_metadata_detail.py`` — the
  widest field list of the three variants (adds evidence-level fields,
  user-segment / substitute label columns, and joins every list field with
  ``|``).
- ``projects/AI眼镜用户研究/scripts/export_metadata_detail.py`` contributed the
  product metadata + label columns; ``projects/Tiiny用户研究/scripts/...`` the
  original fixed column set.
- Project-agnostic changes: explicit paths (no ``ROOT``), the column list and
  joined list-fields are CLI/taxonomy-config driven instead of hardcoded
  (taxonomy keys: ``export_fields`` / ``export_list_fields``), ``.jsonl.gz``
  input, and a configurable excerpt length.

I/O contract: dataset JSONL(.gz) → CSV (default ``data/processed/metadata_detail.csv``).

The CSV is a review artifact: excerpts only by default, no full-text dump
unless the study deliberately passes a large --excerpt.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, List

from common import Taxonomy, ensure_parent, read_jsonl

DEFAULT_FIELDS = [
    "record_id",
    "source_platform",
    "source_channel",
    "source_role",
    "sample_bucket",
    "created_at",
    "month_bucket",
    "collected_at",
    "primary_sample_eligible",
    "quality_score",
    "topic_relevance_score",
    "sampling_weight",
    "score",
    "reply_count",
    "source_query",
    "product_hint",
    "corpus_role",
    "demand_evidence_level",
    "demand_evidence_basis",
    "language_hint",
    "thread_title",
    "thread_url",
    "source_url",
    "parent_id",
    "author_hash",
    "text_hash",
    "text_length",
    "text_excerpt",
    "quality_flags",
]
DEFAULT_LIST_FIELDS = [
    "market_region_labels",
    "user_segment_labels",
    "substitute_labels",
    "scenario_labels",
    "feature_need_labels",
    "pain_point_labels",
    "purchase_stage_labels",
    "motivation_labels",
    "response_strategy_labels",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export dataset metadata (+ label columns) to CSV."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("data/processed/metadata_detail.csv")
    )
    parser.add_argument(
        "--taxonomy", type=Path, default=None, help="optional; supplies export field lists"
    )
    parser.add_argument(
        "--fields", default=None, help="comma-separated column list (overrides defaults)"
    )
    parser.add_argument(
        "--list-fields",
        default=None,
        help="comma-separated list-valued fields joined with | (overrides defaults)",
    )
    parser.add_argument("--excerpt", type=int, default=320)
    args = parser.parse_args()

    taxonomy: Taxonomy = Taxonomy.load(args.taxonomy) if args.taxonomy else Taxonomy()
    fields: List[str] = (
        [f.strip() for f in args.fields.split(",") if f.strip()]
        if args.fields
        else (taxonomy.export_fields or DEFAULT_FIELDS)
    )
    list_fields: List[str] = (
        [f.strip() for f in args.list_fields.split(",") if f.strip()]
        if args.list_fields
        else (taxonomy.export_list_fields or DEFAULT_LIST_FIELDS)
    )
    for field in list_fields:
        if field not in fields:
            fields.append(field)

    ensure_parent(args.out)
    count = 0
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in read_jsonl(args.input):
            text = row.get("text") or ""
            out: Dict[str, Any] = {field: row.get(field) for field in fields}
            out["text_length"] = len(text)
            excerpt = row.get("text_excerpt") or text[: args.excerpt]
            out["text_excerpt"] = str(excerpt).replace("\n", " ")
            out["quality_flags"] = "|".join(row.get("quality_flags") or [])
            for field in list_fields:
                out[field] = "|".join(str(x) for x in (row.get(field) or []))
            writer.writerow(out)
            count += 1
    print(f"wrote {count} metadata rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

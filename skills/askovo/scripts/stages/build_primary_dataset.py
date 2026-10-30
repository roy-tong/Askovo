#!/usr/bin/env python3
"""Build the primary analysis dataset from raw records: normalize, dedup,
quality/relevance filter, annotate, and weight for month balance.

Provenance (consolidation lineage):

- Base: ``projects/AI眼镜用户研究/scripts/build_primary_dataset.py`` — the most
  complete variant of the two: relevance context includes thread titles,
  product hints participate in normalization, records can be excluded by
  ``corpus_role`` unless a gate field allows them, and kept records go
  through dimension annotation before writing.
- From ``projects/Tiiny用户研究/scripts/build_primary_dataset.py``: the original
  skeleton (dedup by record_id + text hash, quality/relevance floors, control
  buckets, month-inverse sampling weights, histogram summary). Its hardcoded
  control buckets (``mainstream_cloud_user`` / ``rejector_or_abandoned``) and
  source-role default became taxonomy config keys.
- Project-agnostic changes: explicit paths (no ``ROOT``), ``.jsonl.gz`` IO,
  the primary window comes from the taxonomy config, and every domain term
  (relevance vocabulary, control buckets, corpus-role exclusions, default
  source role) loads from the taxonomy JSON.

I/O contract: ``data/raw/*.jsonl(.gz)`` → ``data/processed/feedback_primary.jsonl.gz``
+ ``primary_summary.json``. Deterministic: no RNG, input order only.

Filters here define the ANALYSIS view, not evidence status; labeling stays
candidate-level until the audit workbook spot-check passes.
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
    ensure_parent,
    is_primary_date,
    iter_raw_records,
    month_bucket,
    quality_score,
    stable_text_hash,
    write_jsonl,
)


def normalize_for_primary(row: Dict[str, Any], taxonomy: Taxonomy) -> Dict[str, Any]:
    text = row.get("text") or ""
    created_at = row.get("created_at")
    after_utc = taxonomy.primary_after_utc
    flags = set(row.get("quality_flags") or [])
    flags.update(base_quality_flags(text, created_at, after_utc))
    score = row.get("score")
    q_score = quality_score(text, sorted(flags), score, taxonomy.quality_penalties)
    relevance_context = " ".join(
        str(part or "") for part in [row.get("source_channel"), row.get("thread_title")]
    )
    relevance = taxonomy.topic_relevance(text, row.get("source_query") or "", relevance_context)
    row["text_hash"] = row.get("text_hash") or stable_text_hash(text)
    row["month_bucket"] = row.get("month_bucket") or month_bucket(created_at)
    if not row.get("sample_bucket"):
        row["sample_bucket"] = taxonomy.infer_sample_bucket(
            text, row.get("source_query") or "", row.get("source_platform") or ""
        )
    if taxonomy.default_source_role and not row.get("source_role"):
        row["source_role"] = taxonomy.default_source_role
    row["quality_flags"] = sorted(flags)
    row["quality_score"] = q_score
    row["topic_relevance_score"] = round(relevance, 3)
    eligible = bool(
        row.get("primary_sample_eligible", is_primary_date(created_at, after_utc))
    ) and is_primary_date(created_at, after_utc)
    row["primary_sample_eligible"] = eligible
    return row


def keep_record(
    row: Dict[str, Any],
    min_quality: float,
    min_relevance: float,
    include_controls: bool,
    taxonomy: Taxonomy,
) -> bool:
    if not row.get("primary_sample_eligible"):
        return False
    if float(row.get("quality_score") or 0) < min_quality:
        return False
    if row.get("text_hash") is None:
        return False
    relevance = float(row.get("topic_relevance_score") or 0)
    if relevance >= min_relevance:
        return True
    return (
        include_controls
        and relevance >= taxonomy.control_min_relevance
        and row.get("sample_bucket") in taxonomy.control_buckets
    )


def corpus_role_excluded(row: Dict[str, Any], taxonomy: Taxonomy) -> bool:
    for role, unless_field in taxonomy.excluded_corpus_roles:
        if row.get("corpus_role") != role:
            continue
        if unless_field and row.get(unless_field):
            return False
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the primary analysis dataset from raw records."
    )
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--min-quality", type=float, default=0.55)
    parser.add_argument("--min-relevance", type=float, default=0.35)
    parser.add_argument(
        "--no-controls",
        action="store_true",
        help="drop the counter-evidence control-bucket rescue path",
    )
    parser.add_argument("--max-records", type=int, default=0, help="0 means no cap")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/feedback_primary.jsonl.gz"),
    )
    parser.add_argument(
        "--summary", type=Path, default=Path("data/processed/primary_summary.json")
    )
    args = parser.parse_args()

    taxonomy = Taxonomy.load(args.taxonomy)
    include_controls = not args.no_controls

    out_rows: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_text = set()
    dropped = Counter()
    source_counts = Counter()
    bucket_counts = Counter()
    month_counts = Counter()
    quality_hist = Counter()
    relevance_hist = Counter()
    source_bucket = defaultdict(Counter)

    for raw in iter_raw_records(args.raw_dir):
        if corpus_role_excluded(raw, taxonomy):
            dropped["excluded_corpus_role"] += 1
            continue
        row = normalize_for_primary(raw, taxonomy)
        rid = row.get("record_id")
        thash = row.get("text_hash")
        if not rid or rid in seen_ids:
            dropped["duplicate_record_id"] += 1
            continue
        if thash and thash in seen_text:
            dropped["duplicate_text"] += 1
            continue
        if not keep_record(row, args.min_quality, args.min_relevance, include_controls, taxonomy):
            dropped["filtered"] += 1
            continue
        taxonomy.annotate(row)
        seen_ids.add(rid)
        if thash:
            seen_text.add(thash)
        out_rows.append(row)
        source = str(row.get("source_platform") or "unknown")
        bucket = str(row.get("sample_bucket") or "unknown")
        source_counts[source] += 1
        bucket_counts[bucket] += 1
        month_counts[str(row.get("month_bucket") or "unknown")] += 1
        quality_hist[str(int(float(row.get("quality_score") or 0) * 10) / 10)] += 1
        relevance_hist[str(int(float(row.get("topic_relevance_score") or 0) * 10) / 10)] += 1
        source_bucket[source][bucket] += 1
        if args.max_records and len(out_rows) >= args.max_records:
            break

    if month_counts:
        target_per_month = len(out_rows) / len(month_counts)
        for row in out_rows:
            month = str(row.get("month_bucket") or "unknown")
            row["sampling_weight"] = round(target_per_month / month_counts[month], 6)
            row["sampling_weight_basis"] = "month_balanced_inverse_frequency"

    write_jsonl(args.out, out_rows, append=False)
    summary = {
        "record_count": len(out_rows),
        "taxonomy": taxonomy.summary(),
        "dropped": dict(dropped),
        "source_counts": dict(source_counts),
        "bucket_counts": dict(bucket_counts),
        "month_counts": dict(sorted(month_counts.items())),
        "quality_histogram": dict(sorted(quality_hist.items())),
        "topic_relevance_histogram": dict(sorted(relevance_hist.items())),
        "source_bucket_counts": {src: dict(counts) for src, counts in source_bucket.items()},
        "criteria": {
            "primary_after_utc": taxonomy.primary_after_utc,
            "min_quality": args.min_quality,
            "min_relevance": args.min_relevance,
            "include_controls": include_controls,
        },
        "note": "Primary analysis view; record counts are never user counts.",
    }
    ensure_parent(args.summary)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(out_rows)} primary records -> {args.out}")
    print(f"summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

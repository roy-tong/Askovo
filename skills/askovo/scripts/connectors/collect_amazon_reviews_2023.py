#!/usr/bin/env python3
"""Streaming collection from the Amazon Reviews 2023 historical dataset on HuggingFace.

Collected from the Tiiny user-research project (scripts/collect_amazon_reviews_2023.py).
Two passes over the McAuley-Lab dataset, both streamed (no full download):

1. metadata pass: scan `raw_meta_<category>` and build an ASIN allowlist from
   product keyword matches;
2. review pass: stream `raw_review_<category>`, keep reviews whose ASIN is in
   the allowlist and whose text matches the review keywords.

Project-agnostic changes (see connectors/README.md): dataset id, categories,
and both keyword lists moved from the project's config/queries.json to a
required `--config` JSON file; the output path is explicit; timestamps and
pseudonymisation reuse the shared common.py. The dataset itself is historical
(through 2023-09); this is not a live Amazon connector - the registry entry
`amazon-reviews-2023` documents the scope and limits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import common
from common import author_hash, clean_text, utc_from_timestamp, write_jsonl

DEFAULT_DATASET = "McAuley-Lab/Amazon-Reviews-2023"
DEFAULT_QUERY_LABEL = "amazon_reviews_2023_keywords"


def import_datasets():
    try:
        from datasets import load_dataset  # type: ignore
    except ModuleNotFoundError:
        print(
            "Missing dependency: datasets. Install with `python3 -m pip install datasets`.",
            file=sys.stderr,
        )
        raise
    return load_dataset


def text_matches(text: str, keywords: Iterable[str]) -> bool:
    t = text.lower()
    return any(keyword.lower() in t for keyword in keywords)


def stream_dataset(dataset_id: str, config_name: str):
    load_dataset = import_datasets()
    return load_dataset(dataset_id, config_name, split="full", streaming=True, trust_remote_code=True)


def get_value(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def find_product_asins(
    dataset_id: str,
    category: str,
    product_keywords: List[str],
    max_meta_records: int,
) -> Set[str]:
    config_name = f"raw_meta_{category}"
    asins: Set[str] = set()
    scanned = 0
    for row in stream_dataset(dataset_id, config_name):
        scanned += 1
        title = clean_text(str(get_value(row, ["title", "name"]) or ""))
        categories = clean_text(json.dumps(get_value(row, ["categories", "main_category"]) or "", ensure_ascii=False))
        details = clean_text(json.dumps(get_value(row, ["details", "features", "description"]) or "", ensure_ascii=False))
        haystack = " ".join([title, categories, details])
        if text_matches(haystack, product_keywords):
            asin = get_value(row, ["parent_asin", "asin"])
            if asin:
                asins.add(str(asin))
        if scanned >= max_meta_records:
            break
    print(f"{category}: scanned {scanned} metadata rows, matched {len(asins)} product ASINs")
    return asins


def normalize_review(row: Dict[str, Any], category: str, query: str, author_salt: Optional[str]) -> Optional[Dict[str, Any]]:
    review_id = get_value(row, ["review_id", "id"])
    asin = get_value(row, ["parent_asin", "asin"])
    user_id = get_value(row, ["user_id"])
    title = clean_text(str(get_value(row, ["title", "review_title"]) or ""))
    text = clean_text(str(get_value(row, ["text", "review_text", "content"]) or ""))
    body = clean_text(" ".join([title, text]))
    if len(body) < 20:
        return None
    stable_id = review_id or f"{category}:{asin}:{user_id}:{get_value(row, ['timestamp', 'time'])}:{hash(body)}"
    timestamp = get_value(row, ["timestamp", "time"])
    if isinstance(timestamp, str) and timestamp.isdigit():
        timestamp = int(timestamp)
    # Amazon Reviews 2023 timestamps are usually milliseconds.
    if isinstance(timestamp, (int, float)) and timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return {
        "record_id": f"amazon:{stable_id}",
        "source_platform": "amazon_reviews_2023",
        "source_channel": category,
        "source_url": None,
        "source_query": query,
        "created_at": utc_from_timestamp(timestamp),
        "author_hash": author_hash(str(user_id) if user_id else None, author_salt),
        "text": body,
        "score": get_value(row, ["rating", "stars"]),
        "parent_id": f"asin:{asin}" if asin else None,
        "product_hint": str(asin) if asin else None,
        "quality_flags": [],
    }


def collect(cfg: Dict[str, Any], max_records: int, max_meta_records: int, skip_metadata: bool, author_salt: Optional[str]) -> List[Dict[str, Any]]:
    dataset_id = cfg.get("dataset", DEFAULT_DATASET)
    query_label = str(cfg.get("query_label", DEFAULT_QUERY_LABEL))
    rows: List[Dict[str, Any]] = []
    seen = set()

    for category in cfg["categories"]:
        asin_allowlist: Optional[Set[str]] = None
        if not skip_metadata:
            asin_allowlist = find_product_asins(
                dataset_id,
                category,
                cfg["product_keywords"],
                max_meta_records,
            )
            if not asin_allowlist:
                continue
        config_name = f"raw_review_{category}"
        scanned = 0
        for row in stream_dataset(dataset_id, config_name):
            scanned += 1
            asin = str(get_value(row, ["parent_asin", "asin"]) or "")
            title = clean_text(str(get_value(row, ["title", "review_title"]) or ""))
            text = clean_text(str(get_value(row, ["text", "review_text", "content"]) or ""))
            combined = " ".join([title, text])
            if asin_allowlist is not None and asin not in asin_allowlist:
                continue
            if not text_matches(combined, cfg["review_keywords"]):
                continue
            row_out = normalize_review(row, category, query_label, author_salt)
            if not row_out or row_out["record_id"] in seen:
                continue
            seen.add(row_out["record_id"])
            rows.append(row_out)
            if len(rows) >= max_records:
                return rows
        print(f"{category}: scanned {scanned} review rows, kept {len(rows)} total")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream-filter Amazon Reviews 2023 from HuggingFace.")
    parser.add_argument("--config", type=Path, required=True, help='JSON: {"dataset": "...", "categories": [...], "product_keywords": [...], "review_keywords": [...], "query_label": "..."}}')
    parser.add_argument("--max-records", type=int, default=50000)
    parser.add_argument("--max-meta-records", type=int, default=250000)
    parser.add_argument("--skip-metadata", action="store_true", help="skip the ASIN allowlist pass and filter reviews by keywords only")
    parser.add_argument("--author-salt", default=None, help="study-stable salt for user_id pseudonymisation")
    parser.add_argument("--out", type=Path, default=Path("amazon_reviews_2023_filtered.jsonl"))
    args = parser.parse_args()

    cfg = common.load_json_config(args.config)
    missing = [key for key in ("categories", "product_keywords", "review_keywords") if not cfg.get(key)]
    if missing:
        raise SystemExit(f"config missing keys: {', '.join(missing)}")
    rows = collect(cfg, args.max_records, args.max_meta_records, args.skip_metadata, args.author_salt)
    count = write_jsonl(args.out, rows, append=False)
    print(f"wrote {count} Amazon Reviews 2023 records to {args.out}")


if __name__ == "__main__":
    main()

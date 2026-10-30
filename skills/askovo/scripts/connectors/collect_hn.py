#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import build_url, clean_text, infer_sample_bucket, is_primary_date, load_config, request_json, write_jsonl
from common import author_hash, base_quality_flags, month_bucket, quality_score, stable_text_hash, utc_now_iso


HN_SEARCH = "https://hn.algolia.com/api/v1/search"


def normalize_hit(hit: Dict[str, Any], query: str) -> Dict[str, Any] | None:
    text = clean_text(hit.get("comment_text") or hit.get("story_text") or hit.get("title"))
    if len(text) < 20:
        return None
    object_id = str(hit.get("objectID") or "")
    if not object_id:
        return None
    story_id = hit.get("story_id") or hit.get("parent_id")
    story_title = clean_text(hit.get("story_title") or hit.get("title"))
    created_at = hit.get("created_at")
    flags = base_quality_flags(text, created_at)
    score = hit.get("points")
    return {
        "record_id": f"hn:{object_id}",
        "source_platform": "hacker_news",
        "source_channel": story_title or "hn_comment",
        "source_url": f"https://news.ycombinator.com/item?id={object_id}",
        "source_query": query,
        "created_at": created_at,
        "collected_at": utc_now_iso(),
        "author_hash": author_hash(hit.get("author")),
        "text": text,
        "text_hash": stable_text_hash(text),
        "text_excerpt": text[:320],
        "score": score,
        "reply_count": None,
        "parent_id": f"hn_story:{story_id}" if story_id else None,
        "thread_title": story_title,
        "thread_url": f"https://news.ycombinator.com/item?id={story_id}" if story_id else None,
        "product_hint": story_title,
        "source_role": "motivation",
        "sample_bucket": infer_sample_bucket(text, query, "hacker_news"),
        "month_bucket": month_bucket(created_at),
        "primary_sample_eligible": is_primary_date(created_at),
        "quality_score": quality_score(text, flags, score),
        "sampling_weight": 1.0,
        "quality_flags": flags,
    }


def collect(max_records: int, hits_per_page: int, sleep_s: float, timeout: int) -> List[Dict[str, Any]]:
    cfg = load_config()["hacker_news"]
    queries = cfg["queries"]
    after_utc = cfg.get("after_utc")
    rows: List[Dict[str, Any]] = []
    seen = set()

    for query in queries:
        page = 0
        while len(rows) < max_records:
            url = build_url(
                HN_SEARCH,
                {
                    "query": query,
                    "tags": "comment",
                    "hitsPerPage": hits_per_page,
                    "page": page,
                    "numericFilters": f"created_at_i>={after_utc}" if after_utc else None,
                },
            )
            try:
                payload = request_json(url, timeout=timeout, retries=2)
            except Exception as exc:
                print(f"warning: HN query={query!r} page={page} failed: {exc}")
                break
            hits = payload.get("hits", [])
            if not hits:
                break
            for hit in hits:
                row = normalize_hit(hit, query)
                if not row or row["record_id"] in seen:
                    continue
                seen.add(row["record_id"])
                rows.append(row)
                if len(rows) >= max_records:
                    break
            page += 1
            if len(rows) and len(rows) % 1000 == 0:
                print(f"progress: {len(rows)} HN rows")
            if page >= int(payload.get("nbPages") or 0):
                break
            time.sleep(sleep_s)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-records", type=int, default=2000)
    parser.add_argument("--hits-per-page", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/raw/hn/hn_comments.jsonl"),
    )
    args = parser.parse_args()

    out_path = Path(__file__).resolve().parents[1] / args.out
    rows = collect(args.max_records, args.hits_per_page, args.sleep, args.timeout)
    count = write_jsonl(out_path, rows, append=False)
    print(f"wrote {count} Hacker News records to {out_path}")


if __name__ == "__main__":
    main()

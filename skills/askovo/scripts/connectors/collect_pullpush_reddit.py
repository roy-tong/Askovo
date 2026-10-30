#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List

from common import author_hash, base_quality_flags, build_url, clean_text, infer_sample_bucket, is_primary_date
from common import load_config, month_bucket, quality_score, request_json, stable_text_hash, utc_from_timestamp, utc_now_iso, write_jsonl


PULLPUSH_COMMENT_SEARCH = "https://api.pullpush.io/reddit/search/comment/"


def normalize_comment(item: Dict[str, Any], query: str) -> Dict[str, Any] | None:
    body = clean_text(item.get("body"))
    if len(body) < 20:
        return None
    if body.lower() in {"[deleted]", "[removed]"}:
        return None
    comment_id = item.get("id") or item.get("name")
    if not comment_id:
        return None
    permalink = item.get("permalink")
    source_url = "https://www.reddit.com" + permalink if permalink and permalink.startswith("/") else permalink
    subreddit = item.get("subreddit") or item.get("subreddit_name_prefixed")
    created_at = utc_from_timestamp(item.get("created_utc") or item.get("created"))
    score = item.get("score") or item.get("ups")
    flags = base_quality_flags(body, created_at)
    return {
        "record_id": f"reddit:{comment_id}",
        "source_platform": "reddit",
        "source_channel": f"r/{subreddit}" if subreddit and not str(subreddit).startswith("r/") else subreddit,
        "source_url": source_url,
        "source_query": query,
        "created_at": created_at,
        "collected_at": utc_now_iso(),
        "author_hash": author_hash(item.get("author")),
        "text": body,
        "text_hash": stable_text_hash(body),
        "text_excerpt": body[:320],
        "score": score,
        "reply_count": None,
        "parent_id": item.get("parent_id") or item.get("link_id"),
        "thread_title": None,
        "thread_url": None,
        "product_hint": None,
        "source_role": "motivation",
        "sample_bucket": infer_sample_bucket(body, query, "reddit"),
        "month_bucket": month_bucket(created_at),
        "primary_sample_eligible": is_primary_date(created_at),
        "quality_score": quality_score(body, flags, score),
        "sampling_weight": 1.0,
        "quality_flags": flags,
    }


def collect(max_records: int, size: int, sleep_s: float, timeout: int) -> List[Dict[str, Any]]:
    cfg = load_config()["reddit"]
    queries = cfg["queries"]
    subreddits = cfg["subreddits"]
    after_utc = cfg.get("after_utc")
    rows: List[Dict[str, Any]] = []
    seen = set()

    for subreddit in subreddits:
        for query in queries:
            before = None
            while len(rows) < max_records:
                url = build_url(
                    PULLPUSH_COMMENT_SEARCH,
                    {
                        "q": query,
                        "subreddit": subreddit,
                        "size": size,
                        "after": after_utc,
                        "before": before,
                    },
                )
                try:
                    payload = request_json(url, timeout=timeout, retries=1)
                except Exception as exc:
                    print(f"warning: {subreddit=} {query=!r} failed: {exc}")
                    break
                comments = payload.get("data", [])
                if not comments:
                    break
                next_before = None
                for item in comments:
                    row = normalize_comment(item, query)
                    created = item.get("created_utc") or item.get("created")
                    if created is not None:
                        created_i = int(float(created))
                        next_before = created_i if next_before is None else min(next_before, created_i)
                    if not row or row["record_id"] in seen:
                        continue
                    seen.add(row["record_id"])
                    rows.append(row)
                    if len(rows) >= max_records:
                        break
                if next_before is None or len(comments) < size:
                    break
                before = max(after_utc or 0, next_before - 1)
                if before == after_utc:
                    break
                print(f"progress: {len(rows)} rows after r/{subreddit} query={query!r} before={before}")
                time.sleep(sleep_s)
            if len(rows) >= max_records:
                break
        if len(rows) >= max_records:
            break
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-records", type=int, default=2000)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/raw/reddit/pullpush_comments.jsonl"),
    )
    args = parser.parse_args()

    out_path = Path(__file__).resolve().parents[1] / args.out
    rows = collect(args.max_records, args.size, args.sleep, args.timeout)
    count = write_jsonl(out_path, rows, append=False)
    print(f"wrote {count} Reddit records to {out_path}")


if __name__ == "__main__":
    main()

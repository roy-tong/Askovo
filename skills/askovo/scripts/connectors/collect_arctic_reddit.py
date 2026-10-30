#!/usr/bin/env python3
"""Cursor-paginated collection from the Arctic Shift public archive comments API.

Collected from the Tiiny user-research project (scripts/collect_arctic_reddit.py),
whose normalisation schema and quality scoring were the most mature of the
collected families. It complements collect_legacy_reddit.py: that one walks an
explicit route CSV by community-month sub-windows, while this one pages
backwards inside a time window with a `before` cursor until the subreddit is
exhausted or the record cap is hit.

Project-agnostic changes (see connectors/README.md): subreddits/window come
from `--config` JSON or `--subreddits` instead of the project's fixed
config/queries.json; User-Agent, author salt, and primary window are CLI
arguments; the project-specific sample-bucket lexicon was dropped from the
envelope.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import common
from common import (
    author_hash,
    base_quality_flags,
    build_url,
    clean_text,
    is_primary_date,
    month_bucket,
    quality_score,
    request_json,
    stable_text_hash,
    utc_from_timestamp,
    utc_now_iso,
    write_jsonl,
)

ARCTIC_COMMENTS_SEARCH = "https://arctic-shift.photon-reddit.com/api/comments/search"


def normalize_comment(item: Dict[str, Any], run_id: Optional[str], source_role: Optional[str]) -> Optional[Dict[str, Any]]:
    body = clean_text(item.get("body"))
    if not body or body.lower() in {"[deleted]", "[removed]"}:
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
    row: Dict[str, Any] = {
        "record_id": f"reddit:{comment_id}",
        "source_platform": "reddit",
        "source_family": "legacy_reddit_archive",
        "source_channel": f"r/{subreddit}" if subreddit and not str(subreddit).startswith("r/") else subreddit,
        "source_url": source_url,
        "source_query": "arctic_subreddit_time_slice",
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
        "month_bucket": month_bucket(created_at),
        "primary_sample_eligible": is_primary_date(created_at),
        "quality_score": quality_score(body, flags, score),
        "sampling_weight": 1.0,
        "quality_flags": flags,
        "source_tier": "legacy_nonofficial_public_archive",
    }
    if run_id:
        row["collection_run_id"] = run_id
    if source_role:
        row["source_role"] = source_role
    return row


def collect(subreddits: List[str], after_utc: Optional[int], max_records: int, size: int, sleep_s: float, timeout: int, run_id: Optional[str], source_role: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()

    for subreddit in subreddits:
        before = None
        while len(rows) < max_records:
            params = {
                "subreddit": subreddit,
                "after": after_utc,
                "before": before,
                "limit": size,
            }
            url = build_url(ARCTIC_COMMENTS_SEARCH, params)
            try:
                payload = request_json(url, timeout=timeout, retries=2)
            except Exception as exc:
                print(f"warning: Arctic subreddit={subreddit!r} before={before} failed: {exc}")
                break
            comments = payload.get("data") or []
            if not comments:
                break

            next_before = None
            for item in comments:
                created = item.get("created_utc") or item.get("created")
                if created is not None:
                    created_i = int(float(created))
                    next_before = created_i if next_before is None else min(next_before, created_i)
                row = normalize_comment(item, run_id, source_role)
                if not row or row["record_id"] in seen:
                    continue
                seen.add(row["record_id"])
                rows.append(row)
                if len(rows) >= max_records:
                    break

            print(f"progress: {len(rows)} Arctic Reddit rows after r/{subreddit} before={next_before}")
            if next_before is None or len(comments) < size:
                break
            before = max(after_utc or 0, next_before - 1)
            if before == after_utc:
                break
            time.sleep(sleep_s)
        if len(rows) >= max_records:
            break
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Cursor-paginated Arctic Shift comments collection.")
    parser.add_argument("--subreddits", default=None, help="comma-separated subreddit list; overrides the config file")
    parser.add_argument("--config", type=Path, default=None, help='JSON file: {"subreddits": [...], "after_utc": 1704067200}')
    parser.add_argument("--after-utc", type=int, default=None, help="lower bound as a unix timestamp in seconds")
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--author-salt", default=None, help="study-stable salt for author pseudonymisation")
    parser.add_argument("--primary-after-utc", type=int, default=None, help="primary-window lower bound; disables outside_primary_window flagging when omitted")
    parser.add_argument("--run-id", default=None, help="optional collection_run_id stamped into every record")
    parser.add_argument("--source-role", default=None, help="optional corpus-role field value")
    parser.add_argument("--out", type=Path, default=Path("arctic_comments.jsonl"))
    args = parser.parse_args()

    subreddits: Optional[List[str]] = None
    after_utc: Optional[int] = args.after_utc
    if args.config is not None:
        cfg = common.load_json_config(args.config)
        subreddits = [str(s) for s in cfg.get("subreddits", [])]
        after_utc = args.after_utc if args.after_utc is not None else cfg.get("after_utc")
    if args.subreddits:
        subreddits = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    if not subreddits:
        raise SystemExit("no subreddits: pass --subreddits or a --config file with a subreddits list")

    common.configure(user_agent=args.user_agent, author_salt=args.author_salt, primary_after_utc=args.primary_after_utc)
    rows = collect(subreddits, after_utc, args.max_records, args.size, args.sleep, args.timeout, args.run_id, args.source_role)
    count = write_jsonl(args.out, rows, append=False)
    print(f"wrote {count} Arctic Reddit records to {args.out}")


if __name__ == "__main__":
    main()

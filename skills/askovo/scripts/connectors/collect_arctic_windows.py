#!/usr/bin/env python3
"""Windowed backfill over the Arctic Shift public archive comments API.

Collected from the golf-device research project (04-脚本/deep_pull.py, 2026-11),
where the pattern ran ~3,900 windows across eleven subreddits. It complements
collect_arctic_reddit.py: that one pages backwards inside one time window to
exhaustion, while this one walks an explicit JSON plan of (subreddit x window)
slices — each window pages with an `after` cursor (oldest-1) so it can exceed
the 100-per-request cap, honours a per-window cap, and resumes from a state
file. Project-agnostic changes (see connectors/README.md): the golf-family
envelope (source_record_id) was realigned to the connector family envelope
(record_id + quality layer); the golf project's get()/base_record() were merged
into a standalone fetch/normalize with the field-verified backoff behaviour
(429/403 wait for X-RateLimit-Reset, 422 "slow down" retried with exponential
backoff); route/window provenance fields are kept.

Empty-window honesty: an archive window that returns zero rows is usually a
real gap (a community too small in that era), not a bug — verify one window
interactively before burning a long plan (see connectors/README.md).

Usage:
  python3 collect_arctic_windows.py --config windows.json \
      --out 02-data/raw/backfill.jsonl --state 02-data/raw/backfill.state.json \
      --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
      --author-salt my-stable-salt --run-id backfill-20261117-01
config: [{"sub": "golf",
          "windows": [{"after": "2021-11-01", "before": "2021-11-05", "cap": 100}],
          "max_per_window": 80}, ...]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import common
from common import (
    author_hash,
    base_quality_flags,
    clean_text,
    is_primary_date,
    month_bucket,
    quality_score,
    stable_text_hash,
    utc_from_timestamp,
    utc_now_iso,
)

ARCTIC_COMMENTS_SEARCH = "https://arctic-shift.photon-reddit.com/api/comments/search"
# `permalink` is not a selectable field: the archive answers HTTP 400
# ("'permalink' is not a valid field") for the whole page. The URL is rebuilt
# from link_id + comment id instead.
FIELDS = "id,body,author,created_utc,score,link_id,subreddit"


class ArchiveWindowError(RuntimeError):
    """A hard archive failure; the window must stay incomplete, never empty."""


def fetch_window_page(sub: str, after: int, before: int, cursor: Optional[int],
                      timeout: int, max_wait: float) -> List[Dict[str, Any]]:
    """One comments/search page with the archive's real-world error contract:
    429/403 wait for X-RateLimit-Reset (then exponential, capped, budget-bound);
    422 is the archive's 'timeout, slow down' and retries with backoff. A real
    empty page returns []; a hard failure raises ArchiveWindowError so the
    caller records an error instead of mistaking it for an empty window."""
    params: Dict[str, Any] = {
        "subreddit": sub, "after": cursor if cursor is not None else after,
        "before": before, "limit": 100, "fields": FIELDS,
    }
    url = ARCTIC_COMMENTS_SEARCH + "?" + urllib.parse.urlencode(params)
    wait = 5.0
    deadline = time.time() + max_wait
    while True:
        req = urllib.request.Request(url, headers={"User-Agent": common.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode("utf-8", "ignore"))
            return payload.get("data") or []
        except urllib.error.HTTPError as exc:
            if exc.code == 422:  # archive-side timeout; retry slower
                pass
            elif exc.code in (429, 403):
                reset = exc.headers.get("X-RateLimit-Reset")
                try:
                    pause = max(0.0, float(reset) - time.time()) if reset else wait
                except ValueError:
                    pause = wait
                pause = min(pause, 600.0)
                if time.time() + pause > deadline:
                    code = exc.code
                    exc.close()
                    raise ArchiveWindowError(f"HTTP {code}: rate-limited beyond the wait budget")
                time.sleep(pause)
                wait = min(wait * 2, 120.0)
                continue
            else:
                code = exc.code
                exc.close()
                raise ArchiveWindowError(f"HTTP {code} for subreddit={sub!r} window={after}-{before}")
        except ArchiveWindowError:
            raise
        except Exception as exc:  # noqa: BLE001 - classify transport failures honestly
            raise ArchiveWindowError(f"{type(exc).__name__}: {exc}") from exc
        if time.time() + wait > deadline:
            raise ArchiveWindowError("422 slow-down retries exhausted the wait budget")
        time.sleep(wait)
        wait = min(wait * 2, 120.0)


def comment_source_url(item: Dict[str, Any], sub: str) -> Optional[str]:
    """Stable Reddit URL without requesting the unsupported permalink field."""
    permalink = item.get("permalink")
    if isinstance(permalink, str) and permalink.startswith("/"):
        return "https://www.reddit.com" + permalink
    comment_id = item.get("id") or item.get("name")
    link_id = str(item.get("link_id") or "")
    link = link_id[3:] if link_id.startswith("t3_") else link_id
    subreddit = str(sub or item.get("subreddit") or "")
    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]
    if comment_id and link and subreddit:
        return f"https://www.reddit.com/r/{subreddit}/comments/{link}/_/{comment_id}/"
    return None


def normalize_comment(item: Dict[str, Any], sub: str, window_after: int,
                      run_id: Optional[str]) -> Optional[Dict[str, Any]]:
    body = clean_text(item.get("body"))
    if not body or body.lower() in {"[deleted]", "[removed]"}:
        return None
    comment_id = item.get("id") or item.get("name")
    if not comment_id:
        return None
    source_url = comment_source_url(item, sub)
    created_at = utc_from_timestamp(item.get("created_utc") or item.get("created"))
    score = item.get("score")
    flags = base_quality_flags(body, created_at)
    row: Dict[str, Any] = {
        "record_id": f"reddit:{comment_id}",
        "source_platform": "reddit",
        "source_family": "legacy_reddit_archive",
        "source_channel": f"r/{sub}" if not str(sub).startswith("r/") else sub,
        "source_url": source_url,
        "source_query": f"window:{sub}:{window_after}",
        "route_id": f"deep:{sub}",
        "created_at": created_at,
        "collected_at": utc_now_iso(),
        "author_hash": author_hash(item.get("author")),
        "text": body,
        "text_hash": stable_text_hash(body),
        "text_excerpt": body[:320],
        "score": score,
        "parent_id": item.get("link_id"),
        "thread_title": None,
        "thread_url": None,
        "month_bucket": month_bucket(created_at),
        "primary_sample_eligible": False,
        "quality_score": quality_score(body, flags, score),
        "sampling_weight": 1.0,
        "quality_flags": flags,
        "source_tier": "legacy_nonofficial_public_archive",
    }
    return common.with_connector_envelope(
        row, run_id or "arctic-windows-standalone", "reddit-arctic-shift-historical", "1")


def pull_window(sub: str, wafter: float, wbefore: float, cap: int,
                out, seen: set, stats: Dict[str, int],
                timeout: int, max_wait: float, sleep_s: float,
                run_id: Optional[str]) -> None:
    cursor: Optional[int] = None
    written = 0
    while written < cap:
        rows = fetch_window_page(sub, int(wafter), int(wbefore), cursor, timeout, max_wait)
        if rows is None:
            # Defensive: an adapter that reports failure as None must not be
            # mistaken for a genuinely empty archive page.
            raise ArchiveWindowError(
                f"no page returned for subreddit={sub!r} window={int(wafter)}-{int(wbefore)}")
        if not rows:
            break
        oldest: Optional[int] = None
        for item in rows:
            ts = item.get("created_utc") or item.get("created")
            if ts is None:
                continue
            ts_i = int(float(ts))
            oldest = ts_i if oldest is None else min(oldest, ts_i)
            record = normalize_comment(item, sub, int(wafter), run_id)
            if not record or record["record_id"] in seen or len(record["text"]) < 40:
                continue
            seen.add(record["record_id"])
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            stats["comments"] += 1
        # single-page mode for small caps; short pages and cursor exhaustion stop
        if cap <= 100 or len(rows) < 100 or oldest is None or oldest <= int(wafter):
            break
        cursor = oldest - 1
        time.sleep(sleep_s)
    stats["windows"] += 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Windowed Arctic Shift backfill with per-window caps and resumable state.")
    ap.add_argument("--config", required=True, help="JSON plan: [{sub, windows:[{after,before,cap}], max_per_window}]")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--author-salt", default=None)
    ap.add_argument("--primary-after-utc", type=int, default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--max-wait", type=float, default=300.0, help="per-page backoff budget in seconds")
    ap.add_argument("--max-hours", type=float, default=10.0)
    args = ap.parse_args()

    common.configure(user_agent=args.user_agent, author_salt=args.author_salt,
                     primary_after_utc=args.primary_after_utc)

    plan = json.loads(Path(args.config).read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() \
        else {"completed": [], "counts": {}, "errors": {}}
    completed = set(state["completed"])
    started_at = common.utc_now_iso()
    run_id = args.run_id or f"arctic-windows-{int(time.time())}"
    common.ensure_parent(args.out)
    common.ensure_parent(args.state)
    common.atomic_write_json(args.state, state)
    seen = set()
    if args.out.exists():
        for line in args.out.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["record_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    stats = {"comments": 0, "windows": 0}
    start = time.time()
    with args.out.open("a", encoding="utf-8") as out:
        for entry in plan:
            sub = entry["sub"]
            for win in entry["windows"]:
                key = f"{sub}:{win['after']}:{win['before']}"
                if key in completed:
                    continue
                if time.time() - start > args.max_hours * 3600:
                    print(f"TIME BUDGET hit at {key}", flush=True)
                    return
                wafter = datetime.fromisoformat(win["after"] + "T00:00:00+00:00").timestamp()
                wbefore = datetime.fromisoformat(win["before"] + "T00:00:00+00:00").timestamp()
                cap = int(win.get("cap") or entry.get("max_per_window", 4000))
                before_total = stats["comments"]
                try:
                    pull_window(sub, wafter, wbefore, cap, out, seen, stats,
                                args.timeout, args.max_wait, args.sleep, args.run_id)
                except ArchiveWindowError as exc:
                    # A hard archive failure is not an empty window: keep it out
                    # of `completed` so a rerun retries it, and surface the cause.
                    state["errors"][key] = str(exc)[:200]
                    common.atomic_write_json(args.state, state)
                    continue
                except Exception as exc:  # noqa: BLE001 - record and move on
                    state["errors"][key] = str(exc)[:200]
                    common.atomic_write_json(args.state, state)
                    continue
                completed.add(key)
                state["errors"].pop(key, None)
                state["counts"][key] = stats["comments"] - before_total
                state["completed"] = sorted(completed)
                common.atomic_write_json(args.state, state)
                print(f"{key}: cumulative new={stats['comments']}", flush=True)
                time.sleep(args.sleep)
    errors = list(state["errors"].values())
    stop_reason = "partial" if errors else "completed"
    common.write_collection_manifest(
        args.out, run_id=run_id, platform="reddit", connector_id="reddit-arctic-shift-historical",
        connector_revision="1", access_basis="historical_archive", query="windowed_backfill",
        started_at=started_at, completed_at=common.utc_now_iso(), reached_records=stats["comments"],
        written_records=stats["comments"], stop_reason=stop_reason, errors=errors)
    if errors:
        raise SystemExit(1)
    print(f"DONE new={stats['comments']} windows={stats['windows']}", flush=True)


if __name__ == "__main__":
    main()

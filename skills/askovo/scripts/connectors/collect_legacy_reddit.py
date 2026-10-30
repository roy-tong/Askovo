#!/usr/bin/env python3
"""Bounded, resumable, sub-window sliced collection from a legacy public archive.

Collected from two research projects and merged (see connectors/README.md for
the full provenance and the merged improvements):

- Base: the "deep" collector from the BCI demand-discovery study (sub-window
  slicing, shard support, rate-limit backoff, resumable state).
- Merged improvement 1 (sports-wellness corpus study): an HTTP 404 for a route
  blacklists the WHOLE route (`route_id:*`) instead of retrying every
  month-window of a nonexistent community.
- Merged improvement 2 (sports-wellness corpus study): `--start` actually
  filters the collected months. In the BCI generation the year range was
  hardcoded; here the month sequence is derived from `--start`/`--end`.

Discipline kept from both generations: one capped request per sub-window, no
login, no identity rotation, polite backoff on 429/403 that waits for
X-RateLimit-Reset, and a hard stop once the backoff budget is exhausted.
`--windows 1` reproduces the older one-request-per-community-month pilot
behaviour.

This tier is a non-official public archive, kept separate from official API
data: every envelope is stamped `source_tier=legacy_nonofficial_public_archive`
and `primary_sample_eligible=false`.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_ENDPOINT = "https://arctic-shift.photon-reddit.com/api/comments/search"
MIN_TEXT_LENGTH = 40


class _RouteNotFound(Exception):
    """The archive answered 404 for this route (community does not exist)."""


def month_bounds(start: str, end: str) -> list[tuple[datetime, datetime]]:
    """Whole calendar months intersecting [start, end), derived from the CLI
    window instead of a hardcoded year range (merged improvement 2)."""
    finish = datetime.fromisoformat(end + "T00:00:00+00:00")
    current = datetime.fromisoformat(start + "T00:00:00+00:00")
    # Snap to the first day of the month so windows align with calendar months.
    current = current.replace(day=1)
    months: list[tuple[datetime, datetime]] = []
    while current < finish:
        year, month = current.year, current.month
        if month == 12:
            nxt = current.replace(year=year + 1, month=1)
        else:
            nxt = current.replace(month=month + 1)
        months.append((current, min(nxt, finish)))
        current = nxt
    return months


def month_windows(year: int, month: int, windows: int) -> list[tuple[datetime, datetime]]:
    """Split one calendar month into `windows` roughly equal sub-windows."""
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    total = (end - start).days
    size = max(1, total // windows)
    bounds = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=size), end)
        bounds.append((cursor, nxt))
        cursor = nxt
    return bounds


def clean(text: object) -> str:
    return " ".join(str(text or "").split())


def fetch_with_backoff(
    route: dict,
    after: datetime,
    before: datetime,
    *,
    endpoint: str,
    user_agent: str,
    max_wait: float = 600.0,
) -> list[dict]:
    """Fetch one sub-window, retrying HTTP 429/403 politely.

    The public archive endpoint rate-limits by IP; a burst of parallel shards
    triggers 429. Instead of dying (which wasted whole shards in earlier runs),
    wait for the reset header (or exponential backoff) and retry. This never
    bypasses the limit - it only waits. A 404 raises _RouteNotFound so the
    caller can blacklist the whole route (merged improvement 1).
    """
    wait = 5.0
    deadline = time.time() + max_wait
    params = {
        "subreddit": route["subreddit"],
        "after": int(after.timestamp()),
        "before": int(before.timestamp()),
        "limit": min(int(route.get("per_month_cap") or 100), 100),
    }
    url = endpoint + "?" + urllib.parse.urlencode(params)
    while True:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("data") or []
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise _RouteNotFound(route["route_id"])
            if exc.code not in {429, 403}:
                raise
            reset = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
            try:
                delay = float(reset) if reset else wait
            except (TypeError, ValueError):
                delay = wait
            delay = min(max(delay, 2.0), 120.0)
            if time.time() + delay > deadline:
                print(f"rate-limit backoff exceeded max wait ({max_wait}s); giving up", flush=True)
                raise
            print(f"HTTP {exc.code} on {route['route_id']}; backing off {delay:.0f}s", flush=True)
            time.sleep(delay)
            wait *= 2.0


def normalize(item: dict, route: dict, collected_at: str, run_id: str, salt: str | None, connector_id: str | None) -> dict | None:
    text = clean(item.get("body"))
    comment_id = item.get("id") or item.get("name")
    if not comment_id or len(text) < MIN_TEXT_LENGTH or text.lower() in {"[deleted]", "[removed]"}:
        return None
    created = item.get("created_utc") or item.get("created")
    try:
        created_at = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        created_at = None
    author_hash = None
    if salt:
        author = str(item.get("author") or "").strip().lower()
        if author and author not in {"[deleted]", "deleted"}:
            author_hash = hashlib.sha256((salt + author).encode()).hexdigest()[:24]
    permalink = item.get("permalink")
    source_url = "https://www.reddit.com" + permalink if isinstance(permalink, str) and permalink.startswith("/") else permalink
    row = {
        "collection_run_id": run_id,
        "source_platform": "reddit",
        "source_family": "legacy_reddit_archive",
        "source_record_id": f"reddit:{comment_id}",
        "source_channel": f"r/{route['subreddit']}",
        "thread_id": item.get("link_id"),
        "parent_id": item.get("parent_id"),
        "source_url": source_url,
        "route_id": route["route_id"],
        "source_query": f"community_subwindow:{route['route_id']}",
        "sampling_frame": "legacy_public_archive_community_month_subwindow",
        "created_at": created_at,
        "collected_at": collected_at,
        "author_hash": author_hash,
        "score": item.get("score") or item.get("ups"),
        "text": text,
        "normalized_text_hash": hashlib.sha256(text.lower().encode()).hexdigest(),
        "source_tier": "legacy_nonofficial_public_archive",
        "primary_sample_eligible": False,
        "screening_note": "Uncoded legacy archive observation; does not enter demand evidence without contextual review.",
    }
    if connector_id:
        row["connector_id"] = connector_id
    # Optional per-study seeds; kept only when the route file provides them.
    if route.get("scene_cluster"):
        row["scene_seed"] = route["scene_cluster"]
    if route.get("corpus_role"):
        row["candidate_corpus_role"] = route["corpus_role"]
    return row


def load_seen(path: Path) -> set:
    seen = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line).get("source_record_id"))
            except json.JSONDecodeError:
                continue
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--routes", type=Path, required=True, help="CSV: route_id, subreddit, per_month_cap required; scene_cluster, corpus_role optional")
    parser.add_argument("--out", type=Path, required=True, help="append-mode JSONL output")
    parser.add_argument("--state", type=Path, required=True, help="resumable state JSON")
    parser.add_argument("--start", required=True, help="ISO date YYYY-MM-DD; months before it are skipped (merged improvement 2)")
    parser.add_argument("--end", required=True, help="ISO date YYYY-MM-DD")
    parser.add_argument("--user-agent", required=True, help="identifiable User-Agent per platform rules; never hardcoded per project")
    parser.add_argument("--run-id", default=None, help="collection_run_id stamped on every envelope; defaults to a UTC-timestamped id")
    parser.add_argument("--salt", default=None, help="study-stable salt for author pseudonymisation; when omitted author_hash is null")
    parser.add_argument("--connector-id", default=None, help="optional connector id stamped into envelopes for manifest cross-reference")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--target-records", type=int, default=600000)
    parser.add_argument("--full", action="store_true", help="ignore target-records cap; collect ALL route-month windows")
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--windows", type=int, default=4, help="sub-windows per month; 1 reproduces the one-request-per-month pilot")
    parser.add_argument("--shard-idx", type=int, default=0, help="0-based shard index")
    parser.add_argument("--shard-total", type=int, default=1, help="total number of parallel shards")
    args = parser.parse_args()
    run_id = args.run_id or f"legacy-reddit-archive-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    routes = list(csv.DictReader(args.routes.open(encoding="utf-8-sig", newline="")))
    if args.shard_total > 1:
        routes = routes[args.shard_idx::args.shard_total]
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {"completed": [], "blocked": [], "counts": {}}
    completed = set(state.get("completed", []))
    blocked = set(state.get("blocked", []))
    seen = load_seen(args.out)
    written = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as output:
        for month_start, month_end in month_bounds(args.start, args.end):
            year, month = month_start.year, month_start.month
            for route in routes:
                if not args.full and written >= args.target_records:
                    break
                for wi, (wafter, wbefore) in enumerate(month_windows(year, month, args.windows)):
                    key = f"{route['route_id']}:{year}-{month:02d}:w{wi}"
                    if key in completed or key in blocked or f"{route['route_id']}:*" in blocked:
                        continue
                    if not args.full and written >= args.target_records:
                        break
                    try:
                        records = fetch_with_backoff(route, wafter, wbefore, endpoint=args.endpoint, user_agent=args.user_agent)
                    except _RouteNotFound:
                        # Merged improvement 1: a missing community would 404 on
                        # every month-window; blacklist the whole route now and
                        # persist immediately so resumed runs skip it too.
                        blocked.add(f"{route['route_id']}:*")
                        state["blocked"] = sorted(blocked)
                        args.state.parent.mkdir(parents=True, exist_ok=True)
                        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"route={route['route_id']} 404; blacklisted whole route", flush=True)
                        break
                    except urllib.error.HTTPError as exc:
                        blocked.add(key)
                        state["blocked"] = sorted(blocked)
                        state.setdefault("errors", {})[key] = f"HTTP {exc.code}"
                        if exc.code in {403, 429}:
                            args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                            raise SystemExit(f"stopped on HTTP {exc.code}; no retry or bypass attempted")
                        continue
                    except Exception as exc:  # network hiccup: skip window, keep going
                        state.setdefault("errors", {})[key] = type(exc).__name__
                        time.sleep(args.sleep)
                        continue
                    collected_at = datetime.now(timezone.utc).isoformat()
                    added = 0
                    for item in records:
                        row = normalize(item, route, collected_at, run_id, args.salt, args.connector_id)
                        if row is None or row["source_record_id"] in seen:
                            continue
                        seen.add(row["source_record_id"])
                        output.write(json.dumps(row, ensure_ascii=False) + "\n")
                        written += 1
                        added += 1
                        if not args.full and written >= args.target_records:
                            break
                    completed.add(key)
                    state["completed"] = sorted(completed)
                    state["counts"][key] = added
                    if len(completed) % 40 == 0:
                        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"route={route['route_id']} month={year}-{month:02d} w{wi} added={added} total={written}", flush=True)
                    time.sleep(args.sleep)
                if not args.full and written >= args.target_records:
                    break
            if not args.full and written >= args.target_records:
                break
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"completed deep collection: {written} new records (run_id={run_id})", flush=True)


if __name__ == "__main__":
    main()

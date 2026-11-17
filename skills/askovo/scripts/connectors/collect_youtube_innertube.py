#!/usr/bin/env python3
"""YouTube competitor/KOL video comment collector over the public innertube API.

Collected from the golf-device research project (04-脚本/expand-2026-11/youtube_pull.py,
2026-11), where the channel was field-verified after yt-dlp default clients started
tripping PO-token detection ("page needs to be reloaded"). Project-agnostic changes:
the hardcoded author salt and user agent became --author-salt/--user-agent via
common.configure(); the golf-family envelope (source_record_id) was realigned to the
connector family envelope (record_id + quality layer, see connectors/README.md);
created_at approximated from relative text is now marked date_precision="approximate".

Flow per search query (no login, no browser):
  1) /youtubei/v1/search -> videoIds (top N)
  2) /youtubei/v1/next(videoId) -> title/channel + first comment continuation
  3) /youtubei/v1/next(continuation) -> comment pages until cap or exhaustion

Comment parsing covers both the legacy commentRenderer and the 2024+
commentEntityPayload shape (keyed by commentKey in frameworkUpdates).
Resumable: per-(query,video) marks in a state file.

Usage:
  python3 collect_youtube_innertube.py --queries queries.json \
      --out 02-data/raw/yt-comments.jsonl --state 02-data/raw/yt-comments.state.json \
      --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
      --author-salt my-stable-salt --run-id yt-run-20261117-01
queries.json: [{"q": "xbotgo golf", "route": "yt-comp-xbotgo", "n_videos": 8,
                "cap_comments": 400}, ...]
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import common

CTX = {"context": {"client": {"clientName": "WEB", "clientVersion": "2.20240726.00.00", "hl": "en", "gl": "US"}}}
SOURCE_TIER = "public_page_uncoded"


def post(endpoint: str, body: dict, max_wait: float = 240.0) -> Optional[dict]:
    """POST JSON to an innertube endpoint with polite 429/403 backoff."""
    url = f"https://www.youtube.com/youtubei/v1/{endpoint}?prettyPrint=false"
    wait = 5.0
    deadline = time.time() + max_wait
    while True:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "User-Agent": common.USER_AGENT,
                     "Origin": "https://www.youtube.com"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 403}:
                return None
            if time.time() + wait > deadline:
                return None
            print(f"HTTP {exc.code}; back off {wait:.0f}s", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 120.0)
        except Exception:
            return None


def walk(o: Any, pred, out: list) -> None:
    if isinstance(o, dict):
        if pred(o):
            out.append(o)
        for v in o.values():
            walk(v, pred, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, pred, out)


def search_videos(query: str, n: int) -> List[str]:
    body = dict(CTX)
    body["query"] = query
    vids: List[str] = []
    cont = None
    for _ in range(4):
        if cont:
            body = dict(CTX)
            body["continuation"] = cont
        d = post("search", body)
        if not d:
            break
        renderers: List[dict] = []
        walk(d.get("contents", {}), lambda o: "videoRenderer" in o, renderers)
        for r in renderers:
            vid = r["videoRenderer"].get("videoId")
            if vid and vid not in vids:
                vids.append(vid)
            if len(vids) >= n:
                return vids
        conts: List[dict] = []
        walk(d.get("contents", {}), lambda o: "continuationItemRenderer" in o, conts)
        cont = None
        for c in conts:
            cmd = c["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {})
            if cmd.get("token"):
                cont = cmd["token"]
        if not cont:
            break
    return vids


REL = re.compile(r"(\d+) (second|minute|hour|day|week|month|year)s? ago")


def approx_time(text: object, now: float) -> Optional[str]:
    """'10 months ago' -> approximate ISO date (precision is day-level at best)."""
    m = REL.search(str(text or ""))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24,
            "day": 1, "week": 7, "month": 30.4, "year": 365}[unit]
    ts = datetime.fromtimestamp(now - n * days * 86400, tz=timezone.utc)
    return ts.date().isoformat()


def video_meta(d: dict) -> dict:
    meta: Dict[str, Any] = {}
    walk(d.get("microformat", {}), lambda o: "playerMicroformatRenderer" in o, out := [])
    if out:
        r = out[0]["playerMicroformatRenderer"]
        meta["title"] = r.get("title", "")
        meta["channel"] = r.get("ownerChannelName", "")
        meta["published"] = (r.get("publishDate") or "")[:10]
        meta["views"] = r.get("viewCount")
    counts: List[dict] = []
    walk(d.get("contents", {}), lambda o: "videoPrimaryInfoRenderer" in o, counts)
    if counts and not meta.get("title"):
        meta["title"] = counts[0]["videoPrimaryInfoRenderer"].get("title", {}).get("runs", [{}])[0].get("text", "")
    secs: List[dict] = []
    walk(d.get("contents", {}), lambda o: "videoSecondaryInfoRenderer" in o, secs)
    if secs:
        owner = secs[0]["videoSecondaryInfoRenderer"].get("owner", {}).get("videoOwnerRenderer", {})
        meta["channel"] = owner.get("title", {}).get("runs", [{}])[0].get("text", "") or meta.get("channel", "")
    return meta


def comment_token(d: dict) -> Optional[str]:
    """Comment-section continuation: itemSectionRenderer whose first content is a continuationItemRenderer."""
    sections: List[dict] = []
    walk(d.get("contents", {}), lambda o: "itemSectionRenderer" in o, sections)
    for s in sections:
        for c in s["itemSectionRenderer"].get("contents", []):
            if "continuationItemRenderer" in c:
                tok = c["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
                if tok:
                    return tok
    return None


def parse_comments(d: dict) -> List[dict]:
    """Handles both legacy commentRenderer and 2024+ commentEntityPayload shapes."""
    ents = {}
    for m in d.get("frameworkUpdates", {}).get("entityBatchUpdate", {}).get("mutations", []):
        p = m.get("payload", {})
        if "commentEntityPayload" in p:
            ce = p["commentEntityPayload"]
            ents[ce.get("key")] = ce
    out: List[dict] = []
    threads: List[dict] = []
    for ep in d.get("onResponseReceivedEndpoints", []):
        walk(ep, lambda o: "commentThreadRenderer" in o or "commentRenderer" in o, threads)
    for t in threads:
        if "commentRenderer" in t:  # legacy flat
            cr = t["commentRenderer"]
            out.append({
                "id": cr.get("commentId"),
                "author": cr.get("authorText", {}).get("simpleText"),
                "text": "".join(r.get("text", "") for r in cr.get("contentText", {}).get("runs", [])),
                "time_text": cr.get("publishedTimeText", {}).get("simpleText"),
                "likes": cr.get("voteCount", {}).get("simpleText"),
            })
        else:  # 2024+ shape: commentThreadRenderer.commentViewModel.commentViewModel
            vm = (t["commentThreadRenderer"].get("commentViewModel", {}) or {}).get("commentViewModel", {}) or {}
            ce = ents.get(vm.get("commentKey")) or {}
            props = ce.get("properties", {})
            toolbar = ce.get("toolbar", {})
            author = ce.get("author", {})
            out.append({
                "id": vm.get("commentId") or props.get("commentId"),
                "author": author.get("displayName"),
                "text": (props.get("content", {}) or {}).get("content"),
                "time_text": props.get("publishedTime"),
                "likes": toolbar.get("likeCountLiked") or toolbar.get("likeCountNotliked"),
            })
    return [c for c in out if c.get("id") and c.get("text")]


def next_page_token(d: dict) -> Optional[str]:
    toks: List[dict] = []
    for ep in d.get("onResponseReceivedEndpoints", []):
        walk(ep, lambda o: "continuationItemRenderer" in o, toks)
        for t in toks:
            tok = t["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if tok:
                return tok
    return None


def build_record(c: dict, meta: dict, vid: str, q: dict, run_id: Optional[str]) -> dict:
    text = " ".join(str(c["text"]).split())[:1500]
    created_at = approx_time(c.get("time_text"), time.time())
    flags = common.base_quality_flags(text, created_at)
    record = {
        "record_id": f"youtube:{c['id']}",
        "source_platform": "youtube",
        "source_family": "video_comments",
        "source_channel": meta.get("channel", ""),
        "source_url": f"https://youtu.be/{vid}",
        "source_query": q["q"],
        "route_id": q["route"],
        "thread_id": vid,
        "thread_title": meta.get("title", ""),
        "text": text,
        "text_hash": common.stable_text_hash(text),
        "text_excerpt": text[:320],
        "score": c.get("likes"),
        "author_hash": common.author_hash(c.get("author")),
        "created_at": created_at,
        "date_precision": "approximate",  # derived from relative publishedTime text
        "month_bucket": common.month_bucket(created_at),
        "collected_at": common.utc_now_iso(),
        "quality_flags": flags,
        "quality_score": common.quality_score(text, flags),
        "sampling_weight": 1.0,
        "primary_sample_eligible": created_at is not None and common.is_primary_date(created_at),
        "source_tier": SOURCE_TIER,
    }
    if run_id:
        record["collection_run_id"] = run_id
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queries", required=True, help="JSON list of {q, route, n_videos, cap_comments}")
    ap.add_argument("--out", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--user-agent", required=True, help="study identity, e.g. MyStudyResearch/1.0 (+contact)")
    ap.add_argument("--author-salt", help="stable study salt for cross-run author linkage")
    ap.add_argument("--primary-after-utc", type=int, help="primary window start (unix seconds)")
    ap.add_argument("--run-id", help="written to collection_run_id on every record")
    ap.add_argument("--max-records", type=int, help="global cap across all queries (bounded collection)")
    ap.add_argument("--sleep", type=float, default=1.2)
    args = ap.parse_args()

    common.configure(user_agent=args.user_agent, author_salt=args.author_salt,
                     primary_after_utc=args.primary_after_utc)

    plan = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() \
        else {"done_videos": {}, "queries_run": []}
    seen = set()
    out_path = Path(args.out)
    if out_path.exists():
        for row in common.read_jsonl(out_path):
            if row.get("record_id"):
                seen.add(row["record_id"])
    total = 0
    with out_path.open("a", encoding="utf-8") as fo:
        for q in plan:
            if args.max_records and total >= args.max_records:
                print(f"MAX_RECORDS hit ({total})", flush=True)
                break
            if q["q"] in state["queries_run"]:
                continue
            vids = search_videos(q["q"], int(q.get("n_videos", 8)))
            print(f"[{q['route']}] '{q['q']}' -> {len(vids)} videos", flush=True)
            for vid in vids:
                if vid in state["done_videos"]:
                    continue
                body = dict(CTX)
                body["videoId"] = vid
                d = post("next", body)
                time.sleep(args.sleep)
                if not d:
                    continue
                meta = video_meta(d)
                tok = comment_token(d)
                n_comments = 0
                pages = 0
                while tok and n_comments < int(q.get("cap_comments", 400)) and pages < 40:
                    body = dict(CTX)
                    body["continuation"] = tok
                    cd = post("next", body)
                    time.sleep(args.sleep)
                    pages += 1
                    if not cd:
                        break
                    for c in parse_comments(cd):
                        rid = f"youtube:{c['id']}"
                        if rid in seen or len(str(c.get("text"))) < 15:
                            continue
                        seen.add(rid)
                        record = build_record(c, meta, vid, q, args.run_id)
                        fo.write(json.dumps(record, ensure_ascii=False) + "\n")
                        n_comments += 1
                        total += 1
                    tok = next_page_token(cd)
                state["done_videos"][vid] = {"title": meta.get("title", ""), "comments": n_comments}
                state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                print(f"  {vid} {meta.get('title', '')[:48]} -> +{n_comments}", flush=True)
            state["queries_run"].append(q["q"])
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"DONE total_new={total}", flush=True)


if __name__ == "__main__":
    main()

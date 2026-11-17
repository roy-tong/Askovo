#!/usr/bin/env python3
"""Kickstarter campaign comment/update collector over CDP visible pages.

Method collected from the golf-device research project (2026-11), where it
harvested ~2k crowdfunding comments across four campaigns. Direct fetches of
comment pages sit behind Cloudflare (403) and the comment section is
JS-rendered, so this collector drives a real browser over the Chrome DevTools
Protocol: it opens the page, waits for a passive Cloudflare auto-clear (never
bypasses a challenge — a challenge that needs human interaction is a hard
stop), clicks "load more" until the comment list stops growing, and extracts
comment cards from the DOM.

Field-verified details baked in:
- comment cards are `DIV.border-box` inside `LI.mb2` cards; replies are
  distinguished by `&reply=` in the comment permalink;
- "load more" must be clicked repeatedly (a page shows ~50 first, hundreds
  after expansion); expand in bounded bursts, persist after every burst;
- creator update posts carry their own comment threads (delivery-period
  sentiment concentrates there);
- output is a raw-JSON snapshot (platform-faithful), not the corpus envelope:
  convert with clean_screen_corpus.py (see connectors/README.md).

The CDP client implementation is reused from the engine (../sure_engine.py):
loopback-only debugger, no-redirect page creation, frame limits. Collecting a
tool is not the same as approving a route (README §6): the platform catalog
entry governs whether a study may use this channel.

Usage:
  python3 collect_cdp_kickstarter.py --cdp-url http://127.0.0.1:9222 \
      --url "https://www.kickstarter.com/projects/xbotgo/xbotgo-falcon-the-first-team-sports-camera/comments" \
      --out 02-data/raw/ks-falcon.json
  python3 collect_cdp_kickstarter.py ... --mode posts --project-slug xbotgo-falcon
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sure_engine_cdp_ks", HERE.parent / "sure_engine.py")
sure_engine = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sure_engine)

CHALLENGE_TEXT = "just a moment|checking your browser|verify you are human|attention required"

EXTRACT_COMMENTS = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const body = clean(document.body ? document.body.innerText : "");
  if (/%s/.test(body)) return {error: "challenge_page"};
  const out = [];
  for (const li of document.querySelectorAll("li")) {
    const card = li.querySelector("div.border-box");
    if (!card) continue;
    const links = Array.from(card.querySelectorAll('a[href*="comment="]'));
    const href = links.length ? links[0].getAttribute("href") || "" : "";
    const time = card.querySelector("time");
    out.push({
      author: clean((card.querySelector('a[data-testid], .hover-target') || {}).textContent),
      href: href,
      is_reply: href.includes("&reply="),
      text: clean(card.innerText).slice(0, 2000),
      time: time ? clean(time.textContent) : "",
    });
  }
  const more = Array.from(document.querySelectorAll("button"))
    .find(b => /load more/i.test(clean(b.textContent)));
  return {comments: out, more: !!more, page_title: document.title};
})()
""" % CHALLENGE_TEXT

LOAD_MORE_CLICK = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const more = Array.from(document.querySelectorAll("button"))
    .find(b => /load more/i.test(clean(b.textContent)));
  if (more) { more.click(); return true; }
  return false;
})()
"""

EXTRACT_POSTS = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const body = clean(document.body ? document.body.innerText : "");
  if (/%s/.test(body)) return {error: "challenge_page"};
  const posts = [];
  for (const a of document.querySelectorAll('a[href*="/posts/"]')) {
    const href = a.getAttribute("href") || "";
    const m = href.match(/\\/posts\\/(\\d+)/);
    if (!m) continue;
    posts.push({post_id: m[1], url: new URL(href, location.href).href,
                title: clean(a.textContent).slice(0, 300)});
  }
  return {posts: posts, page_title: document.title};
})()
""" % CHALLENGE_TEXT


def wait_for_page(client, challenge_wait: float, poll: float = 2.0) -> None:
    """Wait for render and passive Cloudflare auto-clear; hard stop otherwise."""
    deadline = time.time() + challenge_wait
    while time.time() < deadline:
        value = client.evaluate(
            '(() => {const t = String(document.body ? document.body.innerText : "");'
            'return /%s/.test(t) ? "challenge" : document.readyState;})()' % CHALLENGE_TEXT)
        if value == "complete":
            time.sleep(1.0)
            return
        time.sleep(poll)
    raise RuntimeError(
        "challenge_page: Cloudflare check did not clear passively within "
        f"{challenge_wait:.0f}s; the collector never bypasses challenges — "
        "finish the check by hand in the browser, then rerun")


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    # lesson from the field: persist after every burst, never batch to the end
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with Path(fd).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    tmp_path = Path(tmp)
    tmp_path.replace(path)


def expand_and_extract(client, max_clicks: int, click_burst: int,
                       burst_pause: float) -> List[Dict[str, Any]]:
    """Click 'load more' until the comment count stops growing; re-extract
    after every burst and keep the largest snapshot."""
    best: List[Dict[str, Any]] = []
    clicks = 0
    while clicks < max_clicks:
        for _ in range(click_burst):
            if not client.evaluate(LOAD_MORE_CLICK):
                break
            clicks += 1
            time.sleep(1.0)
        value = client.evaluate(EXTRACT_COMMENTS)
        if not isinstance(value, dict) or value.get("error"):
            break
        comments = value.get("comments") or []
        if len(comments) > len(best):
            best = comments
        elif not value.get("more"):
            break
        time.sleep(burst_pause)
    return best


def collect_comments(client, url: str, project: str, out_path: Path,
                     max_clicks: int, challenge_wait: float) -> int:
    client.call("Runtime.enable")
    client.call("Page.navigate", {"url": url})
    time.sleep(4.0)
    wait_for_page(client, challenge_wait)
    comments = expand_and_extract(client, max_clicks, click_burst=3, burst_pause=2.0)
    atomic_write_json(out_path, {"project": project, "n": len(comments), "comments": comments})
    print(f"{project}: {len(comments)} comments -> {out_path}", flush=True)
    return len(comments)


def collect_posts(cdp_base: str, url: str, project: str, out_path: Path,
                  max_clicks: int, challenge_wait: float, nav_pause: float) -> int:
    ws_url = sure_engine.cdp_new_page(cdp_base, url)
    client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
    total = 0
    try:
        client.call("Runtime.enable")
        time.sleep(4.0)
        wait_for_page(client, challenge_wait)
        value = client.evaluate(EXTRACT_POSTS)
        posts = (value or {}).get("posts") or []
        payload = {"project": project + "-updates", "posts": []}
        atomic_write_json(out_path, payload)  # create the file before navigation
        for post in posts:
            post_url = post["url"]
            post_client = sure_engine.CDPClient(
                sure_engine._WebSocket(sure_engine.cdp_new_page(cdp_base, post_url)))
            try:
                post_client.call("Runtime.enable")
                time.sleep(3.0)
                wait_for_page(post_client, challenge_wait)
                comments = expand_and_extract(post_client, max_clicks,
                                              click_burst=3, burst_pause=2.0)
            finally:
                post_client.close()
            payload["posts"].append({
                "post_id": post["post_id"], "title": post["title"],
                "n": len(comments), "comments": comments,
            })
            total += len(comments)
            atomic_write_json(out_path, payload)  # persist per post
            print(f"  post {post['post_id']}: +{len(comments)} (total {total})", flush=True)
            time.sleep(nav_pause)  # slow cadence; fast hops look non-human
    finally:
        client.close()
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Kickstarter comments/updates via CDP visible pages (no challenge bypass).")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--url", required=True, help="campaign comments URL, or the .../posts page with --mode posts")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--mode", choices=["comments", "posts"], default="comments")
    ap.add_argument("--project", help="creator/slug label written into the output (default: derived from URL)")
    ap.add_argument("--max-clicks", type=int, default=120, help="bounded 'load more' expansion")
    ap.add_argument("--challenge-wait", type=float, default=60.0,
                    help="seconds to wait for a passive Cloudflare auto-clear before stopping")
    ap.add_argument("--nav-pause", type=float, default=8.0,
                    help="pause between post navigations (slow cadence; fast hops trip heuristics)")
    args = ap.parse_args()

    sure_engine._validate_cdp_base(args.cdp_url)
    sure_engine._validate_cdp_target("kickstarter", args.url)
    project = args.project or "/".join(p for p in args.url.split("/projects/")[-1].split("/")[:2] if p)

    if args.mode == "posts":
        total = collect_posts(args.cdp_url.rstrip("/"), args.url, project, args.out,
                              args.max_clicks, args.challenge_wait, args.nav_pause)
        print(f"DONE posts_comments={total}", flush=True)
        return
    ws_url = sure_engine.cdp_new_page(args.cdp_url.rstrip("/"), args.url)
    client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
    try:
        n = collect_comments(client, args.url, project, args.out,
                             args.max_clicks, args.challenge_wait)
        print(f"DONE comments={n}", flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()

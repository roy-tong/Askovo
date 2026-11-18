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

Runtime policy comes from `assets/platform-field-notes.json`
(`runtime_policies.kickstarter`) through `connectors/cdp_strategy.py`: one goto
per cell, one cell at a time, a 15-minute timeout circuit breaker, a bounded
session with 70% budget headroom, and blank-render/404 triage before writing an
"empty" file. A timeout is recorded and the best harvest is persisted before
the run stops; the session journal lands next to the snapshot as
`<out>.session.json`.

The CDP client implementation is reused from the engine (../sure_engine.py):
loopback-only debugger, no-redirect page creation, frame limits. Collecting a
tool is not the same as approving a route (README §6): the platform catalog
entry governs whether a study may use this channel.

Usage:
  python3 collect_cdp_kickstarter.py --cdp-url http://127.0.0.1:9222 \
      --url "https://www.kickstarter.com/projects/xbotgo/xbotgo-falcon-the-first-team-sports-camera/comments" \
      --out 02-data/raw/ks-falcon.json
  python3 collect_cdp_kickstarter.py ... --mode posts --project xbotgo/xbotgo-falcon

Exit codes: 0 collected; 2 stopped (timeout circuit, session box, challenge,
blank render) — the partial harvest is already on disk.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cdp_runtime
import cdp_strategy
from common import atomic_write_json
_spec = importlib.util.spec_from_file_location("sure_engine_cdp_ks", HERE.parent / "sure_engine.py")
sure_engine = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sure_engine)

CHALLENGE_TEXT = "just a moment|checking your browser|verify you are human|attention required"

PAGE_STATE = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const body = clean(document.body ? document.body.innerText : "");
  return {title: document.title || "", text: body.slice(0, 2000), url: location.href};
})()
"""

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


def page_state(client, guard: "cdp_strategy.SessionGuard") -> Tuple[str, Dict[str, Any]]:
    """Classify the rendered page before extracting (blank/404 are not empty corpora)."""
    value = client.evaluate(PAGE_STATE, timeout=guard.cell_budget(30.0))
    if not isinstance(value, dict):
        return "unknown", {}
    return cdp_strategy.classify_page(value.get("title", ""), value.get("text", "")), value


def wait_for_page(client, challenge_wait: float, poll: float,
                  guard: "cdp_strategy.SessionGuard") -> None:
    """Wait for render and passive Cloudflare auto-clear; hard stop otherwise."""

    def probe() -> str:
        state = client.evaluate(
            '(() => {const t = String(document.body ? document.body.innerText : "");'
            'return /%s/.test(t) ? "challenge" : document.readyState;})()' % CHALLENGE_TEXT,
            timeout=guard.cell_budget(30.0))
        return "clear" if state == "complete" else "challenge"

    result = cdp_runtime.wait_for_challenge_clear(
        probe, poll_seconds=poll, timeout_seconds=challenge_wait)
    if result["status"] == "cleared":
        time.sleep(1.0)
        return
    raise cdp_runtime.ChallengeStopped(
        "challenge_page: Cloudflare check did not clear passively within "
        f"{challenge_wait:.0f}s; the collector never bypasses challenges — "
        "finish the check by hand in the browser, then rerun")


def expand_and_extract(client, max_clicks: int, click_burst: int,
                       burst_pause: float, guard: "cdp_strategy.SessionGuard"
                       ) -> Tuple[List[Dict[str, Any]], str]:
    """Click 'load more' until the count stops growing; keep the largest snapshot.

    A timeout stops the expansion and returns the best harvest so the caller can
    persist it (an un-persisted round is a lost round).
    """
    best: List[Dict[str, Any]] = []

    def snapshot() -> List[Dict[str, Any]]:
        nonlocal best
        value = client.evaluate(EXTRACT_COMMENTS, timeout=guard.cell_budget(60.0))
        if not isinstance(value, dict) or value.get("error"):
            return best
        comments = value.get("comments") or []
        if len(comments) > len(best):
            best = comments
        return comments

    try:
        snapshot()  # expand nothing first: a partial list must not look complete
        cdp_runtime.bounded_load_more(
            lambda: bool(client.evaluate(LOAD_MORE_CLICK, timeout=guard.cell_budget(30.0))),
            lambda: len(snapshot()),
            max_clicks=max_clicks,
            burst=click_burst,
            pause_seconds=burst_pause,
        )
    except cdp_strategy.TIMEOUT_ERRORS as exc:
        guard.record_timeout(str(exc))
        return best, "timeout"
    except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
        guard.record_failure(exc, str(exc))
        return best, "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
    return best, "ok"


def collect_comments(cdp_base: str, url: str, project: str, out_path: Path,
                     max_clicks: int, challenge_wait: float,
                     guard: "cdp_strategy.SessionGuard") -> Tuple[int, str]:
    stopped = "ok"
    comments: List[Dict[str, Any]] = []
    client = None
    try:
        guard.begin_cell("comments")
        guard.navigate()  # the only goto in this cell: cdp_new_page already navigated
        client = sure_engine.CDPClient(
            sure_engine._WebSocket(sure_engine.cdp_new_page(cdp_base, url)))
        client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
        time.sleep(4.0)
        wait_for_page(client, challenge_wait, 2.0, guard)
        state, _ = page_state(client, guard)
        if state in {"blank_render", "page_not_found"}:
            stopped = state
        else:
            comments, stopped = expand_and_extract(
                client, max_clicks, click_burst=3, burst_pause=2.0, guard=guard)
    except cdp_strategy.TIMEOUT_ERRORS as exc:
        guard.record_timeout(str(exc))
        stopped = "timeout"
    except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
        guard.record_failure(exc, str(exc))
        stopped = "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
    except cdp_runtime.ChallengeStopped:
        guard.record_stop("challenge_page")
        stopped = "challenge_page"
    finally:
        guard.end_cell(stopped)
        if client is not None:
            client.close()
    if stopped in {"blank_render", "page_not_found"}:
        return 0, stopped
    payload: Dict[str, Any] = {"project": project, "n": len(comments), "comments": comments}
    if stopped != "ok":
        payload["stopped"] = stopped  # a partial harvest is never presented as complete
    atomic_write_json(out_path, payload)
    print(f"{project}: {len(comments)} comments -> {out_path} (stop={stopped})", flush=True)
    return len(comments), stopped


def collect_posts(cdp_base: str, url: str, project: str, out_path: Path,
                  max_clicks: int, challenge_wait: float, nav_pause: float,
                  guard: "cdp_strategy.SessionGuard") -> Tuple[int, str]:
    payload: Dict[str, Any] = {"project": project + "-updates", "posts": []}
    atomic_write_json(out_path, payload)  # create the file before navigation
    total = 0
    stopped = "ok"
    client = None
    try:
        guard.begin_cell("posts")
        guard.navigate()  # list page: one goto
        client = sure_engine.CDPClient(
            sure_engine._WebSocket(sure_engine.cdp_new_page(cdp_base, url)))
        client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
        time.sleep(4.0)
        wait_for_page(client, challenge_wait, 2.0, guard)
        value = client.evaluate(EXTRACT_POSTS, timeout=guard.cell_budget(30.0))
        posts = (value or {}).get("posts") or []
        guard.end_cell("ok")  # the list cell closes before the per-post cells
        for post in posts:
            guard.check_session()
            guard.begin_cell("posts")  # one cell per post page
            guard.navigate()
            post_state = "ok"
            comments: List[Dict[str, Any]] = []
            post_client = None
            try:
                post_client = sure_engine.CDPClient(
                    sure_engine._WebSocket(sure_engine.cdp_new_page(cdp_base, post["url"])))
                post_client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
                time.sleep(3.0)
                wait_for_page(post_client, challenge_wait, 2.0, guard)
                state, _ = page_state(post_client, guard)
                if state == "page_not_found":
                    post_state = state
                elif state == "blank_render":
                    post_state = state
                    stopped = state
                else:
                    comments, post_state = expand_and_extract(
                        post_client, max_clicks, click_burst=3, burst_pause=2.0, guard=guard)
            except cdp_strategy.TIMEOUT_ERRORS as exc:
                guard.record_timeout(str(exc))
                post_state = "timeout"
                stopped = "timeout"
            except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
                guard.record_failure(exc, str(exc))
                post_state = "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
                stopped = post_state
            finally:
                guard.end_cell(post_state)
                if post_client is not None:
                    post_client.close()
            entry: Dict[str, Any] = {
                "post_id": post["post_id"], "title": post["title"],
                "n": len(comments), "comments": comments,
            }
            if post_state != "ok":
                entry["stopped"] = post_state
            payload["posts"].append(entry)
            total += len(comments)
            atomic_write_json(out_path, payload)  # persist per post
            print(f"  post {post['post_id']}: +{len(comments)} (total {total}, stop={post_state})", flush=True)
            if stopped != "ok":
                break
            time.sleep(nav_pause)  # slow cadence; fast hops look non-human
    except cdp_strategy.TIMEOUT_ERRORS as exc:
        guard.record_timeout(str(exc))
        stopped = "timeout"
    except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
        guard.record_failure(exc, str(exc))
        stopped = "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
    except cdp_runtime.ChallengeStopped:
        guard.record_stop("challenge_page")
        stopped = "challenge_page"
    finally:
        guard.end_cell(stopped)
        if client is not None:
            client.close()
    if stopped != "ok":
        payload["stopped"] = stopped
        atomic_write_json(out_path, payload)
    return total, stopped


def main() -> int:
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
    policy = cdp_strategy.policy_for("kickstarter")
    journal_path = args.out.with_name(args.out.stem + ".session.json")
    guard = cdp_strategy.SessionGuard("kickstarter", policy=policy, state_path=journal_path)
    stopped = "ok"

    try:
        if args.mode == "posts":
            total, stopped = collect_posts(args.cdp_url.rstrip("/"), args.url, project, args.out,
                                           args.max_clicks, args.challenge_wait, args.nav_pause, guard)
            print(f"DONE posts_comments={total} stop={stopped}", flush=True)
        else:
            total, stopped = collect_comments(args.cdp_url.rstrip("/"), args.url, project, args.out,
                                              args.max_clicks, args.challenge_wait, guard)
            print(f"DONE comments={total} stop={stopped}", flush=True)
    except cdp_runtime.ChallengeStopped as exc:
        guard.record_stop("challenge_page")
        stopped = "challenge_page"
        print(f"STOP [challenge_page]: {exc}", file=sys.stderr)
    finally:
        guard.save()
        print(f"journal: {journal_path}", flush=True)

    if stopped != "ok":
        print(
            f"STOP [{stopped}]: stop touching kickstarter; a timeout means >= "
            f"{policy.timeout_cooldown_minutes:g} minutes of no contact before verification. "
            "Partial harvest (if any) is already persisted.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

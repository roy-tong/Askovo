#!/usr/bin/env python3
"""Discord channel message collector over a user-logged-in CDP session.

Method collected from the golf-device research project (2026-11, 4k+ messages
across 16 text channels + forum posts). The user logs in to discord.com by
hand in the CDP browser; this collector then drives authorized visible
channels. It never enters credentials and never exports cookies.

Field-verified details baked in (2026-11-17, four session drops in one day):
- Discord's internal APIs are unusable from an automation context (storage is
  sandboxed away), so collection is DOM-based;
- lazy history loading reacts only to REAL wheel events (Input.dispatchMouseEvent
  type=mouseWheel) — programmatic scrollTop assignment produces no events;
- messages are `li[id^="chat-messages-"]` nodes with author, `time[datetime]`
  absolute timestamps and message ids in the node id;
- anti-automation trips on one signature above all: a **timed-out/aborted
  operation followed by continued driving**. Fast timeout-free navigation did
  not drop the session; timeout-then-continue did, every time. A drop can also
  arrive ~40 minutes after the last operation, or from an hours-idle webview
  that failed token rotation. This collector therefore treats any timeout as a
  circuit breaker (stop, no retry, no snapshot), enforces one goto per cell,
  caps the session at the policy's time-box (40 min), scrolls slowly with a
  mouse move first, and persists after every round (an un-persisted round is a
  lost round);
- forum channels (feature-requests / bug-reports) render thread cards that
  already carry title+author+body — collect the card list, skip sidebar h3s
  (`#channels` navigation), bodies live in `div[class*="messageContent"]`;
- server invites expire; dig fresh codes from your own corpus (grep
  `discord.gg/` and check the surrounding context) rather than trusting
  official pages.

Runtime policy comes from `assets/platform-field-notes.json`
(`runtime_policies.discord`) through `connectors/cdp_strategy.py`: one cell per
run, one goto, 15-minute timeout cooldown, 40-minute session box, 60% budget
headroom, and mode exclusivity (messages / forum / invite never mix in one
session stretch). The session journal lands next to the snapshot as
`<out>.session.json` so the next run can see what was already attempted.

Output is a raw-JSON snapshot `{guild, server, channels: {name: [...]}}`
merged into a per-server file (read-modify-atomic-write). Convert into the
corpus envelope with clean_screen_corpus.py (see connectors/README.md).
Collecting a tool is not approving a route (README §6).

Usage:
  # list channel names first (no collection, no empty snapshot)
  python3 collect_cdp_discord.py --list-channels \
      --url "https://discord.com/channels/<guild>/<channel>"

  # one channel per invocation (anti-automation cadence); rotate channels slowly
  python3 collect_cdp_discord.py --cdp-url http://127.0.0.1:9222 \
      --url "https://discord.com/channels/1472004230112870610/1234567890" \
      --out 02-data/raw/discord-server.json

Exit codes: 0 collected; 2 stopped (timeout circuit, session box, session drop
or blank render) — stop touching the platform and read
``<out>.session.json`` before the next run.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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
_spec = importlib.util.spec_from_file_location("sure_engine_cdp_dc", HERE.parent / "sure_engine.py")
sure_engine = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sure_engine)

EXTRACT_HEAD = r"""
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const header = document.querySelector("h1, [class*='header-'] h1, section h1");
  const channelName = header ? clean(header.textContent) : "";
  const body = clean(document.body ? document.body.innerText : "").slice(0, 800);
"""

EXTRACT_MESSAGES = r"""
(() => {
%s
  const out = [];
  for (const li of document.querySelectorAll('li[id^="chat-messages-"]')) {
    const id = (li.id.match(/chat-messages-\\d+-\\d+-(\\d+)/) || [])[1] || li.id;
    const time = li.querySelector("time");
    const author = li.querySelector('[class*="username"], [class*="author"]');
    out.push({author: clean(author ? author.textContent : ""),
              id: id,
              t: time ? (time.getAttribute("datetime") || clean(time.textContent)) : "",
              text: clean(li.innerText).slice(0, 2000)});
  }
  return {channel: channelName, n: out.length, messages: out,
          url: location.href, body: body};
})()
""" % EXTRACT_HEAD

EXTRACT_FORUM = r"""
(() => {
%s
  const sidebar = document.querySelector("#channels");
  const out = [];
  for (const card of document.querySelectorAll('[role="button"]')) {
    if (sidebar && sidebar.contains(card)) continue;  // sidebar nav also uses h3
    const title = card.querySelector("h3");
    if (!title) continue;
    const bodyNode = card.querySelector('div[class*="messageContent"]');
    const author = card.querySelector('[class*="username"], [class*="author"]');
    const time = card.querySelector("time");
    const link = card.closest("a") || card.querySelector("a");
    out.push({author: clean(author ? author.textContent : ""),
              id: link ? (link.getAttribute("href") || "") : "",
              t: time ? (time.getAttribute("datetime") || clean(time.textContent)) : "",
              title: clean(title.textContent),
              text: clean(bodyNode ? bodyNode.innerText : card.innerText).slice(0, 2000)});
  }
  return {channel: channelName, n: out.length, messages: out,
          url: location.href, body: body};
})()
""" % EXTRACT_HEAD


EXTRACT_CHANNELS = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const out = [];
  const seen = new Set();
  const root = document.querySelector("#channels") || document;
  for (const a of root.querySelectorAll('a[href^="/channels/"]')) {
    const m = (a.getAttribute("href") || "").match(/^\/channels\/(\d+)\/(\d+)/);
    if (!m) continue;
    const name = clean(a.textContent);
    if (!name || seen.has(m[2])) continue;
    seen.add(m[2]);
    out.push({channel_id: m[2], name: name,
              url: "https://discord.com/channels/" + m[1] + "/" + m[2]});
  }
  return {channels: out, url: location.href};
})()
"""


def list_channels(client, guard) -> List[Dict[str, Any]]:
    """Snapshot the server sidebar so channels are named before they are hit.

    The campaign's blind channel scans spent cells on rules/welcome/empty
    rooms; naming first lets the operator target help/support/competitor
    channels and record empty rooms as findings.
    """
    value = client.evaluate(EXTRACT_CHANNELS, timeout=guard.cell_budget(30.0))
    if not isinstance(value, dict):
        return []
    channels = value.get("channels") or []
    return [item for item in channels if isinstance(item, dict) and item.get("channel_id")]


def wheel_up(client, times: int = 3, delta: int = 1200) -> None:
    """Real wheel events upward; a mouse move first keeps the input stream human."""
    for index in range(max(1, times)):
        cdp_runtime.wheel_scroll(client.call, delta_y=-delta, move=index == 0)


def load_server_file(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"guild": "", "server": "", "channels": {}}


def scroll_collect(client, extractor: str, guard: "cdp_strategy.SessionGuard",
                   max_rounds: int, scroll_sleep: float) -> Tuple[List[Dict[str, Any]], str]:
    """Scroll-load history until the count stalls; return (best, stop_reason).

    A timeout is recorded on the guard and ends the run: the caller still
    persists the best harvest. The session box is checked every round.
    """
    best: List[Dict[str, Any]] = []
    stale_rounds = 0
    for _ in range(max(1, max_rounds)):
        try:
            guard.check_session()
            wheel_up(client)
            time.sleep(max(0.5, scroll_sleep))
            value = client.evaluate(extractor)
        except cdp_strategy.TIMEOUT_ERRORS as exc:
            guard.record_timeout(str(exc))
            return best, "timeout"
        except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
            guard.record_failure(exc, str(exc))
            return best, "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
        if not isinstance(value, dict):
            return best, "extractor_error"
        messages = value.get("messages") or []
        if len(messages) > len(best):
            best = messages
            stale_rounds = 0
        else:
            stale_rounds += 1
            if stale_rounds >= 3:  # window exhausted
                break
    return best, "ok"


def _list_channels_main(args, guard: "cdp_strategy.SessionGuard") -> int:
    """One cell: open the server, snapshot channel names, print JSON, write nothing."""
    client = None
    stopped = "ok"
    try:
        guard.begin_cell("channels")
        guard.navigate()
        ws_url = sure_engine.cdp_new_page(args.cdp_url.rstrip("/"), args.url)
        client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
        client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
        time.sleep(6.0)
        channels = list_channels(client, guard)
        print(json.dumps({"url": args.url, "channels": channels}, ensure_ascii=False, indent=2))
    except cdp_strategy.TIMEOUT_ERRORS as exc:
        guard.record_timeout(str(exc))
        stopped = "timeout"
    except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
        guard.record_failure(exc, str(exc))
        stopped = "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
    finally:
        guard.end_cell(stopped)
        if guard.state_path is not None:
            guard.save()
        if client is not None:
            client.close()
        if guard.state_path is not None:
            print(f"journal: {guard.state_path}", file=sys.stderr, flush=True)
    if stopped != "ok":
        print(f"STOP [{stopped}]: channel listing failed; do not retry on a torn cell.",
              file=sys.stderr)
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Discord channel/forum messages via a user-logged-in CDP session (no credentials, no challenge bypass).")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--url", required=True, help="channel URL https://discord.com/channels/<guild>/<channel>")
    ap.add_argument("--out", type=Path,
                    help="per-server JSON snapshot (read-modify-write); not written with --list-channels")
    ap.add_argument("--mode", choices=["messages", "forum"], default="messages")
    ap.add_argument("--list-channels", action="store_true",
                    help="snapshot the server sidebar and print channel ids/names (no collection)")
    ap.add_argument("--channel-name", help="override the channel name detected from the page header")
    ap.add_argument("--server", help="human-readable server name for the snapshot header")
    ap.add_argument("--max-rounds", type=int, default=80,
                    help="bounded scroll rounds; leave ~30%% headroom, never let a cell time out mid-event")
    ap.add_argument("--scroll-sleep", type=float, default=2.5,
                    help="slow cadence per round (fast, steady automation trips anti-bot heuristics)")
    args = ap.parse_args()

    sure_engine._validate_cdp_base(args.cdp_url)
    sure_engine._validate_cdp_target("discord", args.url)
    guild = args.url.rstrip("/").split("/channels/")[-1].split("/")[0] or ""

    policy = cdp_strategy.policy_for("discord")
    if args.list_channels:
        state_path = (args.out.with_name(args.out.stem + ".session.json")
                      if args.out else None)
        guard = cdp_strategy.SessionGuard("discord", policy=policy, state_path=state_path)
        return _list_channels_main(args, guard)
    if not args.out:
        ap.error("--out is required for collection (omit it only with --list-channels)")
    journal_path = args.out.with_name(args.out.stem + ".session.json")
    guard = cdp_strategy.SessionGuard("discord", policy=policy, state_path=journal_path)
    payload = load_server_file(args.out)
    if guild and not payload.get("guild"):
        payload["guild"] = guild
    if args.server:
        payload["server"] = args.server
    extractor = EXTRACT_FORUM if args.mode == "forum" else EXTRACT_MESSAGES
    channel = args.channel_name or f"channel-{guild}"
    messages: List[Dict[str, Any]] = []
    stopped = "ok"
    client = None
    try:
        guard.begin_cell(args.mode)
        guard.navigate()  # the only goto in this cell
        ws_url = sure_engine.cdp_new_page(args.cdp_url.rstrip("/"), args.url)
        client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
        client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
        time.sleep(6.0)  # let the SPA render before probing
        header = client.evaluate(extractor, timeout=guard.cell_budget(60.0)) or {}
        channel = args.channel_name or header.get("channel") or channel
        if not header.get("n"):
            if cdp_strategy.looks_logged_out(header.get("url", ""), header.get("body", "")):
                guard.record_session_drop("login page after navigation")
                stopped = "session_drop"
            elif cdp_strategy.is_blank_render(header.get("channel", ""), header.get("body", "")):
                guard.record_stop("blank_render")
                stopped = "blank_render"
            elif cdp_strategy.detect_membership_gate(header.get("body", "")):
                # Join ≠ access: the server accepted the invite but gates its
                # history behind membership verification. Record the gap; never
                # attempt verification roles, bots or impersonation.
                guard.record_stop("membership_gated")
                stopped = "membership_gated"
        if stopped == "ok":
            messages, stopped = scroll_collect(
                client, extractor, guard, args.max_rounds, args.scroll_sleep)
    except cdp_strategy.TIMEOUT_ERRORS as exc:
        guard.record_timeout(str(exc))
        stopped = "timeout"
    except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
        guard.record_failure(exc, str(exc))
        stopped = "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
    finally:
        guard.end_cell(stopped)
        guard.save()
        if client is not None:
            client.close()

    if stopped in {"blank_render", "session_drop", "membership_gated"}:
        detail = {
            "blank_render": "the page rendered blank (200 + empty title/body); unsupported stack — "
                            "pivot to another source in the same vertical",
            "session_drop": "the login session is gone; a human must log in again, never the agent",
            "membership_gated": "the server accepted the join but hides its history behind member "
                                "verification; this is a coverage gap — never attempt verification "
                                "roles, bots or impersonation",
        }[stopped]
        print(f"STOP [{stopped}] {args.url}: {detail}", file=sys.stderr)
        print(f"journal: {journal_path}", file=sys.stderr)
        return 2

    if messages or stopped == "ok":
        channels = payload.setdefault("channels", {})
        merged = {m.get("id"): m for m in channels.get(channel, [])}
        for m in messages:
            merged[m.get("id")] = m  # re-scrolls refresh, never duplicate
        channels[channel] = sorted(merged.values(), key=lambda m: str(m.get("t")))
        if args.mode == "forum":
            payload.setdefault("forums", {})[channel] = channels.pop(channel)
        atomic_write_json(args.out, payload)
        print(f"{channel}: {len(messages)} messages -> {args.out} (stop={stopped})", flush=True)
    else:
        print(f"{channel}: no messages persisted (stop={stopped}); an empty file is not a corpus",
              file=sys.stderr)
    print(f"journal: {journal_path}", flush=True)

    if stopped != "ok":
        delay = policy.timeout_cooldown_minutes
        if stopped == "session_time_box":
            print(
                "STOP [session_time_box]: the Discord session time-box elapsed; log out "
                "deliberately and resume in a fresh stretch, not in this one.",
                file=sys.stderr,
            )
        else:
            print(
                f"STOP [{stopped}]: a timeout/abort is a circuit breaker on Discord — do not touch "
                f"the platform for >= {delay:g} minutes (no diagnostics, no snapshots, no retries); "
                "then verify the session by hand and resume with a fresh login.",
                file=sys.stderr,
            )
        return 2
    if guard.session_expired():
        print(
            "NOTE: the session time-box elapsed; log out deliberately before the next stretch.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

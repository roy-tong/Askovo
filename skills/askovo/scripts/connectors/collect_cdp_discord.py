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

Exit codes: 0 collected; 2 stopped (timeout circuit, session box, session drop,
blank render, or zero rows with an unconfirmed chat pane) — stop touching the
platform and read ``<out>.session.json`` before the next run. A channel that is
truly empty is only recorded after a human confirms it with --confirm-empty;
zero rows alone is a coverage gap, not an empty window.
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
  // A zero-message snapshot is only an empty channel when the message pane
  // itself rendered; the sidebar renders long before the chat area does.
  const ready = !!document.querySelector(
    'ol[data-list-id="chat-messages"], [class*="messagesWrapper"], [class*="channelTextArea"]');
"""

EXTRACT_MESSAGES_TEMPLATE = r"""
(() => {
%s
  const after = new Set(%s);
  const out = [];
  const nodes = document.querySelectorAll('li[id^="chat-messages-"]');
  for (const li of nodes) {
    const id = (li.id.match(/chat-messages-\\d+-\\d+-(\\d+)/) || [])[1] || li.id;
    if (after.has(id)) continue;
    const time = li.querySelector("time");
    const author = li.querySelector('[class*="username"], [class*="author"]');
    out.push({author: clean(author ? author.textContent : ""),
              id: id,
              t: time ? (time.getAttribute("datetime") || clean(time.textContent)) : "",
              text: clean(li.innerText).slice(0, 2000)});
  }
  return {channel: channelName, n: out.length, total: nodes.length, ready: ready,
          messages: out, url: location.href, body: body};
})()
"""

EXTRACT_MESSAGES = EXTRACT_MESSAGES_TEMPLATE % (EXTRACT_HEAD, "[]")

# The mounted window is far smaller than Discord's full history; cap the
# exclusion list so the expression stays bounded even after a long session.
MAX_AFTER_IDS = 800


def message_extractor(after=None) -> str:
    """Build the message extractor that skips ids already in ``after``.

    Re-reading the whole mounted list every round forces a layout for each
    message; on a long channel that is what pushes one `evaluate` past the
    cell budget. Asking the DOM for only unseen nodes keeps each round cheap
    and lets the browser discard old nodes it would have unmounted anyway.
    """
    ids = sorted({str(item) for item in (after or ()) if item})
    return EXTRACT_MESSAGES_TEMPLATE % (EXTRACT_HEAD, json.dumps(ids[-MAX_AFTER_IDS:]))


PROBE_RENDER = r"""
(() => {
  const n = document.querySelectorAll('li[id^="chat-messages-"]').length;
  const ready = !!document.querySelector(
    'ol[data-list-id="chat-messages"], [class*="messagesWrapper"], [class*="channelTextArea"]');
  return {n: n, ready: ready};
})()
"""

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
  return {channel: channelName, n: out.length, ready: ready, messages: out,
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


def _poll_render(client, budget: float, poll: float = 0.25, sleep=None,
                 timeout: float = None) -> None:
    """Probe the mounted pane, back off, and stop as soon as it renders.

    ``budget`` is a ceiling, not a fixed cost: a warm pane returns on the first
    cheap probe instead of paying the full render wait. The probe reads counts
    and selectors only — no input events, no navigation.
    """
    sleep = sleep or time.sleep
    remaining = max(0.0, float(budget))
    step = max(0.05, float(poll))
    while True:
        probe = client.evaluate(PROBE_RENDER, timeout=timeout) or {}
        if not isinstance(probe, dict):
            return
        if probe.get("n") or probe.get("ready"):
            return
        if remaining <= 0:
            return
        nap = min(step, remaining)
        sleep(nap)
        remaining -= nap
        step = min(max(step * 1.5, float(poll)), 2.0)


def wait_until_ready(client, extractor, budget: float, poll: float = 0.25,
                     sleep=None, timeout: float = None) -> Dict[str, Any]:
    """Wait for the chat pane to mount, then take one full extraction."""
    _poll_render(client, budget, poll, sleep, timeout)
    value = client.evaluate(extractor, timeout=timeout) or {}
    return value if isinstance(value, dict) else {}


def wait_for_render(client, extractor: str, first: Dict[str, Any], grace: float,
                    poll: float = 0.25, sleep=None, timeout: float = None) -> Dict[str, Any]:
    """Give a zero-message page its passive render window before judging it.

    Discord mounts the shell before the chat pane, so zero rows on the first
    probe is a timing signal, not an empty channel. Cheap probes watch for the
    pane (or its first message) and escalate only when it stays blank; the full
    extraction runs once at the end, not once per second.
    """
    value = first if isinstance(first, dict) else {}
    if value.get("n") or value.get("ready"):
        return value
    _poll_render(client, grace, poll, sleep, timeout)
    value = client.evaluate(extractor, timeout=timeout) or {}
    return value if isinstance(value, dict) else {}


def wait_for_channels(client, guard, budget: float, poll: float = 0.25,
                      sleep=None) -> List[Dict[str, Any]]:
    """Poll the sidebar until it renders; ``budget`` is the ceiling, not a cost."""
    sleep = sleep or time.sleep
    remaining = max(0.0, float(budget))
    step = max(0.05, float(poll))
    while True:
        channels = list_channels(client, guard)
        if channels or remaining <= 0:
            return channels
        nap = min(step, remaining)
        sleep(nap)
        remaining -= nap
        step = min(max(step * 1.5, float(poll)), 2.0)


def load_server_file(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"guild": "", "server": "", "channels": {}}


def scroll_collect(client, extractor, guard: "cdp_strategy.SessionGuard",
                   max_rounds: int, scroll_sleep: float,
                   *, seed=None) -> Tuple[List[Dict[str, Any]], str]:
    """Scroll-load history until the count stalls; return (best, stop_reason).

    ``extractor`` may be a callable that receives the already-seen ids and
    returns an incremental expression, or a plain expression string (legacy
    full re-read). The seed is the first screen: a virtual list unmounts rows
    as the user scrolls, so rows seen before the scroll must ride along.

    A timeout is recorded on the guard and ends the run: the caller still
    persists the best harvest. The session box is checked every round.
    """
    incremental = callable(extractor)
    seed_rows = [dict(row) for row in (seed or []) if isinstance(row, dict)]
    best: List[Dict[str, Any]] = list(seed_rows)
    index: Dict[str, int] = {}
    for position, row in enumerate(best):
        if row.get("id") is not None:
            index[str(row["id"])] = position
    stale_rounds = 0
    rounds = 0
    started = time.monotonic()

    def absorb(rows: List[Any]) -> int:
        nonlocal best
        if not incremental:
            if len(rows) > len(best):
                best = rows
                return len(best)
            return 0
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("id") is None:
                best.append(row)
                added += 1
                continue
            key = str(row["id"])
            if key in index:
                best[index[key]] = row  # refresh text/timestamps in place
            else:
                index[key] = len(best)
                best.append(row)
                added += 1
        return added

    def report() -> None:
        guard.record_metric("rounds", rounds)
        guard.record_metric("new_messages", max(0, len(best) - len(seed_rows)))
        guard.record_metric("stale_rounds", stale_rounds)
        guard.record_metric("incremental", incremental)
        guard.record_metric("extract_seconds", round(time.monotonic() - started, 3))

    for _ in range(max(1, max_rounds)):
        rounds += 1
        try:
            guard.check_session()
            wheel_up(client)
            time.sleep(max(0.5, scroll_sleep))
            if incremental:
                value = client.evaluate(extractor(list(index)),
                                        timeout=guard.cell_budget(60.0))
            else:
                value = client.evaluate(extractor)
        except cdp_strategy.TIMEOUT_ERRORS as exc:
            guard.record_timeout(str(exc))
            report()
            return best, "timeout"
        except (cdp_strategy.CircuitOpen, cdp_strategy.SessionExpired) as exc:
            guard.record_failure(exc, str(exc))
            report()
            return best, "circuit_open" if isinstance(exc, cdp_strategy.CircuitOpen) else "session_time_box"
        if not isinstance(value, dict):
            report()
            return best, "extractor_error"
        added = absorb(value.get("messages") or [])
        if added:
            stale_rounds = 0
            continue
        stale_rounds += 1
        if stale_rounds >= 3:  # window exhausted
            break
    report()
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
        channels = wait_for_channels(client, guard,
                                     getattr(args, "render_wait", 8.0),
                                     getattr(args, "render_poll", 0.25))
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
    ap.add_argument("--render-wait", type=float, default=8.0,
                    help="ceiling (not a fixed cost) for the passive first render; the collector "
                         "probes cheaply and proceeds as soon as the chat pane mounts")
    ap.add_argument("--render-poll", type=float, default=0.25,
                    help="initial probe interval in seconds; grows up to 2s while the pane stays blank")
    ap.add_argument("--empty-grace", type=float, default=6.0,
                    help="extra seconds of re-probing when the first probe sees zero messages")
    ap.add_argument("--confirm-empty", action="store_true",
                    help="record a rendered zero-message channel as an empty finding; without "
                         "this flag zero rows is an unconfirmed gap, never an empty window")
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
    empty_confirmed = False
    client = None
    try:
        guard.begin_cell(args.mode)
        guard.navigate()  # the only goto in this cell
        ws_url = sure_engine.cdp_new_page(args.cdp_url.rstrip("/"), args.url)
        client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
        client.call("Runtime.enable", timeout=guard.cell_budget(30.0))
        header = wait_until_ready(
            client, extractor, args.render_wait, args.render_poll,
            timeout=guard.cell_budget(60.0))
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
            else:
                header = wait_for_render(client, extractor, header, args.empty_grace,
                                         args.render_poll,
                                         timeout=guard.cell_budget(60.0))
                if not header.get("n"):
                    if header.get("ready") and args.confirm_empty:
                        empty_confirmed = True
                    else:
                        # A slow pane and a truly empty channel look identical
                        # from here; a human decides, the collector never
                        # records an empty window on a guess.
                        guard.record_stop("empty_unconfirmed")
                        stopped = "empty_unconfirmed"
        if stopped == "ok":
            scroll_extractor = extractor if args.mode == "forum" else message_extractor
            messages, stopped = scroll_collect(
                client, scroll_extractor, guard, args.max_rounds, args.scroll_sleep,
                seed=header.get("messages") or [])
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

    if stopped in {"blank_render", "session_drop", "membership_gated", "empty_unconfirmed"}:
        detail = {
            "blank_render": "the page rendered blank (200 + empty title/body); unsupported stack — "
                            "pivot to another source in the same vertical",
            "session_drop": "the login session is gone; a human must log in again, never the agent",
            "membership_gated": "the server accepted the join but hides its history behind member "
                                "verification; this is a coverage gap — never attempt verification "
                                "roles, bots or impersonation",
            "empty_unconfirmed": "zero messages and the chat pane never confirmed it rendered; a slow "
                                 "SPA and an empty channel are indistinguishable from here. Inspect "
                                 "the tab by hand; if the channel is truly empty, re-run with "
                                 "--confirm-empty to record it as a finding",
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
        if empty_confirmed:
            print(f"{channel}: 0 messages (empty_confirmed by --confirm-empty) -> {args.out}",
                  flush=True)
        else:
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

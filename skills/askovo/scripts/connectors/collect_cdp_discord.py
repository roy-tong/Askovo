#!/usr/bin/env python3
"""Discord channel message collector over a user-logged-in CDP session.

Method collected from the golf-device research project (2026-11, 4k+ messages
across 16 text channels + forum posts). The user logs in to discord.com by
hand in the CDP browser; this collector then drives authorized visible
channels. It never enters credentials and never exports cookies.

Field-verified details baked in:
- Discord's internal APIs are unusable from an automation context (storage is
  sandboxed away), so collection is DOM-based;
- lazy history loading reacts only to REAL wheel events (Input.dispatchMouseEvent
  type=mouseWheel) — programmatic scrollTop assignment produces no events;
- messages are `li[id^="chat-messages-"]` nodes with author, `time[datetime]`
  absolute timestamps and message ids in the node id;
- anti-automation trips on: rapid channel hops, cell timeouts that tear input
  streams mid-event, and 30-40 min of inhumanly steady scrolling. This
  collector therefore moves the mouse before scrolling, keeps one page per
  run, scrolls slowly, and persists after every round (field lesson: an
  un-persisted round is a lost round);
- forum channels (feature-requests / bug-reports) render thread cards that
  already carry title+author+body — collect the card list, skip sidebar h3s
  (`#channels` navigation), bodies live in `div[class*="messageContent"]`;
- server invites expire; dig fresh codes from your own corpus (grep
  `discord.gg/` and check the surrounding context) rather than trusting
  official pages.

Output is a raw-JSON snapshot `{guild, server, channels: {name: [...]}}`
merged into a per-server file (read-modify-atomic-write). Convert into the
corpus envelope with clean_screen_corpus.py (see connectors/README.md).
Collecting a tool is not approving a route (README §6).

Usage:
  # one channel per invocation (anti-automation cadence); rotate channels slowly
  python3 collect_cdp_discord.py --cdp-url http://127.0.0.1:9222 \
      --url "https://discord.com/channels/1472004230112870610/1234567890" \
      --out 02-data/raw/discord-server.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sure_engine_cdp_dc", HERE.parent / "sure_engine.py")
sure_engine = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sure_engine)

EXTRACT_MESSAGES = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const header = document.querySelector("h1, [class*='header-'] h1, section h1");
  const channelName = header ? clean(header.textContent) : "";
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
  return {channel: channelName, n: out.length, messages: out};
})()
"""

EXTRACT_FORUM = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const header = document.querySelector("h1, [class*='header-'] h1, section h1");
  const channelName = header ? clean(header.textContent) : "";
  const sidebar = document.querySelector("#channels");
  const out = [];
  for (const card of document.querySelectorAll('[role="button"]')) {
    if (sidebar && sidebar.contains(card)) continue;  // sidebar nav also uses h3
    const title = card.querySelector("h3");
    if (!title) continue;
    const body = card.querySelector('div[class*="messageContent"]');
    const author = card.querySelector('[class*="username"], [class*="author"]');
    const time = card.querySelector("time");
    const link = card.closest("a") || card.querySelector("a");
    out.push({author: clean(author ? author.textContent : ""),
              id: link ? (link.getAttribute("href") || "") : "",
              t: time ? (time.getAttribute("datetime") || clean(time.textContent)) : "",
              title: clean(title.textContent),
              text: clean(body ? body.innerText : card.innerText).slice(0, 2000)});
  }
  return {channel: channelName, n: out.length, messages: out};
})()
"""


def wheel_up(client, times: int = 3, delta: int = 1200) -> None:
    """Real wheel events upward; a mouse move first keeps the input stream human."""
    client.call("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": 640, "y": 360, "button": "none", "pointerType": "mouse"})
    for _ in range(times):
        client.call("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": 640, "y": 360, "deltaX": 0, "deltaY": -delta,
            "button": "none", "pointerType": "mouse"})


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with Path(fd).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    Path(tmp).replace(path)


def load_server_file(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"guild": "", "server": "", "channels": {}}


def scroll_collect(client, extractor: str, channel_key: str,
                   max_rounds: int, scroll_sleep: float) -> List[Dict[str, Any]]:
    """Scroll-load history until the message count stops growing; persist per round."""
    best: List[Dict[str, Any]] = []
    stale_rounds = 0
    for _ in range(max_rounds):
        wheel_up(client)
        time.sleep(scroll_sleep)
        value = client.evaluate(extractor)
        if not isinstance(value, dict):
            break
        messages = value.get("messages") or []
        if len(messages) > len(best):
            best = messages
            stale_rounds = 0
        else:
            stale_rounds += 1
            if stale_rounds >= 3:  # window exhausted
                break
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description="Discord channel/forum messages via a user-logged-in CDP session (no credentials, no challenge bypass).")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--url", required=True, help="channel URL https://discord.com/channels/<guild>/<channel>")
    ap.add_argument("--out", required=True, type=Path, help="per-server JSON snapshot (read-modify-write)")
    ap.add_argument("--mode", choices=["messages", "forum"], default="messages")
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

    payload = load_server_file(args.out)
    if guild and not payload.get("guild"):
        payload["guild"] = guild
    if args.server:
        payload["server"] = args.server

    extractor = EXTRACT_FORUM if args.mode == "forum" else EXTRACT_MESSAGES
    ws_url = sure_engine.cdp_new_page(args.cdp_url.rstrip("/"), args.url)
    client = sure_engine.CDPClient(sure_engine._WebSocket(ws_url))
    try:
        client.call("Runtime.enable")
        time.sleep(6.0)  # let the SPA render before probing
        header = client.evaluate(extractor) or {}
        channel = args.channel_name or header.get("channel") or f"channel-{guild}"
        messages = scroll_collect(client, extractor, channel,
                                  args.max_rounds, args.scroll_sleep)
    finally:
        client.close()

    channels = payload.setdefault("channels", {})
    merged = {m.get("id"): m for m in channels.get(channel, [])}
    for m in messages:
        merged[m.get("id")] = m  # re-scrolls refresh, never duplicate
    channels[channel] = sorted(merged.values(), key=lambda m: str(m.get("t")))
    if args.mode == "forum":
        payload.setdefault("forums", {})[channel] = channels.pop(channel)
    atomic_write_json(args.out, payload)
    print(f"{channel}: {len(messages)} messages -> {args.out}", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reusable CDP operation helpers for the CDP collectors.

Field-verified patterns from the golf-device research campaign (2026-11),
extracted so every CDP collector does not re-derive them: passive challenge
waits, real wheel events, tab re-binding, bounded "load more" expansion and
parallel lanes.

Boundaries (identical to the collectors and the capture gate):

- **Never bypass a challenge.** :func:`wait_for_challenge_clear` only polls;
  an interactive interstitial is a hard stop for a human.
- **Login sessions are user-operated only.** Nothing here enters credentials,
  reads stored credentials or exports cookies.
- **Bounded everything.** Every loop takes a cap; the caller owns the budget
  and persists after each round (an un-persisted round is a lost round).
- **One tab per site.** :func:`run_lanes` refuses two lanes on the same site:
  per-site cadence is the invariant that keeps a two-tab pipeline safe.

Standard library only; compatible with Python 3.9+.

Usage:
  python3 cdp_runtime.py --help
  python3 cdp_runtime.py --selftest   # offline checks of the pure helpers
"""
from __future__ import annotations

import argparse
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

Pattern = Union[str, "re.Pattern[str]"]


class TabNotFound(LookupError):
    """No tab matched the pattern after every re-list attempt."""


class ChallengeStopped(RuntimeError):
    """A challenge page needs human interaction; the agent must stop."""


def wait_for_challenge_clear(
    probe: Callable[[], str],
    *,
    poll_seconds: float = 2.0,
    timeout_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Poll a page until a passive challenge clears; stop on interaction.

    ``probe()`` returns one of:

    - ``"clear"`` — the page finished loading, continue collecting;
    - ``"challenge"`` — the interstitial is still up, keep polling passively;
    - anything else (e.g. ``"interactive"``) — needs a human, stop now.

    Returns ``{"status": "cleared"|"interactive"|"timeout", "polls": int,
    "waited_seconds": float}``. The caller decides whether a timeout is a hard
    stop (the collectors raise ``ChallengeStopped``) or a route failure.
    """
    started = clock()
    polls = 0
    while True:
        state = str(probe() or "clear")
        polls += 1
        waited = round(clock() - started, 3)
        if state == "clear":
            return {"status": "cleared", "polls": polls, "waited_seconds": waited}
        if state != "challenge":
            return {"status": state, "polls": polls, "waited_seconds": waited}
        if clock() - started >= timeout_seconds:
            return {"status": "timeout", "polls": polls, "waited_seconds": waited}
        sleep(poll_seconds)


def wheel_scroll(
    send: Callable[[str, Dict[str, Any]], Any],
    *,
    delta_y: int = -1200,
    x: int = 640,
    y: int = 360,
    move: bool = True,
) -> List[Dict[str, Any]]:
    """Dispatch a real wheel event through the CDP ``Input`` domain.

    Lazy history loading ignores programmatic ``scrollTop`` writes; the moving
    input stream is what the page reacts to. A short ``mouseMoved`` before the
    wheel keeps the stream human-shaped (field lesson: Discord drops sessions
    that scroll with no organic mouse movement).

    ``send`` is ``client.call``-shaped: ``send(method, params)``. Returns the
    events that were dispatched, for the raw-JSON snapshot.
    """
    events: List[Dict[str, Any]] = []
    if move:
        events.append(
            {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
                "pointerType": "mouse",
            }
        )
    events.append(
        {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": 0,
            "deltaY": int(delta_y),
            "button": "none",
            "pointerType": "mouse",
        }
    )
    for event in events:
        send("Input.dispatchMouseEvent", event)
    return events


def rebind_tab(
    list_tabs: Callable[[], Sequence[Mapping[str, Any]]],
    pattern: Pattern,
    *,
    attempts: int = 3,
    pause_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Find a tab by URL pattern, re-listing on every attempt.

    Tab bindings rot: a ``tabs.find()`` on a URL pattern breaks after redirects
    or reloads and then silently produces zero rows on the wrong tab. Re-list
    and re-bind by stable tab id, and keep navigate→verify→collect in one cell.
    """
    regex = re.compile(pattern) if isinstance(pattern, str) else pattern
    for attempt in range(max(1, attempts)):
        for tab in list_tabs() or []:
            if not isinstance(tab, Mapping):
                continue
            url = str(tab.get("url") or "")
            if regex.search(url):
                return tab
        if attempt + 1 < max(1, attempts):
            sleep(pause_seconds)
    raise TabNotFound(
        f"no tab matches {getattr(regex, 'pattern', pattern)!r} after {attempts} attempt(s); "
        "URL patterns rot after redirects — re-list tabs and re-bind by stable id"
    )


def bounded_load_more(
    click: Callable[[], bool],
    count: Callable[[], int],
    *,
    max_clicks: int = 20,
    burst: int = 3,
    pause_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    initial_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Click "load more" in bounded bursts until the list stops growing.

    A page often renders ~25 of 58 comments until expansion; one extraction
    returns a plausible but partial list. Click a small burst, re-extract, stop
    when the row count stops growing or the button disappears, and cap total
    clicks. Returns ``{"clicks": int, "rows": int, "stopped": "cap"|"stalled"|"no_more"}``.

    ``initial_rows`` lets a caller that already took a snapshot skip the extra
    full extraction at the top of the loop.
    """
    rows = count() if initial_rows is None else max(0, int(initial_rows))
    clicks = 0
    while clicks < max_clicks:
        clicked = False
        for _ in range(max(1, burst)):
            if clicks >= max_clicks or not click():
                break
            clicked = True
            clicks += 1
            sleep(pause_seconds)
        if not clicked:
            return {"clicks": clicks, "rows": rows, "stopped": "no_more"}
        latest = count()
        if latest <= rows:
            return {"clicks": clicks, "rows": rows, "stopped": "stalled"}
        rows = latest
    return {"clicks": clicks, "rows": rows, "stopped": "cap"}


def run_lanes(
    lanes: Mapping[str, Callable[[], Any]],
    *,
    site_of: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Run independent collection lanes concurrently and collect their results.

    Throughput is usually bound by page-render waits, not by per-site rate:
    no-login archives run as background processes while two logged-in tabs on
    *different* sites render in parallel and persist per cell. Per-site cadence
    stays flat because each site only sees its own tab's sequential requests.

    ``site_of`` declares the site each lane touches; two lanes on the same site
    would double that site's rate and is rejected. Returns
    ``{"results": {lane: value}, "errors": {lane: "ExcType: message"},
    "duration_seconds": float, "lanes": [...]}`` — one lane's failure never
    discards another lane's harvest.
    """
    if not lanes:
        raise ValueError("run_lanes needs at least one lane")
    sites = dict(site_of or {})
    unknown = sorted(set(sites) - set(lanes))
    if unknown:
        raise ValueError(f"site_of names unknown lane(s): {', '.join(unknown)}")
    owners: Dict[str, str] = {}
    for lane, site in sites.items():
        if site in owners:
            raise ValueError(
                f"lanes {owners[site]!r} and {lane!r} share site {site!r}: "
                "one tab per site — a second tab would double that site's rate"
            )
        owners[site] = lane

    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    lock = threading.Lock()

    def worker(name: str, fn: Callable[[], Any]) -> None:
        try:
            value = fn()
        except BaseException as exc:  # noqa: BLE001 - report, never kill the sibling lane
            with lock:
                errors[name] = f"{type(exc).__name__}: {exc}"
            return
        with lock:
            results[name] = value

    threads = [
        threading.Thread(target=worker, args=(name, fn), name=f"lane-{name}", daemon=True)
        for name, fn in lanes.items()
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {
        "results": results,
        "errors": errors,
        "duration_seconds": round(time.monotonic() - started, 3),
        "lanes": list(lanes),
    }


def _selftest() -> int:
    """Offline checks of the pure helpers (no browser, no network)."""
    failures: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if not condition:
            failures.append(f"{name}: {detail}".rstrip(": "))

    # Challenge wait: passive clear, interactive stop, timeout.
    sleeps: List[float] = []
    states = iter(["challenge", "challenge", "clear"])
    result = wait_for_challenge_clear(lambda: next(states), sleep=sleeps.append)
    check("challenge-clears", result["status"] == "cleared" and result["polls"] == 3, str(result))
    result = wait_for_challenge_clear(lambda: "interactive", sleep=sleeps.append)
    check("challenge-interactive", result["status"] == "interactive", str(result))
    ticks = iter([0.0, 0.0, 5.0, 30.0, 120.0])
    result = wait_for_challenge_clear(
        lambda: "challenge", timeout_seconds=60.0, sleep=lambda _: None, clock=lambda: next(ticks)
    )
    check("challenge-timeout", result["status"] == "timeout", str(result))

    # Wheel events: mouse move first, then wheel.
    sent: List[tuple[str, Dict[str, Any]]] = []
    events = wheel_scroll(lambda method, params: sent.append((method, params)))
    check("wheel-events", [e["type"] for e in events] == ["mouseMoved", "mouseWheel"], str(events))
    check("wheel-domain", all(method == "Input.dispatchMouseEvent" for method, _ in sent), str(sent))
    check("wheel-delta", events[-1]["deltaY"] == -1200, str(events[-1]))

    # Tab re-binding: re-list on every attempt.
    listings = iter([[], [{"id": "t1", "url": "https://discord.com/channels/1/2"}]])
    tab = rebind_tab(lambda: next(listings), r"discord\.com", pause_seconds=0.0, sleep=lambda _: None)
    check("rebind-tab", tab.get("id") == "t1", str(tab))
    try:
        rebind_tab(lambda: [], r"nope", attempts=2, sleep=lambda _: None)
        check("rebind-missing", False, "expected TabNotFound")
    except TabNotFound:
        pass

    # Bounded load-more: stops when the count stalls.
    counts = iter([25, 25])
    summary = bounded_load_more(
        lambda: True, lambda: next(counts), max_clicks=10, burst=1, sleep=lambda _: None
    )
    check("load-more-stalled", summary["stopped"] == "stalled" and summary["rows"] == 25, str(summary))
    counter = {"rows": 0}

    def grow() -> int:
        counter["rows"] += 5
        return counter["rows"]

    summary = bounded_load_more(
        lambda: True, grow, max_clicks=4, burst=1, sleep=lambda _: None
    )
    check("load-more-cap", summary["stopped"] == "cap" and summary["clicks"] == 4, str(summary))

    # Lanes: parallel, isolated failures, duplicate-site guard.
    out = run_lanes({"a": lambda: 1, "b": lambda: (_ for _ in ()).throw(RuntimeError("boom"))})
    check("lanes-results", out["results"] == {"a": 1}, str(out))
    check("lanes-errors", "boom" in out["errors"].get("b", ""), str(out))
    try:
        run_lanes({"a": lambda: 1, "b": lambda: 2}, site_of={"a": "x.com", "b": "x.com"})
        check("lanes-duplicate-site", False, "expected ValueError")
    except ValueError:
        pass

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[ok] cdp_runtime selftest: challenge wait, wheel events, tab rebind, bounded load-more, lanes")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reusable CDP operation helpers (passive challenge waits, real wheel events, "
        "tab re-binding, bounded load-more, parallel lanes). No credentials, no challenge bypass.",
    )
    parser.add_argument("--selftest", action="store_true", help="run the offline helper checks and exit")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

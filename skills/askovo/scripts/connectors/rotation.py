#!/usr/bin/env python3
"""Multi-platform rotation scheduler: stay under every site's frequency radar.

Field-verified strategy from the golf-device research campaign (2026-11): when a
study needs several platforms, throughput comes from **overlapping different
sites**, never from raising any one site's frequency. The operator rotates one
round per platform, each site only sees its own sequential requests, and the
waits of the other sites are overlapped.

This module encodes the invariants that make rotation safe to automate:

- **per-site minimum interval** — a platform cannot be hit again before its
  cadence elapses (rotating to another platform is how the wait is spent);
- **classified cooldown** — 429/403 wait for the reset header, 422 "slow down"
  backs off, permanent statuses stop the platform (see
  :func:`common.classify_backoff`);
- **session health** — a dropped login session puts the platform in cooldown
  until a *human* re-logs in; the agent never re-authenticates itself;
- **daily quota** — a capped platform is unavailable until the next UTC day;
- **one tab per site** — the scheduler refuses duplicate platforms and never
  treats two tabs on one site as parallelism;
- **resume** — the whole state is JSON-serializable, so a restarted run
  continues the rotation instead of re-hitting hot platforms.

Boundaries (identical to the collectors): no identity/proxy rotation, no
challenge bypass, no credential entry. A blocked platform is a recorded gap.

Standard library only; compatible with Python 3.9+.

Usage:
  python3 rotation.py --help
  python3 rotation.py --plan discord,x,reddit   # one round in fair order
  python3 rotation.py --selftest                # offline checks
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import common

# Field cadences (seconds) per route family that has no CDP runtime policy
# (Reddit/YouTube archives). CDP platforms read their cadence from the
# field-notes registry's runtime_policies, so the scheduler and the collectors
# cannot drift apart on the same site.
PLATFORM_CADENCE_DEFAULTS: Dict[str, float] = {
    "reddit": 3.0,
    "youtube": 2.5,
    "discord": 20.0,
    "x": 10.0,
    "instagram": 10.0,
    "tiktok": 15.0,
    "vertical_forum": 5.0,
}
SESSION_PLATFORMS = frozenset({"discord", "x", "instagram", "tiktok"})


def _runtime_policy(platform: str):
    """The registry's policy for a CDP platform, or None for non-CDP routes.

    Imported lazily so `rotation.py` stays usable when the registry is absent
    during a standalone copy; the registry is authoritative for any platform it
    declares an override for.
    """
    try:
        import cdp_strategy  # local import: no hard dependency for archive-only users
        section = cdp_strategy.load_runtime_policies()
        return cdp_strategy.policy_for(platform, section)
    except Exception:  # pragma: no cover - registry missing during a copied script
        return None


class PlatformCooling(RuntimeError):
    """The platform is not available yet; rotating to another one is the strategy."""

    def __init__(self, platform: str, wait_seconds: float, reason: str) -> None:
        self.platform = platform
        self.wait_seconds = wait_seconds
        self.reason = reason
        super().__init__(f"{platform} cooling: {wait_seconds:.1f}s ({reason})")


@dataclass
class Cadence:
    """Per-platform rotation budget."""

    platform: str
    min_interval: float = 3.0
    daily_cap: Optional[int] = None
    risk_tier: str = "normal"
    requires_session: bool = False
    channel: str = ""
    account_id: str = ""
    account_tier: str = "unknown"


@dataclass
class _PlatformState:
    next_at: float = 0.0
    day: Optional[str] = None
    count: int = 0
    attempt: int = 0
    cooldown_reason: str = ""
    requires_human: bool = False


def build_cadences(
    platforms: Iterable[str],
    account: str = "",
    policy_path: Optional[Path] = None,
    **overrides: Any,
) -> List[Cadence]:
    """Cadences from the registry and the persistent per-account policy.

    A platform with a `runtime_policies` override takes its cadence and session
    requirement from the registry — the same numbers `cdp_strategy.py` enforces
    for collectors. Platforms without an override (Reddit/YouTube archives) keep
    the field table below. Explicit keyword overrides still win.
    """
    try:
        import account_policy
    except ImportError:  # pragma: no cover - standalone copied scheduler
        account_policy = None
    cadences: List[Cadence] = []
    for platform in platforms:
        name = str(platform)
        policy = _runtime_policy(name)
        account_view = (account_policy.view_for(
            name, "collect", account, path=policy_path,
        ) if account_policy is not None else {
            "account_id": "", "account_tier": "unknown", "daily_cap": None,
        })
        if "min_interval" in overrides:
            min_interval = float(overrides["min_interval"])
        elif policy is not None:
            min_interval = float(policy.cadence_seconds)
        else:
            min_interval = float(PLATFORM_CADENCE_DEFAULTS.get(name, 3.0))
        if "requires_session" in overrides:
            requires_session = bool(overrides["requires_session"])
        elif policy is not None:
            requires_session = bool(policy.requires_session)
        else:
            requires_session = name in SESSION_PLATFORMS
        cadences.append(
            Cadence(
                platform=name,
                min_interval=min_interval,
                daily_cap=(overrides["daily_cap"] if "daily_cap" in overrides
                           else account_view["daily_cap"]),
                risk_tier=str(overrides.get("risk_tier", "elevated" if requires_session else "normal")),
                requires_session=requires_session,
                channel=str(overrides.get("channel", "")),
                account_id=str(account_view["account_id"]),
                account_tier=str(account_view["account_tier"]),
            )
        )
    return cadences


class RotationScheduler:
    """Round-robin rotation across platforms with per-site cadence budgets."""

    def __init__(
        self,
        cadences: Iterable[Cadence],
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        session_cooldown: float = 1800.0,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._session_cooldown = float(session_cooldown)
        self._cadences: Dict[str, Cadence] = {}
        self._state: Dict[str, _PlatformState] = {}
        for cadence in cadences:
            name = str(cadence.platform)
            if not name:
                raise ValueError("cadence.platform must be a non-empty string")
            if name in self._cadences:
                raise ValueError(
                    f"duplicate platform {name!r}: two cadences on one site would double its rate"
                )
            if cadence.min_interval < 0:
                raise ValueError(f"{name}: min_interval must be >= 0")
            self._cadences[name] = cadence
            self._state[name] = _PlatformState()
        if not self._cadences:
            raise ValueError("RotationScheduler needs at least one platform cadence")

    # -- introspection -----------------------------------------------------
    @property
    def platforms(self) -> List[str]:
        return list(self._cadences)

    def cadence(self, platform: str) -> Cadence:
        try:
            return self._cadences[str(platform)]
        except KeyError as exc:
            raise KeyError(f"platform {platform!r} has no cadence; schedule it first") from exc

    def _now(self) -> float:
        return float(self._clock())

    @staticmethod
    def _day_key(now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()

    def _seconds_until_next_day(self, now: float) -> float:
        moment = datetime.fromtimestamp(now, tz=timezone.utc)
        tomorrow = datetime.combine(
            date.fromordinal(moment.date().toordinal() + 1), datetime.min.time(), tzinfo=timezone.utc
        )
        return max(0.0, tomorrow.timestamp() - now)

    def _roll_day(self, platform: str, now: float) -> _PlatformState:
        state = self._state[platform]
        today = self._day_key(now)
        if state.day != today:
            state.day = today
            state.count = 0
        return state

    # -- readiness ---------------------------------------------------------
    def seconds_until_ready(self, platform: str) -> float:
        """Seconds before the platform may be hit (``inf`` = human re-login)."""
        self.cadence(platform)
        now = self._now()
        state = self._roll_day(str(platform), now)
        if state.requires_human:
            return float("inf")
        cadence = self._cadences[str(platform)]
        if cadence.daily_cap is not None and state.count >= cadence.daily_cap:
            return self._seconds_until_next_day(now)
        return max(0.0, state.next_at - now)

    def next_platform(self) -> Optional[str]:
        """The platform that becomes ready first (``None`` when all need a human)."""
        ready = [
            (self.seconds_until_ready(platform), platform)
            for platform in self._cadences
        ]
        ready = [item for item in ready if item[0] != float("inf")]
        if not ready:
            return None
        return min(ready)[1]

    def plan_round(self, *, limit: Optional[int] = None) -> List[str]:
        """Fair rotation order for one round: fastest cadence first, gated last.

        This is the round the operator runs: one action per platform, then
        switch. Sites that need a human re-login sort last and are never
        silently retried.
        """
        ordered = sorted(
            self._cadences,
            key=lambda platform: (
                self._state[platform].requires_human,
                self._cadences[platform].min_interval,
                platform,
            ),
        )
        return ordered[:limit] if limit else ordered

    # -- lifecycle ---------------------------------------------------------
    def acquire(self, platform: str, *, wait: bool = False) -> float:
        """Reserve the platform for one round.

        Returns the seconds spent waiting (0.0 when ready). With ``wait=False``
        a cooling platform raises :class:`PlatformCooling` — the caller rotates
        instead. With ``wait=True`` the scheduler sleeps out the cooldown (never
        for a human-gated session: that always raises).
        """
        self.cadence(platform)
        platform = str(platform)
        now = self._now()
        state = self._roll_day(platform, now)
        if state.requires_human:
            raise PlatformCooling(platform, float("inf"), state.cooldown_reason or "session_requires_human")
        cadence = self._cadences[platform]
        if cadence.daily_cap is not None and state.count >= cadence.daily_cap:
            raise PlatformCooling(platform, self._seconds_until_next_day(now), "daily_cap")
        wait_seconds = max(0.0, state.next_at - now)
        if wait_seconds > 0:
            if not wait:
                raise PlatformCooling(platform, wait_seconds, state.cooldown_reason or "min_interval")
            self._sleep(wait_seconds)
        self.record_hit(platform)
        return round(wait_seconds, 3)

    def record_hit(self, platform: str, records: int = 1) -> None:
        """Record one round of collection (advances the platform's next slot)."""
        cadence = self.cadence(platform)
        state = self._roll_day(str(platform), self._now())
        state.next_at = max(state.next_at, self._now()) + max(0.0, cadence.min_interval)
        state.count += max(1, int(records))
        state.attempt = 0
        state.cooldown_reason = ""

    def record_error(
        self,
        platform: str,
        status: int,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Apply the classified backoff to the platform's rotation slot."""
        self.cadence(platform)
        platform = str(platform)
        now = self._now()
        state = self._roll_day(platform, now)
        decision = common.classify_backoff(status, headers, attempt=state.attempt, now=now)
        state.attempt += 1
        if decision["action"] == "stop":
            state.requires_human = True
            state.cooldown_reason = "permanent"
            state.next_at = float("inf")
            return {**decision, "platform": platform, "requires_human": True}
        wait = float(decision["wait_seconds"])
        state.next_at = max(state.next_at, now + wait)
        state.cooldown_reason = str(decision["reason"])
        return {
            **decision,
            "platform": platform,
            "next_ready_in": round(max(0.0, state.next_at - now), 3),
            "requires_human": False,
        }

    def record_success(self, platform: str, records: int = 1) -> None:
        """A healthy round clears the backoff attempt counter."""
        self.record_hit(platform, records=records)

    def record_session_drop(self, platform: str, *, cooldown_seconds: Optional[float] = None) -> None:
        """A dropped login session cools the platform until a human re-logs in."""
        self.cadence(platform)
        state = self._roll_day(str(platform), self._now())
        state.requires_human = True
        state.cooldown_reason = "session_drop"
        state.next_at = self._now() + float(
            self._session_cooldown if cooldown_seconds is None else cooldown_seconds
        )

    def record_human_relogin(self, platform: str) -> None:
        """The human re-authenticated: clear the session gate and resume."""
        self.cadence(platform)
        state = self._roll_day(str(platform), self._now())
        state.requires_human = False
        state.cooldown_reason = ""
        state.next_at = 0.0
        state.attempt = 0

    # -- persistence -------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "generated_at": common.utc_now_iso(),
            "platforms": {
                platform: {
                    # ``inf`` is not portable JSON: a human-gated platform
                    # stores None here and resumes as ``inf``.
                    "next_at": None if state.next_at == float("inf") else state.next_at,
                    "day": state.day,
                    "count": state.count,
                    "attempt": state.attempt,
                    "cooldown_reason": state.cooldown_reason,
                    "requires_human": state.requires_human,
                    "min_interval": self._cadences[platform].min_interval,
                    "daily_cap": self._cadences[platform].daily_cap,
                }
                for platform, state in self._state.items()
            },
        }

    def save(self, path: Path) -> None:
        common.atomic_write_json(Path(path), self.snapshot())

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        cadences: Optional[Iterable[Cadence]] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        account: str = "",
        policy_path: Optional[Path] = None,
    ) -> "RotationScheduler":
        """Resume a rotation from disk with the current persistent account policy."""
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
        platforms = snapshot.get("platforms") or {}
        if cadences is None:
            cadences = build_cadences(
                [str(platform) for platform in platforms],
                account=account, policy_path=policy_path,
            )
        scheduler = cls(cadences, clock=clock, sleep=sleep)
        for platform, saved in platforms.items():
            if platform not in scheduler._state:
                continue
            state = scheduler._state[platform]
            raw_next_at = saved.get("next_at")
            state.next_at = (
                float("inf") if raw_next_at is None and saved.get("requires_human")
                else float(raw_next_at or 0.0)
            )
            state.day = saved.get("day")
            state.count = int(saved.get("count") or 0)
            state.attempt = int(saved.get("attempt") or 0)
            state.cooldown_reason = str(saved.get("cooldown_reason") or "")
            state.requires_human = bool(saved.get("requires_human"))
        return scheduler


def _selftest() -> int:
    """Offline checks: cadence, rotation, backoff, session gate, persistence."""
    failures: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if not condition:
            failures.append(f"{name}: {detail}".rstrip(": "))

    now = [1000.0]
    scheduler = RotationScheduler(
        build_cadences(["reddit", "youtube", "discord"]),
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    # Fair rotation order starts with the fastest cadence, human-gated last.
    check("plan-order", scheduler.plan_round()[:2] == ["reddit", "youtube"], str(scheduler.plan_round()))

    # Per-site minimum interval: second hit waits, rotation to another site does not.
    scheduler.acquire("reddit")
    try:
        scheduler.acquire("reddit")
        check("min-interval", False, "expected PlatformCooling")
    except PlatformCooling as exc:
        check("min-interval", 0 < exc.wait_seconds <= 3.0, str(exc.wait_seconds))
    scheduler.acquire("youtube")

    # Rate-limit reset pushes the platform's next slot.
    decision = scheduler.record_error("reddit", 429, {"X-RateLimit-Reset": "60"})
    check("backoff-reset", decision["next_ready_in"] == 60.0, str(decision))
    check("backoff-wait", scheduler.seconds_until_ready("reddit") == 60.0, str(scheduler.seconds_until_ready("reddit")))

    # Permanent status gates the platform until a human intervenes.
    decision = scheduler.record_error("youtube", 404)
    check("permanent-gate", decision["requires_human"] and scheduler.next_platform() == "discord", str(decision))

    # Session drop: human re-login required; other platforms keep rotating.
    scheduler.record_session_drop("discord")
    check("session-gate", scheduler.seconds_until_ready("discord") == float("inf"), "discord should be human-gated")
    check("session-rotation", scheduler.next_platform() == "reddit", str(scheduler.next_platform()))
    scheduler.record_human_relogin("discord")
    check("relogin", scheduler.next_platform() == "discord", str(scheduler.next_platform()))

    # Daily cap: unavailable until tomorrow UTC.
    capped = RotationScheduler(
        [Cadence("vertical_forum", min_interval=0.0, daily_cap=1)],
        clock=lambda: now[0],
    )
    capped.acquire("vertical_forum")
    try:
        capped.acquire("vertical_forum")
        check("daily-cap", False, "expected PlatformCooling")
    except PlatformCooling as exc:
        check("daily-cap", exc.reason == "daily_cap" and exc.wait_seconds > 0, str(exc))

    # State round-trip resumes the rotation instead of re-hitting hot platforms.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rotation.json"
        snapshot = RotationScheduler(build_cadences(["reddit"]), clock=lambda: now[0])
        snapshot.acquire("reddit")
        snapshot.save(path)
        resumed = RotationScheduler.load(path, clock=lambda: now[0])
        check("resume", resumed.seconds_until_ready("reddit") > 0, str(resumed.snapshot()))

    # Duplicate platforms are refused: two cadences on one site double its rate.
    try:
        RotationScheduler([Cadence("x"), Cadence("x")])
        check("duplicate-platform", False, "expected ValueError")
    except ValueError:
        pass

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[ok] rotation selftest: fair round, per-site cadence, backoff, session gate, daily cap, resume")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Multi-platform rotation scheduler: per-site cadence, classified cooldown, "
        "session health, daily quota and resume. Rotation lowers per-site frequency; it never "
        "bypasses a platform limit.",
    )
    parser.add_argument("--plan", help="comma-separated platforms to order for one round")
    parser.add_argument("--state", type=Path, help="rotation state file to write after planning")
    parser.add_argument("--account", default="", help="account_id or handle for every selected platform")
    parser.add_argument("--account-policy", type=Path, help="persistent account-quotas.json path")
    parser.add_argument("--selftest", action="store_true", help="run the offline checks and exit")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.plan:
        parser.print_help()
        return 0
    platforms = [item.strip() for item in args.plan.split(",") if item.strip()]
    scheduler = RotationScheduler(build_cadences(
        platforms, account=args.account, policy_path=args.account_policy,
    ))
    plan = scheduler.plan_round()
    print(json.dumps({"round": plan, "cadences": {p: scheduler.cadence(p).__dict__ for p in plan}},
                     ensure_ascii=False, indent=2))
    if args.state:
        scheduler.save(args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

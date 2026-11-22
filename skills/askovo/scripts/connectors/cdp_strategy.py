#!/usr/bin/env python3
"""CDP strategy policy: the field-notes registry compiled into runtime guards.

The campaign's CDP strategies used to live in three separate places — prose in
the registry, helper functions nothing called, and hand-rolled loops in each
collector. This module is the one place where those invariants become
executable:

- **one goto per cell** — a second navigation in the same cell doubles what the
  site sees and tears the previous page's input stream;
- **timeout = circuit breaker** — a timeout or abort on a session platform is a
  stop signal, not a retry signal: the platform is left alone for the policy's
  cooldown (15 min on Discord, field-verified after three drops in one day);
- **session time-box** — a logged-in stretch is bounded (Discord: 40 min, then
  the human logs out deliberately); an idle-open webview session is not a
  standing channel;
- **mode exclusivity** — invite joins and channel crawling never share one
  session stretch; one run, one mode per platform;
- **budget headroom** — every cell budget is multiplied by the policy's
  fraction, so a timeout cannot tear an input event mid-dispatch;
- **blank-render triage** — HTTP 200 with an empty title and body is an
  unsupported rendering stack, not a challenge and not an empty corpus;
- **page triage** — challenge / not-found / blank / content is classified in
  one place so capture, collect and the collectors cannot disagree.

The policy numbers come from `assets/platform-field-notes.json`
(`runtime_policies`); nothing here authorizes access. The platform catalog,
study scope, Design gate, human ack and an approved URL still decide whether a
route may run. A blocked platform stays a recorded gap.

Standard library only; compatible with Python 3.9+.

Usage:
  python3 cdp_strategy.py --help
  python3 cdp_strategy.py --policy discord    # print the enforced policy
  python3 cdp_strategy.py --selftest          # offline guard checks
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent.parent
REGISTRY_PATH = SKILL_ROOT / "assets" / "platform-field-notes.json"

try:  # imported as a package (`from connectors import cdp_strategy`)
    from . import common  # type: ignore
except ImportError:  # imported as a top-level module from the connectors directory
    try:
        import common  # type: ignore
    except ImportError:  # loaded by path from the engine (no connectors dir on sys.path)
        import importlib.util

        _common_spec = importlib.util.spec_from_file_location("askovo_cdp_common", HERE / "common.py")
        if _common_spec is None or _common_spec.loader is None:  # pragma: no cover
            raise
        common = importlib.util.module_from_spec(_common_spec)
        _common_spec.loader.exec_module(common)

SCHEMA_VERSION = "askovo.cdp-session/1"
POLICY_KEYS = (
    "cadence_seconds",
    "session_minutes",
    "session_cooldown_minutes",
    "timeout_cooldown_minutes",
    "max_gotos_per_cell",
    "budget_fraction",
    "allow_reload",
    "exclusive_modes",
    "requires_session",
    "challenge_policy",
    "blank_render_status",
)
CHALLENGE_POLICY = "passive_wait_only"
BLANK_RENDER_STATUS = "unsupported_stack"

# Page-state markers shared by capture, collect and the collectors. Titles only
# for not-found: product reviews legitimately mention "not found" in the body.
# Body markers are narrow on purpose: a product review can say "just a
# moment" without the page being a challenge. Cloudflare-style interstitials
# are recognised by their title, so a normal article keeps its content verdict.
CHALLENGE_TEXT = re.compile(
    r"Robot Check|Enter the characters|验证码|异常流量|not a robot",
    re.I,
)
CHALLENGE_TITLE = re.compile(
    r"just a moment|attention required|checking your browser|verify you are human|"
    r"access denied|cloudflare",
    re.I,
)
NOT_FOUND_TITLE_MARKERS = (
    "not found",
    "doesn't exist",
    "does not exist",
    "页面不存在",
    "页面未找到",
    "未找到页面",
    "找不到",
)
_NOT_FOUND_404 = re.compile(r"(?<![0-9a-z])404(?![0-9a-z])", re.I)
MEMBERSHIP_GATE_TEXT = re.compile(
    r"must be a member|members only|member(?:ship)? (?:verification|required)|"
    r"verify (?:your account )?to (?:view|access|join)|verification required|"
    r"only members can|join (?:the|this) server to (?:view|see)|"
    r"you do not have permission to view|"
    r"仅会员|会员可见|需要加入服务器|验证后查看|加入服务器后查看",
    re.I,
)
_LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|auth)(?:/|$)", re.I)
_LOGIN_TEXT = (
    "log in to discord",
    "you need to log in",
    "please log in to continue",
    "session expired",
    "请先登录",
    "登录后继续",
    "会话已失效",
)


# Python 3.9 keeps `socket.timeout` outside the builtin TimeoutError hierarchy
# (it becomes an alias on 3.10+); both mean the same torn cell here.
TIMEOUT_ERRORS: Tuple[type, ...] = (TimeoutError, socket.timeout)


class PolicyError(ValueError):
    """The registry's runtime policy is missing or malformed."""


class CircuitOpen(RuntimeError):
    """The platform is cooling down after a timeout/drop; stop touching it."""

    def __init__(self, platform: str, retry_after_seconds: float, reason: str = "") -> None:
        self.platform = platform
        self.retry_after_seconds = float(retry_after_seconds)
        self.reason = reason or "cooldown"
        super().__init__(
            f"{platform} circuit open for {self.retry_after_seconds:.0f}s ({self.reason}); "
            "a timeout is a stop signal — do not retry, do not snapshot, do not diagnose"
        )


class SessionExpired(RuntimeError):
    """The session time-box elapsed; collect nothing more in this stretch."""


class CellViolation(RuntimeError):
    """The cell broke a frequency invariant (second goto, reload, mixed mode)."""


@dataclass(frozen=True)
class RuntimePolicy:
    """Per-platform budgets derived from the registry's runtime_policies."""

    platform: str
    cadence_seconds: float = 3.0
    session_minutes: float = 60.0
    session_cooldown_minutes: float = 30.0
    timeout_cooldown_minutes: float = 15.0
    max_gotos_per_cell: int = 1
    budget_fraction: float = 0.7
    allow_reload: bool = False
    exclusive_modes: Tuple[str, ...] = ("collect",)
    requires_session: bool = False
    challenge_policy: str = CHALLENGE_POLICY
    blank_render_status: str = BLANK_RENDER_STATUS
    collection_stop_rules: Tuple[str, ...] = ()
    source: str = "registry"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "cadence_seconds": self.cadence_seconds,
            "session_minutes": self.session_minutes,
            "session_cooldown_minutes": self.session_cooldown_minutes,
            "timeout_cooldown_minutes": self.timeout_cooldown_minutes,
            "max_gotos_per_cell": self.max_gotos_per_cell,
            "budget_fraction": self.budget_fraction,
            "allow_reload": self.allow_reload,
            "exclusive_modes": list(self.exclusive_modes),
            "requires_session": self.requires_session,
            "challenge_policy": self.challenge_policy,
            "blank_render_status": self.blank_render_status,
            "collection_stop_rules": list(self.collection_stop_rules),
            "source": self.source,
        }

    def effective_budget(self, cap_seconds: float) -> float:
        """A cap reduced by the policy's headroom fraction (never above the cap)."""
        return round(max(0.0, float(cap_seconds)) * self.budget_fraction, 3)


_CACHE: Dict[str, Tuple[float, Mapping[str, Any]]] = {}


def load_runtime_policies(path: Optional[Path] = None) -> Mapping[str, Any]:
    """Load and cache the registry's ``runtime_policies`` section.

    Raises :class:`PolicyError` when the registry is missing or the section is
    malformed: a broken policy file must be loud, not silently replaced by
    guesses (the whole point is that runtime budgets come from the field data).
    """
    registry = Path(path or REGISTRY_PATH)
    try:
        mtime = registry.stat().st_mtime
    except OSError as exc:
        raise PolicyError(f"cannot read platform field notes: {registry} ({exc})") from exc
    cached = _CACHE.get(str(registry))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"invalid platform field notes: {registry} ({exc})") from exc
    section = data.get("runtime_policies") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        raise PolicyError(f"{registry} has no runtime_policies object")
    problems = policy_problems(section)
    if problems:
        raise PolicyError("; ".join(problems[:5]))
    _CACHE[str(registry)] = (mtime, section)
    return section


def clear_cache() -> None:
    """Drop the cached registry section (tests that rewrite the file use this)."""
    _CACHE.clear()


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _policy_value_problems(name: str, values: Mapping[str, Any]) -> List[str]:
    problems: List[str] = []
    if not _number(values.get("cadence_seconds")) or values["cadence_seconds"] < 0:
        problems.append(f"{name}: cadence_seconds must be a number >= 0")
    if not _number(values.get("session_minutes")) or values["session_minutes"] <= 0:
        problems.append(f"{name}: session_minutes must be a number > 0")
    if not _number(values.get("session_cooldown_minutes")) or values["session_cooldown_minutes"] <= 0:
        problems.append(f"{name}: session_cooldown_minutes must be a number > 0")
    if not _number(values.get("timeout_cooldown_minutes")) or values["timeout_cooldown_minutes"] <= 0:
        problems.append(f"{name}: timeout_cooldown_minutes must be a number > 0")
    gotos = values.get("max_gotos_per_cell")
    if not isinstance(gotos, int) or isinstance(gotos, bool) or gotos < 1:
        problems.append(f"{name}: max_gotos_per_cell must be an integer >= 1")
    fraction = values.get("budget_fraction")
    if not _number(fraction) or not 0 < fraction <= 1:
        problems.append(f"{name}: budget_fraction must be a number in (0, 1]")
    if not isinstance(values.get("allow_reload"), bool):
        problems.append(f"{name}: allow_reload must be a boolean")
    modes = values.get("exclusive_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(not isinstance(item, str) or not item.strip() for item in modes)
    ):
        problems.append(f"{name}: exclusive_modes must be a non-empty list of strings")
    if not isinstance(values.get("requires_session"), bool):
        problems.append(f"{name}: requires_session must be a boolean")
    if values.get("challenge_policy") != CHALLENGE_POLICY:
        problems.append(f"{name}: challenge_policy must be {CHALLENGE_POLICY!r}")
    if values.get("blank_render_status") != BLANK_RENDER_STATUS:
        problems.append(f"{name}: blank_render_status must be {BLANK_RENDER_STATUS!r}")
    return problems


def policy_problems(section: Optional[Mapping[str, Any]] = None,
                    known_platforms: Optional[Sequence[str]] = None) -> List[str]:
    """Structural problems in the runtime-policy section (empty means consistent)."""
    if section is None:
        try:
            section = load_runtime_policies()
        except PolicyError as exc:
            return [str(exc)]
    problems: List[str] = []
    if not isinstance(section, dict):
        return ["runtime_policies must be an object"]
    guards = section.get("guards")
    if not isinstance(guards, dict) or not guards:
        problems.append("runtime_policies.guards must be a non-empty object")
        guards = {}
    for strategy_id, helper in guards.items():
        if not isinstance(helper, str) or not helper.strip():
            problems.append(f"runtime_policies.guards[{strategy_id!r}] must be a helper string")
    defaults = section.get("defaults")
    if not isinstance(defaults, dict):
        problems.append("runtime_policies.defaults must be an object")
        return problems
    missing = [key for key in POLICY_KEYS if key not in defaults]
    if missing:
        problems.append(f"runtime_policies.defaults missing {', '.join(missing)}")
    problems.extend(_policy_value_problems("runtime_policies.defaults", defaults))
    extra = sorted(set(defaults) - set(POLICY_KEYS))
    if extra:
        problems.append(f"runtime_policies.defaults has unknown keys: {', '.join(extra)}")
    platforms = section.get("platforms")
    if not isinstance(platforms, dict):
        problems.append("runtime_policies.platforms must be an object")
        return problems
    allowed = set(known_platforms) if known_platforms is not None else None
    for platform, override in platforms.items():
        if not isinstance(platform, str) or not platform.strip():
            problems.append("runtime_policies.platforms has a non-string key")
            continue
        if allowed is not None and platform not in allowed:
            problems.append(f"runtime_policies.platforms[{platform!r}] is not a catalog platform or source type")
        if not isinstance(override, dict):
            problems.append(f"runtime_policies.platforms[{platform!r}] must be an object")
            continue
        unknown = sorted(set(override) - set(POLICY_KEYS))
        if unknown:
            problems.append(f"runtime_policies.platforms[{platform!r}] has unknown keys: {', '.join(unknown)}")
        merged = dict(defaults)
        merged.update(override)
        problems.extend(_policy_value_problems(f"runtime_policies.platforms[{platform!r}]", merged))
    return problems


def build_policy(platform: str, section: Optional[Mapping[str, Any]] = None) -> RuntimePolicy:
    """Merge defaults and a platform override into a validated policy."""
    section = load_runtime_policies() if section is None else section
    problems = policy_problems(section)
    if problems:
        raise PolicyError("; ".join(problems[:5]))
    name = str(platform)
    merged: Dict[str, Any] = dict(section["defaults"])  # type: ignore[arg-type]
    override = (section.get("platforms") or {}).get(name)
    if isinstance(override, dict):
        merged.update(override)
    unknown = sorted(set(merged) - set(POLICY_KEYS))
    if unknown:
        raise PolicyError(f"{name}: unknown policy keys {', '.join(unknown)}")
    merged["exclusive_modes"] = tuple(str(mode) for mode in merged["exclusive_modes"])
    return RuntimePolicy(platform=name, **merged)


def policy_for(platform: str, section: Optional[Mapping[str, Any]] = None) -> RuntimePolicy:
    """Merge runtime defaults with a collection policy, only in the stricter direction."""
    base = build_policy(platform, section)
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        entry = (registry.get("collection_policies") or {}).get("platforms", {}).get(str(platform))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read collection policy for {platform}: {exc}") from exc
    if entry is None:
        return base
    budget = entry.get("budget") if isinstance(entry, dict) else None
    stop_rules = entry.get("stop_rules") if isinstance(entry, dict) else None
    if not isinstance(budget, dict) or not isinstance(stop_rules, list) or not all(
            isinstance(rule, str) for rule in stop_rules):
        raise PolicyError(f"{platform}: malformed collection policy")
    if not all(_number(budget.get(key)) for key in
               ("cadence_seconds", "session_minutes", "budget_fraction")):
        raise PolicyError(f"{platform}: collection budget must contain numeric limits")
    return replace(
        base,
        cadence_seconds=max(base.cadence_seconds, float(budget["cadence_seconds"])),
        session_minutes=min(base.session_minutes, float(budget["session_minutes"])),
        budget_fraction=min(base.budget_fraction, float(budget["budget_fraction"])),
        collection_stop_rules=tuple(stop_rules),
        source=base.source + "+collection_policy",
    )


def effective_budget(cap_seconds: float, platform: str = "*",
                     section: Optional[Mapping[str, Any]] = None) -> float:
    """Cap seconds reduced by the platform's headroom fraction."""
    return policy_for(platform, section).effective_budget(cap_seconds)


# ---------------------------------------------------------------------------
# Page triage


def title_reports_not_found(title: str) -> bool:
    lowered = str(title or "").lower()
    if any(marker in lowered for marker in NOT_FOUND_TITLE_MARKERS):
        return True
    return bool(_NOT_FOUND_404.search(str(title or "")))


def is_blank_render(title: str, text: str) -> bool:
    """200 + empty title + empty body = an unsupported stack, not an empty page."""
    return not str(title or "").strip() and not str(text or "").strip()


def classify_page(title: str, text: str) -> str:
    """One page verdict shared by capture, collect and the collectors.

    Returns ``challenge`` | ``page_not_found`` | ``blank_render`` | ``content``.
    The caller decides what to do: wait passively, stop, mark unsupported or
    continue. Classification never bypasses anything.
    """
    if CHALLENGE_TEXT.search(str(text or "")) or CHALLENGE_TITLE.search(str(title or "")):
        return "challenge"
    if title_reports_not_found(title):
        return "page_not_found"
    if is_blank_render(title, text):
        return "blank_render"
    return "content"


def detect_membership_gate(text: str) -> bool:
    """A membership-verification gate, not a broken selector or a login page.

    Only trust this after extraction returned zero and the page is not blank or
    logged out: a normal post can discuss "membership" without gating history.
    The gate is a coverage gap, never something to work around.
    """
    return bool(MEMBERSHIP_GATE_TEXT.search(str(text or "")))


def looks_logged_out(url: str, text: str = "") -> bool:
    """Cheap login-page detector; only trust it when extraction already returned zero."""
    parsed = str(url or "")
    if _LOGIN_PATH.search(parsed.split("?", 1)[0]):
        return True
    lowered = str(text or "").casefold()
    return any(marker in lowered for marker in _LOGIN_TEXT)


# ---------------------------------------------------------------------------
# Failure classification


def classify_failure(exc: BaseException, *, platform: Optional[str] = None,
                     policy: Optional[RuntimePolicy] = None) -> Dict[str, Any]:
    """Map a collector failure to the strategy action.

    ``circuit_break`` — leave the platform alone for the cooldown (timeout/abort);
    ``human_required`` — a challenge page or a dropped login session;
    ``cooldown`` — the circuit is already open;
    ``stop`` — anything else: stop the cell, keep the harvest, do not retry.
    """
    policy = policy or (policy_for(platform) if platform else None)
    cooldown = policy.timeout_cooldown_minutes * 60 if policy else 900.0
    name = type(exc).__name__
    if isinstance(exc, TIMEOUT_ERRORS) or name in {"CDPTimeout", "Timeout"}:
        return {
            "action": "circuit_break",
            "reason": "timeout_abort",
            "platform": platform,
            "cooldown_seconds": cooldown,
            "message": (
                "a timeout/abort tears the input stream; stop touching the platform for "
                f"{cooldown / 60:.0f} min, then verify the session before the next run"
            ),
        }
    if name in {"ChallengeStopped", "ChallengePage"}:
        return {
            "action": "human_required",
            "reason": "challenge_page",
            "platform": platform,
            "message": "a challenge needs a human in the same browser; never solve, spoof or reload around it",
        }
    if name in {"SessionExpired"}:
        return {
            "action": "stop",
            "reason": "session_time_box",
            "platform": platform,
            "message": "the session time-box elapsed; log out deliberately and resume in a fresh stretch",
        }
    if name in {"CircuitOpen"}:
        return {
            "action": "cooldown",
            "reason": "circuit_open",
            "platform": platform,
            "message": "the platform is cooling down; rotate to another platform instead of retrying",
        }
    return {
        "action": "stop",
        "reason": (name or "collector_error").lower(),
        "platform": platform,
        "message": "stop the cell, persist what was harvested, and diagnose before the next run",
    }


# ---------------------------------------------------------------------------
# Session guard


class SessionGuard:
    """Enforce one platform's runtime policy for one collection stretch.

    The guard is deliberately small and pure: it owns no browser connection.
    A collector wraps one cell (navigate→verify→collect) in
    :meth:`begin_cell` / :meth:`end_cell`, calls :meth:`navigate` once, and
    records timeouts; the journal is the run's audit trail.
    """

    def __init__(
        self,
        platform: str,
        *,
        policy: Optional[RuntimePolicy] = None,
        section: Optional[Mapping[str, Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        state_path: Optional[Path] = None,
    ) -> None:
        self.platform = str(platform)
        self.policy = policy or policy_for(self.platform, section)
        self._clock = clock
        self._wall_clock = wall_clock
        self.state_path = Path(state_path) if state_path else None
        self._started = float(clock())
        self._started_wall = float(wall_clock())
        self._cell: Optional[Dict[str, Any]] = None
        self._cells: List[Dict[str, Any]] = []
        self._timeouts: List[Dict[str, Any]] = []
        self._modes: List[str] = []
        self._circuit_until = 0.0
        self._circuit_reason = ""
        self._stopped = ""

    # -- budget / clocks ---------------------------------------------------
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started)

    def remaining_session_seconds(self) -> float:
        return max(0.0, self.policy.session_minutes * 60.0 - self.elapsed_seconds())

    def session_expired(self) -> bool:
        return self.remaining_session_seconds() <= 0

    def cell_budget(self, cap_seconds: float) -> float:
        """A cell's cap with the policy's headroom applied."""
        return self.policy.effective_budget(cap_seconds)

    # -- gates -------------------------------------------------------------
    def check_session(self) -> None:
        if self.session_expired():
            raise SessionExpired(
                f"{self.platform}: session time-box of {self.policy.session_minutes:.0f} min "
                "reached; stop, persist, log out deliberately and resume in a fresh stretch"
            )

    def check_circuit(self) -> None:
        remaining = self._circuit_until - self._clock()
        if remaining > 0:
            raise CircuitOpen(self.platform, remaining, self._circuit_reason)

    def check(self) -> None:
        self.check_circuit()
        self.check_session()

    def circuit(self) -> Dict[str, Any]:
        remaining = max(0.0, self._circuit_until - self._clock())
        return {
            "open": remaining > 0,
            "reason": self._circuit_reason,
            "retry_after_seconds": round(remaining, 3),
        }

    # -- cells -------------------------------------------------------------
    def begin_cell(self, kind: str = "collect") -> Dict[str, Any]:
        """Open one cell; enforces circuit, time-box, mode exclusivity, one cell."""
        self.check()
        mode = str(kind or "collect")
        if mode in self.policy.exclusive_modes and self._modes and mode not in self._modes:
            raise CellViolation(
                f"{self.platform}: never mix {self._modes[-1]!r} and {mode!r} in one session "
                "stretch; finish the mode, log out, start a fresh stretch"
            )
        if self._cell is not None:
            raise CellViolation(
                f"{self.platform}: cell {self._cell['kind']!r} is still open; one cell at a "
                "time — a second goto would double what the site sees"
            )
        if mode not in self._modes:
            self._modes.append(mode)
        self._cell = {"kind": mode, "gotos": 0, "started_at": self._wall_iso()}
        return self._cell

    def navigate(self) -> None:
        """Count one goto; a second goto in the same cell is refused."""
        if self._cell is None:
            raise CellViolation(f"{self.platform}: navigate() outside a cell; begin_cell first")
        self._cell["gotos"] += 1
        if self._cell["gotos"] > self.policy.max_gotos_per_cell:
            raise CellViolation(
                f"{self.platform}: {self._cell['gotos']} gotos in one cell "
                f"(max {self.policy.max_gotos_per_cell}); navigate→verify→collect in one cell"
            )

    def reload(self) -> None:
        """Reload is refused by default (it re-requests the page and re-arms risk control)."""
        if not self.policy.allow_reload:
            raise CellViolation(
                f"{self.platform}: reload() is forbidden by policy; re-bind the tab or open a "
                "fresh page in a new cell"
            )
        self.navigate()

    def end_cell(self, result: str = "ok") -> None:
        if self._cell is None:
            return
        self._cell.update({"ended_at": self._wall_iso(), "result": str(result)})
        self._cells.append(self._cell)
        self._cell = None

    # -- recording ---------------------------------------------------------
    def record_timeout(self, detail: str = "") -> Dict[str, Any]:
        """A timeout opens the circuit for the policy's cooldown."""
        cooldown = self.policy.timeout_cooldown_minutes * 60.0
        self._circuit_until = max(self._circuit_until, self._clock() + cooldown)
        self._circuit_reason = "timeout_abort"
        event = {
            "at": self._wall_iso(),
            "detail": str(detail)[:300],
            "cooldown_seconds": round(cooldown, 3),
            "retry_after": datetime.fromtimestamp(
                self._wall_clock() + cooldown, tz=timezone.utc
            ).isoformat(),
        }
        self._timeouts.append(event)
        return event

    def record_session_drop(self, detail: str = "") -> Dict[str, Any]:
        """A dropped login session ends the stretch; only a human re-authenticates."""
        cooldown = self.policy.session_cooldown_minutes * 60.0
        self._circuit_until = max(self._circuit_until, self._clock() + cooldown)
        self._circuit_reason = "session_drop"
        self._stopped = "session_drop"
        event = {
            "at": self._wall_iso(),
            "detail": str(detail)[:300],
            "cooldown_seconds": round(cooldown, 3),
            "human_relogin_required": True,
        }
        self._timeouts.append(event)
        return event

    def record_failure(self, exc: BaseException, detail: str = "") -> Dict[str, Any]:
        """Classify a failure and record its consequence on the guard."""
        decision = classify_failure(exc, platform=self.platform, policy=self.policy)
        if decision["action"] == "circuit_break":
            self.record_timeout(detail or decision["reason"])
        elif decision["action"] == "human_required":
            self.record_session_drop(detail or decision["reason"])
        else:
            self._stopped = str(decision["reason"])
        return decision

    def record_stop(self, reason: str) -> None:
        self._stopped = str(reason)

    # -- journal -----------------------------------------------------------
    def _wall_iso(self) -> str:
        return datetime.fromtimestamp(self._wall_clock(), tz=timezone.utc).isoformat()

    def journal(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "platform": self.platform,
            "generated_at": common.utc_now_iso(),
            "started_at": datetime.fromtimestamp(self._started_wall, tz=timezone.utc).isoformat(),
            "policy": self.policy.to_dict(),
            "session": {
                "time_box_seconds": round(self.policy.session_minutes * 60.0, 3),
                "elapsed_seconds": round(self.elapsed_seconds(), 3),
                "remaining_seconds": round(self.remaining_session_seconds(), 3),
                "expired": self.session_expired(),
            },
            "circuit": self.circuit(),
            "cells": list(self._cells),
            "timeouts": list(self._timeouts),
            "modes": list(self._modes),
            "stopped": self._stopped,
        }

    def save(self, path: Optional[Path] = None) -> Path:
        target = Path(path) if path else self.state_path
        if target is None:
            raise ValueError("SessionGuard.save needs a path (pass state_path at construction)")
        common.atomic_write_json(target, self.journal())
        return target


def _selftest() -> int:
    """Offline checks: policy derivation, page triage, cell and session guards."""
    failures: List[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if not condition:
            failures.append(f"{name}: {detail}".rstrip(": "))

    # Policies come from the registry, not from a second copy in code.
    discord = policy_for("discord")
    check("policy-discord", discord.cadence_seconds == 20.0 and discord.session_minutes == 40.0,
          str(discord.to_dict()))
    check("policy-headroom", discord.effective_budget(60.0) == 36.0, str(discord.effective_budget(60.0)))
    unknown = policy_for("some_new_site")
    check("policy-defaults", unknown.max_gotos_per_cell == 1 and unknown.budget_fraction == 0.7,
          str(unknown.to_dict()))

    # Page triage: challenge, 404 title, blank 200, content.
    check("page-challenge", classify_page("Just a moment...", "Just a moment...") == "challenge")
    check("page-404", classify_page("Page not found", "whatever") == "page_not_found")
    check("page-blank", classify_page("", "") == "blank_render")
    check("page-content", classify_page("Reviews", "a real review body") == "content")
    check("gate-detected", detect_membership_gate("You must be a member of this server to view this channel"))
    check("gate-detected-zh", detect_membership_gate("仅会员可查看该频道"))
    check("gate-negative", not detect_membership_gate("membership has grown steadily this year"))

    now = [1000.0]
    guard = SessionGuard("discord", clock=lambda: now[0], wall_clock=lambda: now[0])
    cell = guard.begin_cell("messages")
    check("cell-open", cell["kind"] == "messages" and cell["gotos"] == 0, str(cell))
    guard.navigate()
    try:
        guard.navigate()
        check("one-goto", False, "expected CellViolation on the second goto")
    except CellViolation:
        pass
    try:
        guard.begin_cell("forum")
        check("mode-exclusive", False, "expected CellViolation for a mixed mode")
    except CellViolation:
        pass
    guard.end_cell("ok")
    guard.begin_cell("messages")  # another cell in the same mode is fine
    guard.end_cell("ok")

    # Timeout = circuit breaker: 15 minutes of no contact, then the session resumes.
    guard.record_timeout("cuaScroll timeout")
    try:
        guard.check()
        check("circuit-open", False, "expected CircuitOpen after a timeout")
    except CircuitOpen:
        pass
    now[0] += 16 * 60
    guard.check()
    check("circuit-clear", not guard.circuit()["open"], str(guard.circuit()))

    # Session time-box: 40 minutes for Discord.
    now[0] += 45 * 60
    try:
        guard.check_session()
        check("session-expired", False, "expected SessionExpired")
    except SessionExpired:
        pass

    # Reload is refused unless a policy allows it.
    reload_guard = SessionGuard("discord", clock=lambda: 5000.0, wall_clock=lambda: 5000.0)
    try:
        reload_guard.reload()
        check("reload", False, "expected CellViolation for reload()")
    except CellViolation:
        pass

    # Journal round-trip.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session.json"
        guard.save(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        check("journal", payload["platform"] == "discord" and payload["policy"]["session_minutes"] == 40.0,
              str(payload)[:200])

    # Malformed policy is refused, not guessed around.
    broken = {
        "guards": {"session-health-cooldown": "connectors.cdp_strategy.SessionGuard"},
        "defaults": dict(policy_for("discord").to_dict(), budget_fraction=1.5),
        "platforms": {},
    }
    check("policy-validation", bool(policy_problems(broken)), str(policy_problems(broken)))

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    print("[ok] cdp_strategy selftest: policy, triage, gate, one goto/cell, circuit, time-box, reload, journal")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CDP strategy policy: per-platform runtime budgets, page triage and the "
        "session guard (one goto per cell, timeout circuit breaker, session time-box). "
        "No credentials, no challenge bypass.",
    )
    parser.add_argument("--policy", help="print the enforced policy for one platform")
    parser.add_argument("--selftest", action="store_true", help="run the offline guard checks and exit")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.policy:
        print(json.dumps(policy_for(args.policy).to_dict(), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

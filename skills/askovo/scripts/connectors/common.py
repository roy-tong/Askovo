"""Shared collection helpers: schema, quality flags, pseudonymisation, JSONL IO.

Collected from the Tiiny user-research project (scripts/common.py), which had
the most mature normalisation schema and quality scoring of the collected
families. Project-specific parts were removed during collection (see
connectors/README.md):

- the fixed project root and `config/queries.json` loader became an explicit
  `load_json_config(path)`;
- the hardcoded User-Agent, author salt, and primary-window timestamp moved to
  `configure()` / per-call arguments (a study must state its own identity);
- the local-LLM topic lexicon (TOPIC_TERMS, topic_relevance_score,
  infer_sample_bucket) was dropped: it encodes one project's domain, not a
  reusable rule.

Standard library only; compatible with Python 3.9+.
"""
from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

USER_AGENT = "askovo-connector/1.0 (configure per study)"
AUTHOR_SALT: Optional[str] = None
PRIMARY_AFTER_UTC: Optional[int] = None

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def configure(
    user_agent: Optional[str] = None,
    author_salt: Optional[str] = None,
    primary_after_utc: Optional[int] = None,
) -> None:
    """Set the study identity once; collectors call this from their CLI args."""
    global USER_AGENT, AUTHOR_SALT, PRIMARY_AFTER_UTC
    if user_agent:
        USER_AGENT = user_agent
    AUTHOR_SALT = author_salt
    PRIMARY_AFTER_UTC = primary_after_utc


def load_json_config(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def request_json(url: str, *, timeout: int = 30, retries: int = 3, user_agent: Optional[str] = None) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    safe_url = url.split("?", 1)[0]
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
                if len(payload) > 16 * 1024 * 1024:
                    raise RuntimeError("JSON response exceeds 16 MiB limit")
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            decision = classify_backoff(exc.code, dict(exc.headers or {}), attempt)
            if decision["action"] == "stop" or attempt + 1 >= retries:
                break
            time.sleep(float(decision["wait_seconds"]))
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {safe_url}") from last_error


def build_url(base: str, params: Dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return base + "?" + urllib.parse.urlencode(clean)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]], *, append: bool = True) -> int:
    ensure_parent(path)
    mode = "a" if append else "w"
    count = 0
    with path.open(mode, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def author_hash(author: str | None, salt: Optional[str] = None) -> Optional[str]:
    if not author:
        return None
    normalized = author.strip().lower()
    if normalized in {"[deleted]", "deleted", "none", "unknown"}:
        return None
    effective = AUTHOR_SALT if salt is None else salt
    material = f"{effective}:{normalized}" if effective else normalized
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest[:24]


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = text.replace("\u0000", " ")
    return WS_RE.sub(" ", text).strip()


def stable_text_hash(text: str | None) -> Optional[str]:
    cleaned = clean_text(text).lower()
    if not cleaned:
        return None
    cleaned = re.sub(r"https?://\S+", " URL ", cleaned)
    cleaned = re.sub(r"\W+", " ", cleaned)
    cleaned = WS_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]


def utc_from_timestamp(ts: int | float | str | None) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def timestamp_from_iso(value: str | None) -> Optional[float]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    match = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d{1,6})(.*)$", text)
    if match:
        frac = match.group(2).ljust(6, "0")
        text = f"{match.group(1)}.{frac}{match.group(3)}"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def is_primary_date(value: str | None, after_utc: Optional[int] = None) -> bool:
    """True when the record falls inside the configured primary window.

    With no window configured every date counts as primary; a study narrows
    this via configure(primary_after_utc=...) or --primary-after-utc.
    """
    threshold = PRIMARY_AFTER_UTC if after_utc is None else after_utc
    if threshold is None:
        return True
    ts = timestamp_from_iso(value)
    return ts is not None and ts >= threshold


def month_bucket(value: str | None) -> Optional[str]:
    ts = timestamp_from_iso(value)
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def base_quality_flags(text: str, created_at: str | None, primary_after_utc: Optional[int] = None) -> List[str]:
    flags: List[str] = []
    low = (text or "").strip().lower()
    if len(low) < 40:
        flags.append("too_short")
    if low in {"[deleted]", "[removed]", "deleted", "removed"}:
        flags.append("removed_or_deleted")
    threshold = PRIMARY_AFTER_UTC if primary_after_utc is None else primary_after_utc
    if threshold is not None:
        if created_at and not is_primary_date(created_at, threshold):
            flags.append("outside_primary_window")
    if not created_at:
        flags.append("missing_created_at")
    if re.search(r"\b(as an ai language model|i cannot browse|chatgpt can)\b", low):
        flags.append("possible_ai_generated_meta")
    if any(
        phrase in low
        for phrase in [
            "i am a bot, and this action was performed automatically",
            "action was performed automatically",
            "please contact the moderators of this subreddit",
            "if you have any questions or concerns",
            "please reply to this message with the conversation link",
            "post screenshot chatgpt conversation",
            "consider joining our public discord server",
        ]
    ):
        flags.append("moderator_or_bot_template")
    if re.search(r"\b([a-z]{2,20})(?:\s+\1){2,}\b", low):
        flags.append("repetitive_low_signal")
    return flags


def quality_score(text: str, flags: List[str], score: int | float | None = None) -> float:
    value = 1.0
    if "too_short" in flags:
        value -= 0.35
    if "removed_or_deleted" in flags:
        value -= 0.7
    if "outside_primary_window" in flags:
        value -= 0.8
    if "missing_created_at" in flags:
        value -= 0.25
    if "possible_ai_generated_meta" in flags:
        value -= 0.2
    if "moderator_or_bot_template" in flags:
        value -= 0.85
    if "repetitive_low_signal" in flags:
        value -= 0.7
    if len(text) > 200:
        value += 0.05
    if score is not None:
        try:
            if float(score) < 0:
                value -= 0.05
        except (TypeError, ValueError):
            pass
    return max(0.0, min(1.0, round(value, 3)))


def unique_by_record_id(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        rid = row.get("record_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Operational guards: classified backoff, single-writer state, relative time
#
# Collected from the golf-device campaign (2026-11), where multi-hour runs kept
# rediscovering the same failures. These are the reusable rules; the field
# narrative lives in skills/askovo/references/platform-field-notes.md and the
# engine exposes the same registry as data (assets/platform-field-notes.json).

RATE_LIMIT_HEADERS = ("X-RateLimit-Reset", "x-ratelimit-reset", "Retry-After", "retry-after")
PERMANENT_STATUSES = frozenset({400, 401, 404, 410, 451})
SUCCESS_STATUSES = frozenset({200, 201, 202, 204})


class SingleWriterError(RuntimeError):
    """Another live process is collecting into the same state file."""


def _header_value(headers: Optional[Dict[str, str]], names: Iterable[str]) -> Optional[str]:
    if not headers:
        return None
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return str(value)
    return None


def _reset_wait_seconds(headers: Optional[Dict[str, str]], now: float) -> Optional[float]:
    """Seconds to wait from a rate-limit header, accepting epoch or delta values."""
    raw = _header_value(headers, RATE_LIMIT_HEADERS)
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return 0.0
    # Epoch seconds (2026+) vs a relative delta: anything above 10^8 is a clock.
    return max(0.0, value - now) if value > 1e8 else value


def _exponential_wait(attempt: int, base: float, max_wait: float) -> float:
    return min(max_wait, base * (2 ** max(0, int(attempt))))


def classify_backoff(
    status: int,
    headers: Optional[Dict[str, str]] = None,
    attempt: int = 0,
    *,
    now: Optional[float] = None,
    base: float = 2.0,
    max_wait: float = 900.0,
) -> Dict[str, Any]:
    """Classified backoff for a collection HTTP response.

    Field-verified rules (Arctic Shift runs, 2026-11):

    - 429/403: wait for ``X-RateLimit-Reset``/``Retry-After`` when present,
      otherwise retry exponentially; never rotate identity to continue;
    - 422 "slow down": exponential wait, the archive is asking for a slower
      cadence rather than a different route;
    - 5xx: exponential retry;
    - 400/401/404/410/451: permanent — stop and record the route as missing
      instead of burning the budget.

    Returns ``{"action": "continue"|"retry"|"wait"|"stop", "wait_seconds": float,
    "reason": str, "status": int}``. The caller owns the budget: once it is
    exhausted, stop the window honestly.
    """
    clock = time.time() if now is None else now
    if status in SUCCESS_STATUSES:
        return {"action": "continue", "wait_seconds": 0.0, "reason": "ok", "status": status}
    if status in PERMANENT_STATUSES:
        return {"action": "stop", "wait_seconds": 0.0, "reason": "permanent", "status": status}
    if status in (429, 403):
        reset = _reset_wait_seconds(headers, clock)
        wait = reset if reset is not None else _exponential_wait(attempt, base, max_wait)
        return {
            "action": "wait",
            "wait_seconds": round(min(max_wait, max(0.0, wait)), 3),
            "reason": "rate_limit_reset" if reset is not None else "rate_limit",
            "status": status,
        }
    if status == 422:
        return {
            "action": "retry",
            "wait_seconds": round(_exponential_wait(attempt, base, max_wait), 3),
            "reason": "slow_down",
            "status": status,
        }
    return {
        "action": "retry",
        "wait_seconds": round(_exponential_wait(attempt, base, max_wait), 3),
        "reason": "server_error" if status >= 500 else "unexpected",
        "status": status,
    }


def process_is_alive(pid: int) -> bool:
    """True when ``pid`` is a live process the current user can signal."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@contextlib.contextmanager
def single_writer_state(path: Path) -> Iterator[Path]:
    """Exclusive pid lock for one collector's state file.

    Field lesson (golf-main, 2026-11): a stale duplicate collector kept writing
    the same state file, doubling the request rate and corrupting resume state.
    Hold this lock around a run; a live owner raises :class:`SingleWriterError`,
    a dead owner's lock is reclaimed. Verify with ``ps`` before overriding.
    """
    state_path = Path(path)
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    try:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            owner = 0
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                owner = int(existing.get("pid") or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                owner = 0
            if owner and process_is_alive(owner):
                raise SingleWriterError(
                    f"state file is owned by live PID {owner}: {lock_path}. "
                    "Verify with ps and stop the old collector before restarting — "
                    "two writers double the request rate and corrupt resume state."
                )
            lock_path.unlink(missing_ok=True)
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": utc_now_iso()}, handle)
        acquired = True
        yield state_path
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


RELATIVE_TIME_UNITS: Dict[str, int] = {
    # English
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
    "month": 2592000, "months": 2592000,
    "year": 31536000, "years": 31536000,
    # Chinese
    "秒": 1, "秒钟": 1, "分钟": 60, "小时": 3600, "天": 86400, "日": 86400,
    "周": 604800, "星期": 604800, "礼拜": 604800, "个月": 2592000, "月": 2592000,
    "年": 31536000,
    # Korean
    "초": 1, "분": 60, "시간": 3600, "일": 86400, "주": 604800,
    "개월": 2592000, "달": 2592000, "년": 31536000,
    # Japanese
    "秒間": 1, "分間": 60, "時間": 3600, "日間": 86400, "週間": 604800,
    "ヶ月": 2592000, "か月": 2592000, "カ月": 2592000,
    "秒": 1, "分": 60, "時": 3600, "週": 604800,
}
_RELATIVE_SUFFIXES = ("ago", "前", "전", "之前", "以前")
_RELATIVE_NOW = ("just now", "刚刚", "方才", "방금", "たった今", "now")
_RELATIVE_RE = re.compile(
    r"(?P<count>\d+)\s*(?P<unit>"
    + "|".join(sorted(RELATIVE_TIME_UNITS, key=len, reverse=True))
    + r")\s*(?P<suffix>"
    + "|".join(_RELATIVE_SUFFIXES)
    + r")"
)


def parse_relative_time(
    text: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Parse a relative timestamp into an approximate UTC instant.

    Platforms render comments as "10 months ago" / "3小时前" / "2일 전" / "5 分前".
    A relative string can never be an exact date, so the result is always
    flagged ``date_precision="approximate"``; nothing here guesses an absolute
    time when the platform did not state one.
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    clock = now or datetime.now(tz=timezone.utc)
    low = raw.casefold()
    for marker in _RELATIVE_NOW:
        if low == marker or low.startswith(marker + " ") or low.endswith(" " + marker):
            return {
                "iso": clock.astimezone(timezone.utc).isoformat(),
                "seconds_ago": 0,
                "unit": "now",
                "date_precision": "approximate",
                "raw": raw,
            }
    match = _RELATIVE_RE.search(raw)
    if not match:
        return None
    count = int(match.group("count"))
    unit = match.group("unit")
    seconds = count * RELATIVE_TIME_UNITS[unit]
    instant = clock.timestamp() - seconds
    return {
        "iso": datetime.fromtimestamp(instant, tz=timezone.utc).isoformat(),
        "seconds_ago": seconds,
        "unit": unit,
        "date_precision": "approximate",
        "raw": raw,
    }


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON through a sibling temp file, then replace (crash-safe).

    Field lesson: persist after every round/burst — an un-persisted round is a
    lost round.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    Path(tmp).replace(target)


def with_connector_envelope(record: Dict[str, Any], run_id: str, connector_id: str,
                            connector_revision: str) -> Dict[str, Any]:
    record["source_record_id"] = record.get("record_id") or record.get("source_record_id")
    record["normalized_text_hash"] = (
        record.get("normalized_text_hash") or record.get("text_hash")
        or stable_text_hash(str(record.get("text") or ""))
    )
    record["collection_run_id"] = run_id
    record["connector_id"] = connector_id
    record["connector_revision"] = connector_revision
    return record


def collection_manifest_path(out: Path, run_id: str) -> Path:
    out = Path(out)
    parts = out.parts
    if "02-data" in parts:
        index = parts.index("02-data")
        root = Path(*parts[:index]) if index else Path(".")
        return root / "01-sources" / "manifests" / f"{run_id}.json"
    return out.with_name(out.stem + ".manifest.json")


def write_collection_manifest(
    out: Path,
    *,
    run_id: str,
    platform: str,
    connector_id: str,
    connector_revision: str,
    access_basis: str,
    query: str,
    started_at: str,
    completed_at: str,
    reached_records: int,
    written_records: int,
    stop_reason: str,
    requested_records: int = 0,
    errors: Optional[Iterable[str]] = None,
) -> Path:
    errors = list(errors or [])
    path = collection_manifest_path(out, run_id)
    payload = {
        "collection_run_id": run_id,
        "study_id": "",
        "platform": platform,
        "connector_id": connector_id,
        "connector_revision": connector_revision,
        "connector_license": "MIT",
        "access_basis": access_basis,
        "terms_reviewed_at": "",
        "data_rights_reviewed_at": "",
        "data_rights_basis": "See the approved study design",
        "route_id": query,
        "query": query,
        "requested_at": started_at,
        "completed_at": completed_at,
        "requested_records": int(requested_records),
        "reached_records": int(reached_records),
        "written_records": int(written_records),
        "blocked_or_dropped": {"errors": len(errors)},
        "rate_limit_or_quota": "",
        "warnings": errors,
        "stop_reason": stop_reason,
    }
    atomic_write_json(path, payload)
    return path


@contextlib.contextmanager
def collection_manifest(
    out: Path,
    *,
    run_id: str,
    platform: str,
    connector_id: str,
    connector_revision: str,
    access_basis: str,
    query: str,
    requested_records: int,
    written_records: Any,
):
    started_at = utc_now_iso()
    try:
        yield
    except Exception as exc:
        write_collection_manifest(
            out, run_id=run_id, platform=platform, connector_id=connector_id,
            connector_revision=connector_revision, access_basis=access_basis, query=query,
            started_at=started_at, completed_at=utc_now_iso(), reached_records=0,
            written_records=int(written_records() if callable(written_records) else written_records),
            stop_reason="failed", requested_records=requested_records, errors=[str(exc)])
        raise
    count = int(written_records() if callable(written_records) else written_records)
    write_collection_manifest(
        out, run_id=run_id, platform=platform, connector_id=connector_id,
        connector_revision=connector_revision, access_basis=access_basis, query=query,
        started_at=started_at, completed_at=utc_now_iso(), reached_records=count,
        written_records=count, stop_reason="completed", requested_records=requested_records)


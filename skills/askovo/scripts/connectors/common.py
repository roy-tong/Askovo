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

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
    for attempt in range(retries):
        try:
            try:
                import requests  # type: ignore

                response = requests.get(url, headers={"User-Agent": user_agent or USER_AGENT}, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except ModuleNotFoundError:
                req = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception:
                req = urllib.request.Request(url, headers={"User-Agent": user_agent or USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 404}:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} attempts: {url}") from last_error


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

"""Shared helpers for the consolidated labeling / dataset-building stages.

Provenance (consolidation lineage, most-evolved-first):

- Base: ``projects/灵泷视界/用户研究/scripts/common.py`` — the latest evolution of
  the family: CJK-aware word-boundary term matching (no false hits like
  ``ai`` inside ``said``), parametrized primary window (``after_utc`` as an
  argument, not a constant), table-driven ``quality_score`` penalties, and the
  ``commercial_promo_template`` / Chinese AI-template quality flags.
- Merged from ``projects/AI眼镜用户研究/scripts/common.py``: the product-hint +
  product-metadata inference, ``annotate_research_dimensions`` orchestration,
  market-region inference with ``region:XX`` query codes, and the
  merged-region logic that keeps an explicit non-unknown region label.
- Merged from ``projects/Tiiny用户研究/scripts/common.py`` (byte-identical to
  ``projects/泛具身用户研究/scripts/common.py``): the ``base_quality_flags`` /
  ``quality_score`` skeleton, month buckets, stable text hashing, and the
  JSONL read/write helpers.
- The precedent for taxonomy-as-config is 灵泷's ``config/adjacent_user_lexicon.json``
  (rules loaded from JSON instead of hardcoded). Here EVERY domain rule table
  (label dimensions, product terms, relevance vocabulary, sample buckets,
  quality-penalty overrides, signal stopwords) loads from one taxonomy JSON
  file — see ``taxonomy.example.json`` next to this script.

Project-agnostic changes vs. every source variant:

- No ``ROOT`` / ``CONFIG_PATH`` module constants; every path is an explicit
  argument. Callers run the stages from their study root (``data/raw`` →
  ``data/processed`` by convention).
- No ``USER_AGENT`` / ``AUTHOR_SALT`` / ``PRIMARY_AFTER_UTC`` constants; the
  salt and primary window come from the taxonomy config or CLI flags.
- Collection-only helpers (HTTP, request retries) are NOT carried over; they
  live in ``connectors/common.py``.

Untrusted-data rule (inherited from the repo): text handled here is source
content and is only ever matched, counted, hashed, or echoed as data — never
interpreted as instructions.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
CJK_TERM_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")

# Penalty table for quality_score (灵泷 evolution of the Tiiny/AI眼镜 if-chains).
# Values can be overridden per study via the taxonomy config ("quality_penalties").
BASE_QUALITY_PENALTIES: Dict[str, float] = {
    "too_short": 0.35,
    "removed_or_deleted": 0.7,
    "outside_primary_window": 0.8,
    "missing_created_at": 0.25,
    "possible_ai_generated_meta": 0.2,
    "moderator_or_bot_template": 0.85,
    "repetitive_low_signal": 0.7,
    "commercial_promo_template": 0.85,
}


# ---------------------------------------------------------------------------
# IO helpers (jsonl / jsonl.gz)
# ---------------------------------------------------------------------------

def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield rows from a ``.jsonl`` or ``.jsonl.gz`` file (suffix decides)."""
    path = Path(path)
    if not path.exists():
        return
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[call-arg]
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]], *, append: bool = True) -> int:
    """Write rows as JSONL; a ``.gz`` suffix writes gzip. Returns row count."""
    path = Path(path)
    ensure_parent(path)
    count = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "at" if append else "wt", encoding="utf-8") as handle:  # type: ignore[call-arg]
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def load_json_config(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def iter_raw_records(raw_dir: Path) -> Iterator[Dict[str, Any]]:
    """Iterate every ``*.jsonl`` / ``*.jsonl.gz`` under a raw directory."""
    for path in sorted(raw_dir.rglob("*.jsonl.gz")):
        yield from read_jsonl(path)
    for path in sorted(raw_dir.rglob("*.jsonl")):
        yield from read_jsonl(path)


# ---------------------------------------------------------------------------
# Text normalization and hashing
# ---------------------------------------------------------------------------

def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    value = html.unescape(str(text))
    value = TAG_RE.sub(" ", value).replace("\u0000", " ")
    return WS_RE.sub(" ", value).strip()


def stable_text_hash(text: Optional[str]) -> Optional[str]:
    cleaned = clean_text(text).lower()
    if not cleaned:
        return None
    cleaned = re.sub(r"https?://\S+", " URL ", cleaned)
    cleaned = re.sub(r"\W+", " ", cleaned)
    cleaned = WS_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:24]


def author_hash(author: Optional[str], salt: Optional[str] = None) -> Optional[str]:
    """Salted hash of an author handle; no salt → hash without pepper (still
    pseudonymous, but cross-run joins need a study-stable salt)."""
    if not author:
        return None
    normalized = str(author).strip().lower()
    if normalized in {"[deleted]", "deleted", "none", "unknown"}:
        return None
    material = (salt + ":" + normalized) if salt else normalized
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def utc_from_timestamp(ts: Optional[int | float | str]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def timestamp_from_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    match = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d{1,6})(.*)$", text)
    if match:
        frac = match.group(2).ljust(6, "0")
        text = f"{match.group(1)}.{frac}{match.group(3)}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_primary_date(value: Optional[str], after_utc: Optional[int]) -> bool:
    if after_utc is None:
        return True
    ts = timestamp_from_iso(value)
    return ts is not None and ts >= after_utc


def month_bucket(value: Optional[str]) -> Optional[str]:
    ts = timestamp_from_iso(value)
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Quality flags and score
# ---------------------------------------------------------------------------

def base_quality_flags(
    text: str,
    created_at: Optional[str],
    after_utc: Optional[int] = None,
) -> List[str]:
    """Deterministic quality flags (灵泷 evolution of the Tiiny skeleton).

    ``after_utc=None`` disables the ``outside_primary_window`` flag (mirrors
    the connectors/common precedent: an unconfigured window judges nothing).
    """
    flags: List[str] = []
    low = clean_text(text).lower()
    if len(low) < 40:
        flags.append("too_short")
    if low in {"[deleted]", "[removed]", "deleted", "removed"}:
        flags.append("removed_or_deleted")
    if created_at and not is_primary_date(created_at, after_utc):
        flags.append("outside_primary_window")
    if not created_at:
        flags.append("missing_created_at")
    if re.search(r"\b(as an ai language model|i cannot browse|chatgpt can)\b", low) or any(
        phrase in low
        for phrase in [
            "本回答由团结musechat",
            "本回答由团结 musechat",
            "本回答由ai生成",
            "本回答由 ai 生成",
        ]
    ):
        flags.append("possible_ai_generated_meta")
    if any(
        phrase in low
        for phrase in [
            "i am a bot, and this action was performed automatically",
            "please contact the moderators of this subreddit",
            "action was performed automatically",
            "generation_mode | subagent",
            "generation mode | subagent",
            "spec_source | project constitution",
            "spec source | project constitution",
            "this topic was automatically closed after",
            "this topic was automatically opened after",
        ]
    ):
        flags.append("moderator_or_bot_template")
    if re.search(r"generation[_*\s-]*mode.{0,12}subagent", low) or re.search(
        r"spec[_*\s-]*source.{0,12}project constitution", low
    ):
        if "moderator_or_bot_template" not in flags:
            flags.append("moderator_or_bot_template")
    if re.search(r"\b([a-z]{2,20})(?:\s+\1){2,}\b", low):
        flags.append("repetitive_low_signal")
    url_count = len(re.findall(r"https?://\S+", text or ""))
    if url_count >= 4 or (
        url_count >= 2
        and any(term in low for term in ["热销推荐", "视频同款", "购买链接", "affiliate link"])
    ):
        flags.append("commercial_promo_template")
    return flags


def quality_score(
    text: str,
    flags: List[str],
    score: Optional[int | float] = None,
    penalties: Optional[Dict[str, float]] = None,
) -> float:
    """Table-driven penalty score (灵泷); positive length bonus from Tiiny."""
    table = dict(BASE_QUALITY_PENALTIES)
    if penalties:
        table.update({str(k): float(v) for k, v in penalties.items()})
    value = 1.0
    value -= sum(table.get(flag, 0.0) for flag in flags)
    if len(text or "") > 200:
        value += 0.05
    if score is not None:
        try:
            if float(score) < 0:
                value -= 0.05
        except (TypeError, ValueError):
            pass
    return max(0.0, min(1.0, round(value, 3)))


# ---------------------------------------------------------------------------
# Term matching (CJK-aware word boundaries, from 灵泷/AI眼镜)
# ---------------------------------------------------------------------------

def term_in_lower_text(low: str, term: str) -> bool:
    """Substring match with word boundaries for latin terms; plain substring
    for CJK terms (no word boundaries in Chinese/Japanese/Korean script)."""
    needle = (term or "").lower().strip()
    if not needle:
        return False
    if CJK_TERM_RE.search(needle):
        return needle in low
    start = 0
    while True:
        index = low.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        before_ok = index == 0 or not low[index - 1].isalnum()
        after_ok = end == len(low) or not low[end].isalnum()
        if before_ok and after_ok:
            return True
        start = index + 1


def term_in_text(text: str, term: str) -> bool:
    return term_in_lower_text((text or "").lower(), term)


def label_terms(text: str, rules: Dict[str, List[str]]) -> List[str]:
    low = (text or "").lower()
    return [
        label
        for label, terms in rules.items()
        if any(term_in_lower_text(low, term) for term in terms or [])
    ]


def infer_language_hint(text: str, query: str = "", channel: str = "") -> str:
    """Script-based language hint (mechanics, not domain taxonomy — kept built-in)."""
    sample = f"{query} {channel} {text}"
    if re.search(r"[\u3040-\u30ff]", sample):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", sample):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", sample):
        return "zh"
    if re.search(r"\b(le|la|les|des|avec|avis|lunettes)\b", sample.lower()):
        return "fr_possible"
    if re.search(r"\b(der|die|das|mit|brille|test|bewertung)\b", sample.lower()):
        return "de_possible"
    return "en_or_unknown"


# ---------------------------------------------------------------------------
# Taxonomy: every domain rule table behind one JSON config
# ---------------------------------------------------------------------------

class Taxonomy:
    """Domain configuration for the labeling / dataset stages.

    Sections (all optional; see ``taxonomy.example.json``):

    - ``label_rules``: ``{dimension: {label: [terms...]}}`` — each dimension
      becomes a multi-label field ``<dimension>`` on every record.
    - ``product_terms`` / ``product_metadata``: product hint inference and the
      metadata fields attached to each hint (written as ``product_<key>``).
    - ``relevance_terms``: vocabulary for the topic-relevance ladder.
    - ``region_rules`` / ``region_code_markets`` / ``region_platforms``:
      market-region inference (incl. ``region:XX`` codes in the query).
    - ``sample_bucket``: platform buckets + ordered term rules + default.
    - ``control_buckets`` / ``control_min_relevance``: relevance-floor rescue
      buckets for counter-evidence (used by build_primary_dataset).
    - ``default_source_role``: role stamped when a record carries none.
    - ``primary_after_utc`` / ``author_salt``: study window and anonymization.
    - ``quality_penalties``: per-flag score penalty overrides.
    - ``signal_stopwords`` / ``signal_noise_phrases`` / ``signal_cjk_noise``:
      extra vocabulary for extract_candidate_signals.
    - ``export_fields`` / ``export_list_fields``: default CSV columns for
      export_metadata_detail.
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        data = data or {}
        self.data = data
        self.study_id: Optional[str] = data.get("study_id")
        self.author_salt: Optional[str] = data.get("author_salt")
        primary = data.get("primary_after_utc")
        self.primary_after_utc: Optional[int] = int(primary) if primary is not None else None
        self.label_rules: Dict[str, Dict[str, List[str]]] = {
            str(dim): {str(label): list(terms or []) for label, terms in rules.items()}
            for dim, rules in (data.get("label_rules") or {}).items()
        }
        self.product_terms: Dict[str, List[str]] = {
            str(name): list(terms or []) for name, terms in (data.get("product_terms") or {}).items()
        }
        self.product_metadata: Dict[str, Dict[str, Any]] = {
            str(name): dict(meta or {}) for name, meta in (data.get("product_metadata") or {}).items()
        }
        self.relevance_terms: List[str] = list(data.get("relevance_terms") or [])
        self.region_rules: Dict[str, List[str]] = {
            str(label): list(terms or []) for label, terms in (data.get("region_rules") or {}).items()
        }
        self.region_code_markets: Dict[str, str] = {
            str(code).upper(): str(market) for code, market in (data.get("region_code_markets") or {}).items()
        }
        self.region_platforms: Dict[str, List[str]] = {
            str(market): [str(p).lower() for p in platforms or []]
            for market, platforms in (data.get("region_platforms") or {}).items()
        }
        bucket_cfg = data.get("sample_bucket") or {}
        self.sample_platform_buckets: Dict[str, str] = {
            str(platform).lower(): str(bucket)
            for platform, bucket in (bucket_cfg.get("platform_buckets") or {}).items()
        }
        self.sample_ordered_rules: List[Tuple[str, List[str]]] = [
            (str(rule.get("bucket")), [str(t) for t in rule.get("terms") or []])
            for rule in bucket_cfg.get("ordered_rules") or []
            if rule.get("bucket")
        ]
        self.sample_default: str = str(bucket_cfg.get("default") or "general_discussion")
        self.control_buckets: List[str] = [str(b) for b in data.get("control_buckets") or []]
        self.control_min_relevance: float = float(data.get("control_min_relevance", 0.15))
        self.default_source_role: Optional[str] = data.get("default_source_role")
        self.quality_penalties: Dict[str, float] = {
            str(flag): float(v) for flag, v in (data.get("quality_penalties") or {}).items()
        }
        self.signal_stopwords: List[str] = [str(t) for t in data.get("signal_stopwords") or []]
        self.signal_noise_phrases: List[str] = [str(t) for t in data.get("signal_noise_phrases") or []]
        self.signal_cjk_noise: List[str] = [str(t) for t in data.get("signal_cjk_noise") or []]
        self.export_fields: List[str] = [str(f) for f in data.get("export_fields") or []]
        self.export_list_fields: List[str] = [str(f) for f in data.get("export_list_fields") or []]
        # corpus roles excluded from the primary build unless ``unless_field`` is truthy
        self.excluded_corpus_roles: List[Tuple[str, Optional[str]]] = [
            (
                str(entry.get("corpus_role")),
                str(entry["unless_field"]) if entry.get("unless_field") else None,
            )
            for entry in data.get("excluded_corpus_roles") or []
            if entry.get("corpus_role")
        ]

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        return cls(load_json_config(path))

    # -- inference helpers ---------------------------------------------------

    def _relevance_hits(self, blob: str) -> int:
        low = blob.lower()
        hits = sum(1 for term in self.relevance_terms if term_in_lower_text(low, term))
        product_hits = sum(
            1
            for terms in self.product_terms.values()
            for term in terms
            if term_in_lower_text(low, term)
        )
        return hits + product_hits * 2

    def topic_relevance(self, text: str, query: str = "", channel: str = "") -> float:
        """AI眼镜/灵泷 hit ladder. With no relevance vocabulary configured,
        returns a neutral 1.0 (the relevance filter then judges nothing)."""
        if not self.relevance_terms and not self.product_terms:
            return 1.0
        content_hits = self._relevance_hits(f"{channel} {text}")
        query_hits = self._relevance_hits(query)
        if content_hits == 0:
            return 0.15 if query_hits >= 2 and len(text or "") >= 160 else 0.0
        hits = content_hits + min(query_hits, 1)
        if hits <= 0:
            return 0.0
        if hits == 1:
            return 0.35
        if hits == 2:
            return 0.65
        return min(1.0, 0.65 + 0.08 * (hits - 2))

    def infer_product_hint(self, text: str = "", query: str = "", channel: str = "") -> Optional[str]:
        blob = f"{query} {channel} {text}".lower()
        scores: Dict[str, int] = {}
        for product, terms in self.product_terms.items():
            score = sum(1 for term in terms if term_in_lower_text(blob, term))
            if score:
                scores[product] = score
        if not scores:
            return None
        return max(scores.items(), key=lambda item: item[1])[0]

    def infer_sample_bucket(self, text: str, query: str = "", source_platform: str = "") -> str:
        platform = (source_platform or "").lower()
        if platform in self.sample_platform_buckets:
            return self.sample_platform_buckets[platform]
        low = f"{query} {text}".lower()
        for bucket, terms in self.sample_ordered_rules:
            if any(term_in_lower_text(low, term) for term in terms):
                return bucket
        return self.sample_default

    def infer_market_regions(
        self, text: str, query: str = "", channel: str = "", source_platform: str = ""
    ) -> List[str]:
        labels = set(label_terms(f"{query} {channel} {text}", self.region_rules))
        for match in re.finditer(r"(?:^|\|)region:([A-Za-z]{2})(?:\b|$)", query):
            market = self.region_code_markets.get(match.group(1).upper())
            if market:
                labels.add(market)
        platform = (source_platform or "").lower()
        for market, platforms in self.region_platforms.items():
            if platform in platforms:
                labels.add(market)
        return sorted(labels) or ["unknown_or_global"]

    def annotate(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Stamp every configured dimension onto a record (idempotent: existing
        non-empty values are kept, so re-runs and imports stay stable)."""
        text = clean_text(row.get("text"))
        query = str(row.get("source_query") or "")
        channel = " ".join(
            str(part or "") for part in [row.get("source_channel"), row.get("thread_title")]
        )
        if self.product_terms:
            raw_hint = row.get("product_hint")
            if raw_hint and raw_hint not in self.product_terms:
                row.setdefault("source_product_hint", raw_hint)
            product_hint = (
                raw_hint if raw_hint in self.product_terms else self.infer_product_hint(text, query, channel)
            )
            row["product_hint"] = product_hint
            meta = self.product_metadata.get(product_hint or "") or {}
            for key, value in meta.items():
                row.setdefault(f"product_{key}", value)
        for dimension, rules in self.label_rules.items():
            if not row.get(dimension):
                row[dimension] = label_terms(text, rules)
        if self.region_rules or self.region_platforms:
            inferred = self.infer_market_regions(text, query, channel, str(row.get("source_platform") or ""))
            existing = set(row.get("market_region_labels") or [])
            if not existing or existing == {"unknown_or_global"}:
                row["market_region_labels"] = inferred
            else:
                merged = (existing - {"unknown_or_global"}) | set(inferred)
                if len(merged) > 1:
                    merged.discard("unknown_or_global")
                row["market_region_labels"] = sorted(merged)
        if not row.get("language_hint"):
            row["language_hint"] = infer_language_hint(text, query, channel)
        return row

    def summary(self) -> Dict[str, Any]:
        """Config fingerprint for run summaries (what drove the labels)."""
        return {
            "study_id": self.study_id,
            "label_dimensions": sorted(self.label_rules.keys()),
            "product_count": len(self.product_terms),
            "relevance_term_count": len(self.relevance_terms),
            "sample_bucket_configured": bool(
                self.sample_platform_buckets or self.sample_ordered_rules
            ),
            "primary_after_utc": self.primary_after_utc,
            "control_buckets": self.control_buckets,
            "excluded_corpus_roles": [
                {"corpus_role": role, "unless_field": field}
                for role, field in self.excluded_corpus_roles
            ],
        }

#!/usr/bin/env python3
"""Reusable collect -> screen -> clean stage for raw JSONL research corpora.

Generalised from three scripts in the BCI demand-discovery study (see
connectors/README.md for provenance):

- clean_amazon_health_history.py: PII scrubbing, stable record-id derivation
  for datasets without ids, dedup on id + normalised text, audit output,
  gzip input;
- clean_legacy_reddit_archive.py: the same envelope with an extra u/@ handle
  redaction;
- screen_legacy_reddit_candidates.py: conservative multi-label lexical
  screening that marks rows `discovery_candidate_not_evidence`.

The pattern kept intact: read raw rows (never rewrite them), scrub
contact-like strings, hash identities, deduplicate on stable source ids
before text hashes, write a privacy-minimised envelope, and leave an audit
JSON with counts, rejection reasons, and policy. Added during collection:
a state.json checkpoint so interrupted cleans resume at the last processed
input line (skipped lines are re-read to rebuild the dedup sets, so
cross-boundary duplicates are still caught; the output is reopened in append
mode), and optional gzip output.

The output is a discovery/screening corpus, never an evidence table: rows
carry `primary_sample_eligible=false` until contextual review promotes them.

Standard library only; Python 3.9+.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, TextIO

REDACTIONS = {
    "email": (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL]"),
    "url": (re.compile(r"https?://\S+|www\.\S+", re.I), "[URL]"),
    "phone": (re.compile(r"(?<!\d)(?:\+?\d[\d .()\-]{7,}\d)(?!\d)"), "[PHONE]"),
    "user": (re.compile(r"(?<!\w)(?:u/|@)[A-Za-z0-9_\-]{2,}"), "[USER]"),
}
SPACE = re.compile(r"\s+")


def scrub(text: str, enabled: List[str]) -> str:
    for name in enabled:
        pattern, replacement = REDACTIONS[name]
        text = pattern.sub(replacement, text)
    return SPACE.sub(" ", text).strip()


def stable_text_hash(text: str) -> str:
    return hashlib.sha256(text.lower().encode()).hexdigest()


def open_input(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def open_output(path: Path, append: bool) -> TextIO:
    mode = "a" if append else "w"
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def derive_record_id(row: Dict, id_parts: List[str], text_hash: str) -> str:
    """Stable local key for datasets without a review/comment id.

    Same construction as the Amazon Health history cleaner: hash of the
    id-part values joined with the text hash, so a raw user_id never needs to
    be retained to re-identify the row.
    """
    material = "|".join(str(row.get(field) or "") for field in id_parts) + "|" + text_hash
    return hashlib.sha256(material.encode()).hexdigest()


def first_field(row: Dict, names: List[str]) -> Optional[str]:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def compile_lexicon(path: Path) -> Dict[str, List[re.Pattern]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {label: [re.compile(p, re.I) for p in pats] for label, pats in raw.items()}


def screen_labels(text: str, lexicon: Dict[str, List[re.Pattern]]) -> List[str]:
    return [label for label, pats in lexicon.items() if any(p.search(text) for p in pats)]


def build_envelope(
    row: Dict,
    *,
    text: str,
    text_hash: str,
    record_key: str,
    keep_fields: List[str],
    channel_field: str,
    created_at_field: str,
    run_id: str,
    platform: str,
    source_family: str,
    source_tier: str,
    dataset_role: str,
    lexicon: Optional[Dict[str, List[re.Pattern]]],
    keep_unlabeled: bool,
    screening_method: str,
) -> Optional[Dict]:
    envelope: Dict = {
        "collection_run_id": run_id,
        "source_platform": platform,
        "source_family": source_family,
        "source_record_id": f"{platform}:{record_key}",
    }
    if channel_field and row.get(channel_field) not in (None, ""):
        envelope["source_channel"] = str(row.get(channel_field))
    for field in keep_fields:
        if field in row:
            envelope[field] = row[field]
    if created_at_field:
        envelope["created_at"] = row.get(created_at_field)
    envelope.update(
        {
            "text": text,
            "normalized_text_hash": text_hash,
            "source_tier": source_tier,
            "primary_sample_eligible": False,
            "dataset_role": dataset_role,
        }
    )
    if lexicon is not None:
        labels = screen_labels(text, lexicon)
        if not labels and not keep_unlabeled:
            return None
        envelope["screen_labels"] = labels
        envelope["screening_method"] = screening_method
        envelope["screening_status"] = "discovery_candidate_not_evidence"
    return envelope


def main() -> None:
    parser = argparse.ArgumentParser(description="Privacy-minimise, deduplicate, and optionally screen a raw JSONL(.gz) corpus.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="resumable checkpoint JSON")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--platform", required=True, help="source platform stamped into the envelope")
    parser.add_argument("--source-family", required=True)
    parser.add_argument("--source-tier", default="published_historical_dataset")
    parser.add_argument("--dataset-role", default="privacy_minimised_discovery_corpus")
    parser.add_argument("--text-fields", default="title,text", help="comma-separated fields concatenated into the cleaned text")
    parser.add_argument("--id-fields", default="review_id,id,source_record_id", help="preferred stable id fields")
    parser.add_argument("--id-parts", default="", help="comma-separated fields hashed into a derived id when no id field exists (e.g. parent_asin,timestamp)")
    parser.add_argument("--channel-field", default="", help="field copied to source_channel (e.g. category)")
    parser.add_argument("--created-at-field", default="", help="field copied to created_at (e.g. timestamp)")
    parser.add_argument("--keep-fields", default="", help="comma-separated raw fields passed through into the envelope")
    parser.add_argument("--min-length", type=int, default=20)
    parser.add_argument("--redact", default="email,url,phone", help="comma-separated of: " + ",".join(sorted(REDACTIONS)))
    parser.add_argument("--lexicon", type=Path, default=None, help="JSON {label: [regex,...]}; enables the screening pass")
    parser.add_argument("--screening-method", default="lexicon_v1")
    parser.add_argument("--keep-unlabeled", action="store_true", help="with --lexicon: keep rows matching no label (empty screen_labels)")
    parser.add_argument("--checkpoint-every", type=int, default=20000, help="state checkpoint interval in written rows")
    args = parser.parse_args()

    lexicon = compile_lexicon(args.lexicon) if args.lexicon else None
    redactions = [name for name in args.redact.split(",") if name]
    unknown = [name for name in redactions if name not in REDACTIONS]
    if unknown:
        raise SystemExit(f"unknown redaction(s): {', '.join(unknown)}")
    text_fields = [f for f in args.text_fields.split(",") if f]
    id_fields = [f for f in args.id_fields.split(",") if f]
    id_parts = [f for f in args.id_parts.split(",") if f]
    keep_fields = [f for f in args.keep_fields.split(",") if f]

    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else None
    if state and (state.get("input") != str(args.input) or state.get("done")):
        state = None  # checkpoint belongs to another input or a finished run; start over
    skip_lines = int(state["processed_lines"]) if state else 0

    counts: Counter = Counter()
    rejected: Counter = Counter()
    label_totals: Counter = Counter()
    if state:
        counts.update(state.get("counts", {}))
        rejected.update(state.get("rejected", {}))
        label_totals.update(state.get("label_totals", {}))
    seen_ids = set(state.get("seen_ids", [])) if state else set()
    seen_texts = set(state.get("seen_texts", [])) if state else set()

    def write_state(done: bool) -> None:
        payload = {
            "input": str(args.input),
            "processed_lines": counts["input_rows"],
            "done": done,
            "counts": dict(counts),
            "rejected": dict(rejected),
            "label_totals": dict(label_totals),
            "seen_ids": sorted(seen_ids),
            "seen_texts": sorted(seen_texts),
        }
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def digest(row: Dict):
        """(record_key, text, text_hash) computed once per row."""
        text = scrub("\n".join(str(row.get(f) or "") for f in text_fields).strip(), redactions)
        text_hash = stable_text_hash(text)
        record_key = first_field(row, id_fields)
        if record_key is None and id_parts:
            record_key = derive_record_id(row, id_parts, text_hash)
        return record_key, text, text_hash

    args.output.parent.mkdir(parents=True, exist_ok=True)
    line_no = 0
    with open_input(args.input) as src, open_output(args.output, append=skip_lines > 0) as out:
        for line in src:
            line_no += 1
            if line_no <= skip_lines:
                # Resume: re-hash skipped lines into the dedup sets without
                # writing or re-classifying them, so duplicates across the
                # resume boundary are still caught. The skip test uses a
                # run-local line number - the persisted input_rows counter
                # already includes these lines from the previous run.
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record_key, _text, text_hash = digest(row)
                if record_key:
                    seen_ids.add(record_key)
                if _text:
                    seen_texts.add(text_hash)
                continue
            counts["input_rows"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rejected["invalid_json"] += 1
                continue
            record_key, text, text_hash = digest(row)
            if not record_key or len(text) < args.min_length:
                rejected["missing_id_or_short_text"] += 1
                continue
            if record_key in seen_ids:
                rejected["duplicate_source_id"] += 1
                continue
            if text_hash in seen_texts:
                rejected["duplicate_normalized_text"] += 1
                continue
            envelope = build_envelope(
                row,
                text=text,
                text_hash=text_hash,
                record_key=record_key,
                keep_fields=keep_fields,
                channel_field=args.channel_field,
                created_at_field=args.created_at_field,
                run_id=args.run_id,
                platform=args.platform,
                source_family=args.source_family,
                source_tier=args.source_tier,
                dataset_role=args.dataset_role,
                lexicon=lexicon,
                keep_unlabeled=args.keep_unlabeled,
                screening_method=args.screening_method,
            )
            if envelope is None:
                rejected["no_lexicon_label"] += 1
                continue
            seen_ids.add(record_key)
            seen_texts.add(text_hash)
            out.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            counts["written_rows"] += 1
            if lexicon is not None:
                label_totals.update(envelope["screen_labels"])
            if counts["written_rows"] % args.checkpoint_every == 0:
                write_state(done=False)
    write_state(done=True)

    counts["unique_source_ids"] = len(seen_ids)
    counts["unique_normalized_text"] = len(seen_texts)
    policy_bits = [
        "contact-like strings redacted: " + ",".join(redactions),
        "raw identifiers replaced by hashes; fields kept: " + (",".join(keep_fields) or "none"),
        "deduplicated on stable source ids then normalised text hashes",
    ]
    if lexicon is not None:
        policy_bits.append("lexical screen only; candidates marked discovery_candidate_not_evidence")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(
        json.dumps(
            {
                "counts": dict(counts),
                "rejected": dict(rejected),
                "screen_label_counts_multi_label": dict(label_totals),
                "policy": "; ".join(policy_bits),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"cleaned {counts['written_rows']} rows (rejected: {dict(rejected)}); audit at {args.audit}")


if __name__ == "__main__":
    main()

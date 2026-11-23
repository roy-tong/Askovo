"""Product behaviour observations as an explicit research source.

A product observation records what the collector actually saw in a product:
the version, the account permission, the platform, the region and when the
session ran. Each claim separates three things that are easy to blur:

* ``observed_facts`` - what appeared on screen or in the response;
* ``inferred_rule`` - the rule the collector thinks explains it;
* ``uncovered_conditions`` - what this session did not test.

Generalisation is a recorded decision, not a default: ``single_case`` (exactly
one run), ``repeated`` (at least two runs) or ``multi_context`` (at least two
distinct version/permission/platform/region tuples). There is no universal
level. Observations cap at E2 and still need human semantic review before they
enter ``02-data/evidence.jsonl``; this module never promotes them itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import study_context
import write_integrity

SCHEMA = "askovo.product-observation/1"
GENERATOR = "askovo.observation"
GENERATOR_VERSION = "1"
METHODS = ("manual", "scripted", "api")
GENERALIZATIONS = ("single_case", "repeated", "multi_context")
CONTEXT_FIELDS = ("product_version", "account_permission", "platform", "region")
OBSERVATION_LEVEL = "E2"
BASIS = "product_behavior_observation"
EXPORT_REL = Path("01-sources/observations.jsonl")
INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")

BOUNDARY = (
    "One recorded product session. It states what was observed and what was not "
    "tested; it does not prove a general product capability, a market fact or a "
    "purchase behaviour, and it does not enter the evidence pool without human review."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _context_of(doc: Dict[str, Any]) -> Dict[str, str]:
    return {field: _text(doc.get(field)) for field in CONTEXT_FIELDS}


def _context_key(item: Dict[str, Any]) -> Tuple[str, ...]:
    return tuple(_text(item.get(field)) for field in CONTEXT_FIELDS)


def validate_observation(doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["observation must be a JSON object"]
    if doc.get("schema") != SCHEMA:
        errors.append("schema must be %r" % SCHEMA)
    for field in ("observation_id", "product", "tested_at"):
        if not _text(doc.get(field)):
            errors.append("%s must be a non-empty string" % field)
    if doc.get("observation_id") and not ID_RE.match(str(doc["observation_id"])):
        errors.append("observation_id must contain only letters, digits, _ and -")
    for field in ("product_version", "account_permission", "platform", "region"):
        if not _text(doc.get(field)):
            errors.append(
                "%s is required: an observation without it cannot be scoped" % field)
    tested_at = _text(doc.get("tested_at"))
    if tested_at and not INSTANT_RE.match(tested_at):
        errors.append("tested_at must be an ISO-8601 instant with a timezone")
    if doc.get("method") not in METHODS:
        errors.append("method must be one of: %s" % ", ".join(METHODS))
    for field in ("inputs", "observed"):
        values = doc.get(field)
        if not isinstance(values, list) or not values:
            errors.append("%s must be a non-empty list of strings" % field)
            continue
        for index, item in enumerate(values):
            if not _text(item):
                errors.append("%s[%d] must be a non-empty string" % (field, index))

    claims = doc.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be a non-empty list")
        return errors
    seen = set()
    for index, claim in enumerate(claims):
        path = "claims[%d]" % index
        if not isinstance(claim, dict):
            errors.append("%s must be an object" % path)
            continue
        claim_id = _text(claim.get("claim_id"))
        if not claim_id:
            errors.append("%s.claim_id must be a non-empty string" % path)
        elif claim_id in seen:
            errors.append("%s.claim_id duplicates %r" % (path, claim_id))
        seen.add(claim_id)
        if not _text(claim.get("statement")):
            errors.append("%s.statement must be a non-empty string" % path)
        facts = claim.get("observed_facts")
        if not isinstance(facts, list) or not facts:
            errors.append("%s.observed_facts needs at least one observed fact" % path)
        else:
            for fact_index, fact in enumerate(facts):
                text = fact.get("text") if isinstance(fact, dict) else fact
                if not _text(text):
                    errors.append("%s.observed_facts[%d] must carry text"
                                  % (path, fact_index))
        if not _text(claim.get("inferred_rule")):
            errors.append(
                "%s.inferred_rule must say what rule the observation suggests" % path)
        uncovered = claim.get("uncovered_conditions")
        if not isinstance(uncovered, list) or not uncovered:
            errors.append(
                "%s.uncovered_conditions needs at least one untested condition" % path)
        else:
            for cond_index, item in enumerate(uncovered):
                if not _text(item):
                    errors.append("%s.uncovered_conditions[%d] must be non-empty"
                                  % (path, cond_index))
        generalization = claim.get("generalization")
        if generalization not in GENERALIZATIONS:
            errors.append(
                "%s.generalization must be one of %s; a product observation never "
                "becomes a universal capability claim"
                % (path, ", ".join(GENERALIZATIONS)))
            continue
        repeat = claim.get("repeat_count")
        if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
            errors.append("%s.repeat_count must be an integer >= 1" % path)
            continue
        if generalization == "single_case" and repeat != 1:
            errors.append("%s.repeat_count: single_case means exactly one run" % path)
        if generalization == "repeated" and repeat < 2:
            errors.append("%s.repeat_count: repeated means at least two runs" % path)
        if generalization == "multi_context":
            if repeat < 2:
                errors.append(
                    "%s.repeat_count: multi_context needs at least two runs" % path)
            contexts = claim.get("contexts")
            if not isinstance(contexts, list):
                errors.append("%s.contexts is required for multi_context" % path)
            else:
                keys = set()
                for ctx_index, item in enumerate(contexts):
                    if not isinstance(item, dict):
                        errors.append("%s.contexts[%d] must be an object"
                                      % (path, ctx_index))
                        continue
                    key = _context_key(item)
                    if not all(key):
                        errors.append(
                            "%s.contexts[%d] must fill %s"
                            % (path, ctx_index, ", ".join(CONTEXT_FIELDS)))
                    else:
                        keys.add(key)
                if len(keys) < 2:
                    errors.append(
                        "%s.contexts: multi_context needs at least two distinct "
                        "contexts" % path)
        if claim.get("evidence_level") != OBSERVATION_LEVEL:
            errors.append("%s.evidence_level must be %r"
                          % (path, OBSERVATION_LEVEL))
        if claim.get("basis") != BASIS:
            errors.append("%s.basis must be %r" % (path, BASIS))
    return errors


def load_observation(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("%s must contain one JSON object" % path)
    return payload


def _store_files(store: Path) -> List[Path]:
    if not store.is_dir():
        return []
    return sorted(path for path in store.glob("*.json") if path.is_file())


def _require_valid(doc: Dict[str, Any], source: str) -> None:
    errors = validate_observation(doc)
    if errors:
        raise ValueError("%s is not a valid observation:\n  - %s"
                         % (source, "\n  - ".join(errors)))


def cmd_record(args: argparse.Namespace) -> int:
    source = Path(args.file)
    doc = load_observation(source)
    if not ID_RE.match(str(doc.get("observation_id") or "")):
        print("ERROR: observation_id is unsafe for the observation store", file=sys.stderr)
        return 2
    _require_valid(doc, str(source))
    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    target = store / ("%s.json" % _text(doc["observation_id"]))
    if target.exists() and args.replace:
        existing = load_observation(target)
        if existing.get("reviewed_at") or existing.get("exported_at") \
                or existing.get("review_status") in ("reviewed", "accepted", "exported"):
            print("ERROR: a reviewed/exported observation is immutable; append a new revision",
                  file=sys.stderr)
            return 2
    if target.exists() and not args.replace:
        print("ERROR: %s already exists; observations are append-only "
              "(use --replace only to fix an un-reviewed file)" % target,
              file=sys.stderr)
        return 2
    study_context.StudyRepository(store).atomic_write_text(
        target, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    if args.json:
        print(json.dumps({
            "stored": str(target),
            "observation_id": doc["observation_id"],
            "claims": len(doc["claims"]),
            "generator": GENERATOR,
            "generated_at": _now(),
        }, ensure_ascii=False, indent=2))
    else:
        print("已登记观察：%s（%d 条结论，E2 上限，仍需人工语义审核）"
              % (target, len(doc["claims"])))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    source = Path(args.file)
    doc = load_observation(source)
    errors = validate_observation(doc)
    if args.json:
        print(json.dumps({"file": str(source), "ok": not errors,
                          "errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print("校验失败：%s" % source)
        for item in errors:
            print("  - %s" % item)
    else:
        print("校验通过：%s（%d 条结论）" % (source, len(doc.get("claims") or [])))
    return 0 if not errors else 1


def cmd_list(args: argparse.Namespace) -> int:
    store = Path(args.store)
    rows = []
    for path in _store_files(store):
        try:
            doc = load_observation(path)
        except (OSError, ValueError) as exc:
            rows.append({"file": str(path), "error": str(exc)})
            continue
        claims = doc.get("claims") or []
        levels = sorted({str(item.get("generalization")) for item in claims
                         if isinstance(item, dict)})
        rows.append({
            "observation_id": doc.get("observation_id"),
            "product": "%s %s" % (doc.get("product") or "?",
                                  doc.get("product_version") or "?"),
            "platform": doc.get("platform"),
            "region": doc.get("region"),
            "tested_at": doc.get("tested_at"),
            "claims": len(claims),
            "generalization": levels,
        })
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("（%s 下没有观察记录）" % store)
        return 0
    print("%-28s %-22s %-10s %-6s %-24s %s"
          % ("observation", "product", "platform", "region", "tested_at", "claims"))
    for row in rows:
        if "error" in row:
            print("%-28s ERROR %s" % (Path(row["file"]).name, row["error"]))
            continue
        print("%-28s %-22s %-10s %-6s %-24s %d (%s)"
              % (row["observation_id"], row["product"], row["platform"],
                 row["region"], row["tested_at"], row["claims"],
                 ",".join(row["generalization"]) or "-"))
    return 0


def _claim_line(doc: Dict[str, Any], claim: Dict[str, Any], source: Path) -> Dict[str, Any]:
    generalization = claim.get("generalization")
    return {
        "source_kind": "product_observation",
        "source_ref": "%s/%s" % (doc.get("observation_id"), claim.get("claim_id")),
        "source_hash": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        "observed_facts": list(claim.get("observed_facts") or []),
        "inputs": list(doc.get("inputs") or []),
        "observed": list(doc.get("observed") or []),
        "observation_id": doc.get("observation_id"),
        "claim_id": claim.get("claim_id"),
        "statement": claim.get("statement"),
        "inferred_rule": claim.get("inferred_rule"),
        "uncovered_conditions": list(claim.get("uncovered_conditions") or []),
        "product": doc.get("product"),
        "product_version": doc.get("product_version"),
        "method": doc.get("method"),
        "tested_at": doc.get("tested_at"),
        "context": _context_of(doc),
        "contexts": list(claim.get("contexts") or []),
        "generalization": generalization,
        "repeat_count": claim.get("repeat_count"),
        "not_generalizable": generalization == "single_case",
        "evidence_level": OBSERVATION_LEVEL,
        "basis": BASIS,
        "boundary": BOUNDARY,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
    }


def cmd_export(args: argparse.Namespace) -> int:
    store = Path(args.store)
    documents = []
    for path in _store_files(store):
        doc = load_observation(path)
        errors = validate_observation(doc)
        if errors:
            print("ERROR: %s is invalid; export aborted:\n  - %s"
                  % (path, "\n  - ".join(errors)), file=sys.stderr)
            return 1
        documents.append((doc, path))
    study = Path(args.study)
    if not study.is_dir():
        print("ERROR: study directory not found: %s" % study,
              file=sys.stderr)
        return 2
    target = study / EXPORT_REL
    lines = [_claim_line(doc, claim, source)
             for doc, source in documents for claim in doc.get("claims") or []
             if isinstance(claim, dict)]

    def identity(line: Dict[str, Any]) -> Tuple[str, str, str]:
        return (str(line.get("observation_id") or ""),
                str(line.get("claim_id") or ""), str(line.get("source_hash") or ""))

    repository = study_context.StudyRepository(study)
    new_lines = []
    with repository.transaction("observation export") as txn:
        existing = set()
        if target.is_file():
            for raw in target.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    item = json.loads(raw)
                    if isinstance(item, dict):
                        existing.add(identity(item))
        new_lines = [line for line in lines if identity(line) not in existing]
        if new_lines:
            payload = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"
                              for line in new_lines)
            txn.add(target, payload, mode="append")
            txn.commit()
    summary = {
        "exported": str(target),
        "observations": len(documents),
        "claims": len(lines),
        "added": len(new_lines),
        "duplicates": len(lines) - len(new_lines),
        "single_case": sum(1 for line in lines if line["not_generalizable"]),
        "generalization": dict(sorted(
            (level, sum(1 for line in lines if line["generalization"] == level))
            for level in GENERALIZATIONS)),
        "note": "E2 only; promotion into evidence.jsonl still needs named human review",
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("已导出 %d 条新结论到 %s（重复 %d 条；其中新增 single_case %d 条，标记为不可泛化）"
              % (len(new_lines), target, summary["duplicates"],
                 sum(1 for line in new_lines if line["not_generalizable"])))
        print("提醒：观察是 E2 来源，进入证据库前仍需具名人工语义审核。")
    return 0

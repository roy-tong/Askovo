"""A-05 incremental research delta: append-only evidence snapshots.

One decision question keeps accumulating public issue material. This module
answers "what changed since the accepted decision, and does it still hold?"
without ever rewriting history:

- **append-only snapshots** — every real change produces a new
  ``04-findings/deltas/vNNN-<hash>/`` directory. An older version is never
  rewritten, so a deleted or edited record keeps its previous content, hash and
  acquisition basis (A25).
- **identity, not content** — ``added`` / ``changed`` / ``deleted`` are keyed by
  source id plus ``updated_at``. An edited issue is not new evidence, and an
  author rename is not a new observed user (A26); a stable user id proves the
  same person, and a login-only rename is recorded as ``identity_drift`` for
  human review instead of inflating the user count.
- **idempotent sync** — the same export twice is a no-op: no new version, no new
  index line, and a delta that says 无变化 instead of pretending to have produced
  a version (A24).
- **never auto-approve** — a new counter-evidence raises ``needs_re_review`` and
  lists the current-vs-accepted difference; the approved DecisionSnapshot is
  byte-identical before and after (A27). The predicate is shared with
  :mod:`decision_brief` so the two entries cannot disagree.
- **degraded read** — an unreachable or unauthorized source still shows the last
  good snapshot, marked ``stale`` with the reason and the last success time
  (A28).

The delta is a read-only projection: it writes derived artifacts under
``04-findings/deltas/`` and ``06-report/`` and never edits the canonical chain,
the demand judgments or the evidence store.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import decision_brief
import issue_structuring

SCHEMA = "askovo.decision-delta/1"
SNAPSHOT_SCHEMA = "askovo.decision-snapshot/1"
SCHEMA_VERSION = "1.0"

DELTAS_RELATIVE = Path("04-findings/deltas")
INDEX_NAME = "index.jsonl"
STATE_NAME = "state.json"
EVIDENCE_NAME = "evidence.jsonl"
SNAPSHOT_NAME = "snapshot.json"
DELTA_NAME = "delta.json"
DECISION_SNAPSHOTS_SUBDIR = "decision-snapshots"
REPORT_RELATIVE = Path("06-report")
DELTA_MD_NAME = "decision-delta.md"
CANONICAL_REF = "04-findings/product-reasoning.json"
JUDGMENTS_RELATIVE = "04-findings/demand-judgments.json"

#: Fields whose difference makes a source "changed". Identity and timestamps are
#: included so an author rename or an edit is visible, but never a new record.
CONTENT_FIELDS = (
    "title", "body", "state", "author_ref", "author_login", "author_id",
    "created_at", "updated_at", "author_association", "labels", "comments",
)

BOUNDARY = (
    "Delta 是只读投影：它比较两次授权导出的来源身份与更新时间，列出新增/变更/删除记录、"
    "受影响节点、反证影响与是否需要重审。它不分配证据等级、不自动批准、不自动推翻已签决定；"
    "历史快照永不覆盖。"
)


class DeltaError(ValueError):
    """A delta rule was violated; always carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INPUT_REQUIRED",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _study(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / "study.json"
    if not path.is_file():
        raise DeltaError(f"study.json not found under {Path(study_dir).resolve()}",
                         "INPUT_REQUIRED", "run `askovo do` first")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeltaError(f"cannot read study.json: {exc}", "INTERNAL_ERROR")
    if not isinstance(payload, dict):
        raise DeltaError("study.json must be an object", "INTERNAL_ERROR")
    return payload


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #

def _issue_ref(raw: Dict[str, Any]) -> str:
    url = str(raw.get("html_url") or raw.get("url") or "")
    import re

    match = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        return f"github:{match.group(1)}/{match.group(2)}#{match.group(3)}"
    return f"github:{raw.get('id') or raw.get('number') or ''}"


def _labels(raw: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for item in raw.get("labels") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


def _comments(raw: Dict[str, Any]) -> List[Dict[str, str]]:
    comments: List[Dict[str, str]] = []
    for comment in raw.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
        comments.append({
            "author_ref": f"github:{user.get('login') or comment.get('author') or ''}",
            "created_at": str(comment.get("created_at") or ""),
            "body": str(comment.get("body") or ""),
        })
    return comments


def _record(raw: Dict[str, Any], *, run_id: str, version: str) -> Dict[str, Any]:
    """One source record: identity is the source id, content is hashed separately."""
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    login = str(user.get("login") or raw.get("author") or "").strip()
    user_id = user.get("id")
    author_id = (f"github-user:{user_id}" if user_id not in (None, "") else f"login:{login}")
    record = {
        "source_id": f"github:{raw.get('id') or raw.get('number') or ''}",
        "issue_ref": _issue_ref(raw),
        "author_ref": f"github:{login}",
        "author_login": login,
        "author_id": author_id,
        "author_association": str(raw.get("author_association") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "state": str(raw.get("state") or ""),
        "title": str(raw.get("title") or ""),
        "body": str(raw.get("body") or ""),
        "labels": _labels(raw),
        "comments": _comments(raw),
        "visibility": str(raw.get("visibility") or "public"),
        "snapshot_version": version,
        "run_id": run_id,
    }
    record["content_hash"] = _sha_text(json.dumps(
        {field: record[field] for field in CONTENT_FIELDS},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return record


def _evidence_text(records: List[Dict[str, Any]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                   for record in records)


# --------------------------------------------------------------------------- #
# state + snapshots
# --------------------------------------------------------------------------- #

def _deltas_dir(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / DELTAS_RELATIVE


def _index(study_dir: Path) -> List[Dict[str, Any]]:
    return _read_jsonl(_deltas_dir(study_dir) / INDEX_NAME)


def _state(study_dir: Path) -> Dict[str, Any]:
    payload = _load(_deltas_dir(study_dir) / STATE_NAME)
    return payload if isinstance(payload, dict) else {}


def _save_state(study_dir: Path, state: Dict[str, Any]) -> None:
    path = _deltas_dir(study_dir) / STATE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record_error(study_dir: Path, reason: str, reason_code: str) -> None:
    state = _state(study_dir)
    state.update({
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.delta-state",
        "last_error_at": _now(),
        "last_error": reason,
        "last_error_code": reason_code,
    })
    state.setdefault("last_success_at", None)
    state.setdefault("latest_version", None)
    _save_state(study_dir, state)


def _latest_snapshot(study_dir: Path) -> Optional[Dict[str, Any]]:
    index = _index(study_dir)
    if not index:
        return None
    entry = index[-1]
    version = str(entry.get("version") or "")
    if not version:
        return None
    directory = _deltas_dir(study_dir) / version
    snapshot = _load(directory / SNAPSHOT_NAME)
    if not isinstance(snapshot, dict):
        return None
    return {
        "version": version,
        "dir": directory,
        "snapshot": snapshot,
        "records": _read_jsonl(directory / EVIDENCE_NAME),
        "delta": _load(directory / DELTA_NAME) or {},
    }


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #

def sync(study_dir: Path, file_path: Any, *, authorized_by: str = "",
         since: str = "", label: str = "", question: str = "") -> Dict[str, Any]:
    """Compare an authorized export with the latest snapshot; append a version on change.

    A no-op sync (identical export) creates no version. A failed sync records the
    error and leaves the previous snapshot readable and marked stale.
    """
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    operator = str(authorized_by or "").strip()
    if not operator:
        raise DeltaError(
            "syncing an issue export requires a named authorizer (--authorized-by NAME)",
            "AUTH_REQUIRED",
            "a human must confirm the export's access and data rights before it is read")
    source = Path(str(file_path or "")).resolve()
    try:
        if not source.is_file():
            raise DeltaError(f"export file not found: {source}", "INPUT_REQUIRED",
                             "check the authorized export path; the previous snapshot is unchanged")
        rows = issue_structuring._parse_export(source)
    except (DeltaError, OSError, ValueError) as exc:
        _record_error(study_dir, str(exc), getattr(exc, "reason_code", "INPUT_REQUIRED"))
        raise

    filters = {"since": since or None, "label": label or None}
    skipped_private = 0
    current: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        if not issue_structuring._visibility_ok(raw):
            skipped_private += 1
            continue
        created = str(raw.get("created_at") or "")
        if since and created and created[:10] < str(since):
            continue
        if label and str(label).lower() not in [name.lower() for name in _labels(raw)]:
            continue
        record = _record(raw, run_id="", version="")
        current[record["source_id"]] = record
    records = [current[key] for key in sorted(current)]
    evidence_text = _evidence_text(records)
    evidence_hash = _sha_text(evidence_text)
    run_id = "delta-" + evidence_hash[7:19]

    previous = _latest_snapshot(study_dir)
    prev_records: Dict[str, Dict[str, Any]] = {}
    if previous is not None:
        prev_records = {str(item.get("source_id")): item for item in previous["records"]}
    prev_filters = (previous["snapshot"].get("filters") if previous else None) or {}
    filters_match = previous is not None and prev_filters == filters

    added = [current[key] for key in sorted(set(current) - set(prev_records))]
    deleted_ids = sorted(set(prev_records) - set(current))
    changed: List[Dict[str, Any]] = []
    for source_id in sorted(set(current) & set(prev_records)):
        old = prev_records[source_id]
        new = current[source_id]
        if old.get("content_hash") == new.get("content_hash"):
            continue
        fields = [field for field in CONTENT_FIELDS if old.get(field) != new.get(field)]
        previous_ref = (f"{DELTAS_RELATIVE.as_posix()}/"
                        f"{previous['version'] if previous else 'unknown'}/"
                        f"{EVIDENCE_NAME}#{source_id}")
        changed.append({
            "source_id": source_id,
            "issue_ref": new.get("issue_ref"),
            "previous_hash": old.get("content_hash"),
            "current_hash": new.get("content_hash"),
            "previous_updated_at": old.get("updated_at"),
            "current_updated_at": new.get("updated_at"),
            "previous_author_ref": old.get("author_ref"),
            "current_author_ref": new.get("author_ref"),
            "previous_author_id": old.get("author_id"),
            "current_author_id": new.get("author_id"),
            "fields": fields,
            "previous_ref": previous_ref,
        })

    # A26: a stable user id proves the same person; without one the rename is
    # recorded as drift and never inflates the observed-user count.
    identity_drift = [
        {
            "source_id": item["source_id"],
            "previous_author_ref": item["previous_author_ref"],
            "current_author_ref": item["current_author_ref"],
            "basis": "login_only",
            "detail": "登录名变化但无法证明是同一人：保留来源身份，不新增观测用户，需人工复核",
        }
        for item in changed
        # A stable user id proves the same person, so a rename is not drift. Without
        # one, the login change cannot be proven benign: record it, never count it.
        if item["previous_author_id"] != item["current_author_id"]
    ]

    deletion_basis = "same_window_export" if filters_match else (
        "no_previous_snapshot" if previous is None else "not_asserted")
    deleted: List[Dict[str, Any]] = []
    if filters_match:
        deletions_state = _state(study_dir)
        for source_id in deleted_ids:
            old = prev_records[source_id]
            deleted.append({
                "source_id": source_id,
                "issue_ref": old.get("issue_ref"),
                "previous_hash": old.get("content_hash"),
                "previous_ref": (f"{DELTAS_RELATIVE.as_posix()}/{previous['version']}/"
                                 f"{EVIDENCE_NAME}#{source_id}"),
                "author_ref": old.get("author_ref"),
                "acquisition_basis": deletions_state.get("acquisition_basis")
                                     or "human-authorized local export",
                "retention_rule": deletions_state.get("retention_rule")
                                  or "keep the snapshot with its hash; never re-read the source",
            })

    changed_ids = {item["source_id"] for item in added} | {item["source_id"] for item in changed}
    reasoning = _load(study_dir / CANONICAL_REF) or {}
    judgments = _load(study_dir / JUDGMENTS_RELATIVE) or []
    chains = [item for item in reasoning.get("chains") or [] if isinstance(item, dict)] \
        if isinstance(reasoning, dict) else []
    chain = chains[0] if chains else {}
    affected = _affected_nodes(chains, changed_ids)
    registered_counter = set()
    for item in chains:
        registered_counter.update(str(value) for value in item.get("counter_evidence_ids") or [])
    for judgment in judgments if isinstance(judgments, list) else []:
        if isinstance(judgment, dict):
            registered_counter.update(str(value) for value in
                                     judgment.get("counter_evidence_ids") or [])
    counter_impact = [
        {
            "record_id": record_id,
            "chain_id": chain.get("id"),
            "issue_ref": (current.get(record_id) or prev_records.get(record_id) or {}).get("issue_ref"),
            "why": "该记录被登记为反证，且本次增量新增或修改了它：建议重审当前决定",
        }
        for record_id in sorted(changed_ids & registered_counter)
    ]
    signal = decision_brief.review_signal(
        chain, extra_counter_ids=[item["record_id"] for item in counter_impact])
    needs_re_review = bool(signal["needs_re_review"])

    changed_any = bool(added or changed or deleted)
    version = previous["version"] if (previous is not None and not changed_any) else _next_version(
        study_dir, evidence_hash)
    for record in records:
        record["snapshot_version"] = version
        record["run_id"] = run_id

    accepted = _accepted_snapshot(study_dir)
    differences = _differences(added, changed, deleted, counter_impact, accepted, evidence_hash)
    recommendation = _current_recommendation(chain, judgments)
    document: Dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.decision-delta",
        "study_id": str(study.get("study_id") or ""),
        "generated_at": _now(),
        "version": version,
        "supersedes": previous["version"] if previous else None,
        "accepted_version": accepted.get("evidence_snapshot_hash") if accepted else None,
        "has_changes": changed_any,
        "noop": not changed_any,
        "message": ("无变化：来源身份与更新时间均与上一版本一致，未生成新版本"
                    if not changed_any else
                    f"新增 {len(added)}、变更 {len(changed)}、删除 {len(deleted)} 条来源记录"),
        "counts": {
            "added": len(added),
            "changed": len(changed),
            "deleted": len(deleted),
            "unchanged": len(set(current) & set(prev_records)),
            "total": len(records),
        },
        "deletion_basis": deletion_basis,
        "added": added,
        "changed": changed,
        "deleted": deleted,
        "identity": _identity(records, prev_records, identity_drift),
        "affected_nodes": affected,
        "counter_impact": counter_impact,
        "needs_re_review": needs_re_review,
        "review_basis": signal["reasons"],
        "accepted": accepted,
        "current": recommendation,
        "differences": differences,
        "decision_record_mutated": False,
        "source": {
            "run_id": run_id,
            "file": str(source),
            "sha256": evidence_hash,
            "authorized_by": operator,
            "filters": filters,
            "skipped_private": skipped_private,
            "selection_bias": issue_structuring._selection_bias(
                since, label, len(records), skipped_private),
        },
        "boundary": BOUNDARY,
    }
    document["digest"] = _digest({
        key: value for key, value in document.items() if key != "generated_at"
    })
    document.update(_freshness(study_dir, extra_reason=""))
    document["next_required_action"] = _next_action(document)

    if changed_any:
        _write_version(study_dir, document, records, evidence_text, evidence_hash,
                       operator=operator, filters=filters, question=question)
    else:
        state = _state(study_dir)
        state.update({
            "schema_version": SCHEMA_VERSION,
            "kind": "askovo.delta-state",
            "last_checked_at": document["generated_at"],
            "last_success_at": state.get("last_success_at"),
            "latest_version": state.get("latest_version"),
            "last_error": None,
            "last_error_code": None,
            "last_error_at": None,
            "acquisition_basis": "human-authorized local export; no network read, no API call",
            "retention_rule": "keep the snapshot with its hash; the study owns the copy",
        })
        _save_state(study_dir, state)
        document.update(_freshness(study_dir, extra_reason=""))
        document["next_required_action"] = _next_action(document)
    return document


def _next_version(study_dir: Path, evidence_hash: str) -> str:
    index = _index(study_dir)
    return f"v{len(index) + 1:03d}-{evidence_hash[7:19]}"


def _write_version(study_dir: Path, document: Dict[str, Any],
                   records: List[Dict[str, Any]], evidence_text: str,
                   evidence_hash: str, *, operator: str, filters: Dict[str, Any],
                   question: str) -> None:
    version = str(document["version"])
    directory = _deltas_dir(study_dir) / version
    if directory.exists():  # pragma: no cover - content-addressed, never re-entered
        raise DeltaError(f"snapshot version {version} already exists", "INTERNAL_ERROR",
                         "versions are append-only; never overwrite history")
    directory.mkdir(parents=True, exist_ok=False)
    evidence_path = directory / EVIDENCE_NAME
    evidence_path.write_text(evidence_text, encoding="utf-8")
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.decision-snapshot",
        "decision_id": f"DS-{version.split('-')[0]}",
        "study_id": document["study_id"],
        "question": question or document.get("current", {}).get("question"),
        "scope": document.get("source", {}).get("filters") or {},
        "hypothesis_ids": [],
        "evidence_snapshot_hash": evidence_hash,
        "recommendation_snapshot_hash": _sha_text(json.dumps(
            document.get("current") or {}, ensure_ascii=False, sort_keys=True)),
        "chosen_option": (document.get("accepted") or {}).get("chosen_option"),
        "approval_ref": None,
        "approved_at": None,
        "approved_by": None,
        "identity_basis": "declaration_only",
        "next_validation": list(document.get("review_basis") or []),
        "validation_receipts": [],
        "supersedes": document.get("supersedes"),
        "current_review_status": "needs_re_review" if document["needs_re_review"] else "proposed",
        "generated_at": document["generated_at"],
        "filters": filters,
        "record_count": len(records),
        "authorized_by": operator,
        "source": document.get("source"),
        "boundary": BOUNDARY,
    }
    (directory / SNAPSHOT_NAME).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / DELTA_NAME).write_text(
        json.dumps({key: value for key, value in document.items() if key != "markdown"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(document)
    (directory / DELTA_MD_NAME).write_text(markdown, encoding="utf-8")
    report_dir = study_dir / REPORT_RELATIVE
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / DELTA_MD_NAME).write_text(markdown, encoding="utf-8")

    index_path = _deltas_dir(study_dir) / INDEX_NAME
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "version": version,
            "supersedes": document.get("supersedes"),
            "generated_at": document["generated_at"],
            "evidence_snapshot_hash": evidence_hash,
            "counts": document["counts"],
            "needs_re_review": document["needs_re_review"],
            "accepted_by": operator,
        }, ensure_ascii=False) + "\n")

    state = _state(study_dir)
    state.update({
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.delta-state",
        "last_checked_at": document["generated_at"],
        "last_success_at": document["generated_at"],
        "latest_version": version,
        "last_error": None,
        "last_error_code": None,
        "last_error_at": None,
        "acquisition_basis": "human-authorized local export; no network read, no API call",
        "retention_rule": "keep the snapshot with its hash; the study owns the copy",
    })
    _save_state(study_dir, state)


def _affected_nodes(chains: List[Dict[str, Any]],
                    changed_ids: set) -> List[Dict[str, Any]]:
    affected: Dict[str, Dict[str, Any]] = {}
    for chain in chains:
        chain_id = str(chain.get("id") or "chain")
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for node_name, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for record_id in node.get("evidence_ids") or []:
                record_id = str(record_id)
                if record_id not in changed_ids:
                    continue
                entry = affected.setdefault(record_id, {
                    "record_id": record_id,
                    "chain_id": chain_id,
                    "nodes": [],
                    "why": "该记录被 canonical 节点引用，来源变化会影响该节点",
                })
                if node_name not in entry["nodes"]:
                    entry["nodes"].append(node_name)
    return [affected[key] for key in sorted(affected)]


def _identity(records: List[Dict[str, Any]], prev_records: Dict[str, Dict[str, Any]],
              drift: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_ids = {str(record.get("author_id")) for record in records}
    previous_ids = {str(record.get("author_id")) for record in prev_records.values()}
    stable = all(str(record.get("author_id") or "").startswith("github-user:")
                 for record in records) if records else True
    return {
        "observed_users": len(current_ids),
        "previous_observed_users": len(previous_ids),
        "new_users": sorted(current_ids - previous_ids),
        "identity_drift": drift,
        "identity_basis": "stable_id" if stable else "login_only",
        "note": (
            "记录数不是用户数：同一来源被编辑不产生新用户；登录名变化若无稳定 user id，"
            "只记为 identity_drift 供人工复核"),
    }


def _current_recommendation(chain: Dict[str, Any],
                            judgments: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
    gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
    return {
        "question": chain.get("title"),
        "recommendation": gate.get("decision") or business.get("statement") or chain.get("title"),
        "decision_status": (str(chain.get("status") or "unknown")),
        "confidence": chain.get("confidence"),
        "judgments": len([item for item in judgments if isinstance(item, dict)]),
    }


def _accepted_snapshot(study_dir: Path) -> Optional[Dict[str, Any]]:
    directory = _deltas_dir(study_dir) / DECISION_SNAPSHOTS_SUBDIR
    if not directory.is_dir():
        return None
    snapshots: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        payload = _load(path)
        if isinstance(payload, dict):
            payload["path"] = str(path)
            snapshots.append(payload)
    if not snapshots:
        return None
    snapshots.sort(key=lambda item: str(item.get("approved_at") or ""))
    return snapshots[-1]


def _differences(added: List[Dict[str, Any]], changed: List[Dict[str, Any]],
                 deleted: List[Dict[str, Any]], counter_impact: List[Dict[str, Any]],
                 accepted: Optional[Dict[str, Any]], evidence_hash: str) -> List[Dict[str, Any]]:
    differences: List[Dict[str, Any]] = []
    if counter_impact:
        differences.append({
            "kind": "new_counter_evidence",
            "record_ids": [item["record_id"] for item in counter_impact],
            "detail": "新的反证材料出现：建议重审当前决定",
        })
    if changed:
        differences.append({
            "kind": "changed_sources",
            "record_ids": [item["source_id"] for item in changed],
            "detail": "来源被编辑；旧版本内容与 hash 保留，不被覆盖",
        })
    if deleted:
        differences.append({
            "kind": "deleted_sources",
            "record_ids": [item["source_id"] for item in deleted],
            "detail": "来源被删除；快照、hash 与获取权说明保留",
        })
    if added:
        differences.append({
            "kind": "added_sources",
            "record_ids": [item["source_id"] for item in added],
            "detail": "新增来源记录；是否改变结论由人工判断",
        })
    if accepted and accepted.get("evidence_snapshot_hash") != evidence_hash:
        differences.append({
            "kind": "snapshot_drift",
            "record_ids": [],
            "detail": ("当前证据快照与已批准版本不同；已批准记录保持只读，"
                       "需人工重审后另行追加版本"),
        })
    return differences


def _freshness(study_dir: Path, *, extra_reason: str) -> Dict[str, Any]:
    """Staleness has two sources: a failed sync, or a broken canonical reference.

    The second is shared with :func:`decision_brief.stale_inputs`: the brief and
    the delta must never disagree about whether the decision is still current.
    """
    state = _state(study_dir)
    last_error_at = str(state.get("last_error_at") or "")
    last_success_at = str(state.get("last_success_at") or "")
    sync_failed = bool(last_error_at) and (
        not last_success_at or last_error_at > last_success_at)
    broken = decision_brief.stale_inputs(study_dir)
    stale = bool(sync_failed or broken)
    reason = str(state.get("last_error") or "") or extra_reason
    if broken and not sync_failed:
        reason = "；".join(str(item.get("detail")) for item in broken)
    return {
        "stale": stale,
        "reason_code": "STALE_SOURCE" if stale else None,
        "last_success_at": last_success_at or None,
        "stale_reasons": broken,
        "freshness": {
            "status": "stale" if stale else "fresh",
            "reason": reason,
            "last_error_at": last_error_at or None,
            "last_success_at": last_success_at or None,
        },
    }


def _next_action(document: Dict[str, Any]) -> str:
    if document.get("stale"):
        return ("来源不可达：先恢复授权导出并重跑 `askovo delta sync`；"
                "当前只能浏览上次可用结果，不能当作最新")
    if document.get("noop"):
        return "无变化：不需要重审；如需推进，补充新的授权来源或等待新素材"
    if document.get("needs_re_review"):
        return ("新反证挑战当前决定：人工重审并在 `askovo delta approve` 中记录新决定；"
                "已批准记录保持只读，不会被自动推翻")
    if not document.get("accepted"):
        return "尚未有已批准决定：确认建议后运行 `askovo delta approve --by NAME`"
    return "增量已记录：按 review_basis 逐条核对受影响节点与反证"


# --------------------------------------------------------------------------- #
# read-side projections
# --------------------------------------------------------------------------- #

def show(study_dir: Path, *, version: str = "") -> Dict[str, Any]:
    """Return one delta version (default: latest), marked stale when the source failed."""
    study_dir = Path(study_dir).resolve()
    _study(study_dir)
    index = _index(study_dir)
    if not index:
        raise DeltaError(
            "no delta snapshot yet; a delta needs at least one authorized export sync",
            "INPUT_REQUIRED",
            "run `askovo delta sync STUDY --file EXPORT.jsonl --authorized-by NAME`")
    wanted = str(version or "").strip()
    if wanted:
        matches = [item for item in index if item.get("version") == wanted]
        if not matches:
            raise DeltaError(f"unknown delta version {wanted!r}", "INPUT_REQUIRED",
                             "run `askovo delta status STUDY` to list versions")
        entry = matches[0]
    else:
        entry = index[-1]
    directory = _deltas_dir(study_dir) / str(entry["version"])
    document = _load(directory / DELTA_NAME)
    if not isinstance(document, dict):
        raise DeltaError(f"delta artifact for {entry['version']} is unreadable",
                         "INTERNAL_ERROR", "re-run `askovo delta sync`")
    document = dict(document)
    document.update(_freshness(study_dir, extra_reason=""))
    document["next_required_action"] = _next_action(document)
    document["artifact_refs"] = [
        str(directory / name) for name in (EVIDENCE_NAME, SNAPSHOT_NAME, DELTA_NAME, DELTA_MD_NAME)
        if (directory / name).is_file()
    ]
    document["markdown"] = render_markdown(document)
    return document


def status(study_dir: Path) -> Dict[str, Any]:
    """Version list plus freshness; a status always names a concrete next step."""
    study_dir = Path(study_dir).resolve()
    _study(study_dir)
    index = _index(study_dir)
    freshness = _freshness(study_dir, extra_reason="")
    state = _state(study_dir)
    if not index:
        return {
            "schema_version": SCHEMA_VERSION,
            "study_id": str(_study(study_dir).get("study_id") or ""),
            "state": "no_data",
            "versions": 0,
            "latest_version": None,
            "latest_at": None,
            "last_success_at": freshness["last_success_at"],
            "stale": freshness["stale"],
            "reason_code": freshness["reason_code"],
            "freshness": freshness["freshness"],
            "next_required_action": (
                "askovo delta sync STUDY --file EXPORT.jsonl --authorized-by NAME"),
            "boundary": BOUNDARY,
        }
    latest = index[-1]
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": str(state.get("study_id") or ""),
        "state": "needs_re_review" if latest.get("needs_re_review") else "ready",
        "versions": len(index),
        "latest_version": latest.get("version"),
        "latest_at": latest.get("generated_at"),
        "last_success_at": freshness["last_success_at"],
        "stale": freshness["stale"],
        "reason_code": freshness["reason_code"],
        "freshness": freshness["freshness"],
        "counts": latest.get("counts") or {},
        "needs_re_review": bool(latest.get("needs_re_review")),
        "versions_detail": index,
        "next_required_action": (
            "先修复来源并重跑 `askovo delta sync`" if freshness["stale"]
            else "人工重审新反证，然后 `askovo delta approve --by NAME`"
            if latest.get("needs_re_review")
            else "增量已就绪；按需 `askovo delta show` 查看差异"),
        "boundary": BOUNDARY,
    }


def approve(study_dir: Path, *, by: str = "", approval_ref: str = "",
            option: str = "", decision_id: str = "") -> Dict[str, Any]:
    """Record a human approval as a DecisionSnapshot (a declaration, not a proof)."""
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    operator = str(by or "").strip()
    if not operator:
        raise DeltaError(
            "approving a decision requires a named human (--by NAME)", "AUTH_REQUIRED",
            "the CLI records a declaration; a model must never sign a decision")
    snapshot = _latest_snapshot(study_dir)
    if snapshot is None:
        raise DeltaError("no delta snapshot to approve", "INPUT_REQUIRED",
                         "run `askovo delta sync` first")
    document = _load(snapshot["dir"] / DELTA_NAME) or {}
    directory = _deltas_dir(study_dir) / DECISION_SNAPSHOTS_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob("*.json"))
    wanted = str(decision_id or "").strip() or f"DS-{len(existing) + 1:03d}"
    path = directory / f"{wanted}.json"
    if path.exists():
        raise DeltaError(f"decision snapshot {wanted} already exists", "POLICY_DENIED",
                         "approved decisions are append-only; record a new version instead")
    current = document.get("current") or {}
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.decision-snapshot",
        "decision_id": wanted,
        "study_id": str(study.get("study_id") or ""),
        "question": current.get("question"),
        "scope": (document.get("source") or {}).get("filters") or {},
        "hypothesis_ids": [],
        "evidence_snapshot_hash": snapshot["snapshot"].get("evidence_snapshot_hash"),
        "recommendation_snapshot_hash": snapshot["snapshot"].get(
            "recommendation_snapshot_hash"),
        "chosen_option": str(option or "").strip() or None,
        "approval_ref": str(approval_ref or "").strip() or None,
        "approved_at": _now(),
        "approved_by": operator,
        "identity_basis": "declaration_only",
        "next_validation": list(document.get("review_basis") or []),
        "validation_receipts": [],
        "supersedes": _previous_decision_id(existing),
        "current_review_status": "approved",
        "version": snapshot["version"],
        "needs_re_review_at_approval": bool(document.get("needs_re_review")),
        "note": ("approval_ref 的身份真实性依赖实际签核机制；CLI 自填人名只算声明，"
                 "不构成业务批准证明"),
        "boundary": BOUNDARY,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "approved",
        "decision_id": wanted,
        "path": str(path),
        "approval_ref": payload["approval_ref"],
        "approved_by": operator,
        "approved_at": payload["approved_at"],
        "chosen_option": payload["chosen_option"],
        "evidence_snapshot_hash": payload["evidence_snapshot_hash"],
        "identity_basis": payload["identity_basis"],
        "next_required_action": (
            "已记录声明式批准；后续增量只会提示 needs_re_review，不会自动推翻该记录"),
    }


def _previous_decision_id(existing: List[Path]) -> Optional[str]:
    if not existing:
        return None
    return existing[-1].stem


# --------------------------------------------------------------------------- #
# markdown (四块)
# --------------------------------------------------------------------------- #

def render_markdown(document: Dict[str, Any]) -> str:
    counts = document.get("counts") or {}
    identity = document.get("identity") or {}
    lines = [
        f"# Decision Delta：{document.get('study_id')}",
        "",
        f"- 版本：`{document.get('version')}`"
        f"（supersedes：`{document.get('supersedes') or '无'}`）",
        f"- 变化：新增 {counts.get('added', 0)}、变更 {counts.get('changed', 0)}、"
        f"删除 {counts.get('deleted', 0)}、未变 {counts.get('unchanged', 0)}",
        f"- 观测用户：{identity.get('observed_users', 0)}"
        f"（上一版本 {identity.get('previous_observed_users', 0)}；"
        f"identity_basis：`{identity.get('identity_basis')}`）",
        f"- `needs_re_review`：**{document.get('needs_re_review')}**；"
        f"`decision_record_mutated`：**{document.get('decision_record_mutated')}**",
        f"- {document.get('message')}",
        "",
        "## 新增证据",
        "",
    ]
    if document.get("added"):
        for item in document["added"]:
            lines.append(f"- `{item.get('source_id')}`（{item.get('issue_ref')}；"
                         f"作者：{item.get('author_ref')}；更新：{item.get('updated_at')}）"
                         f"：{str(item.get('title') or '')[:120]}")
    else:
        lines.append("- 无新增来源记录。")
    lines.extend(["", "## 已影响节点", ""])
    if document.get("affected_nodes"):
        for item in document["affected_nodes"]:
            lines.append(f"- `{item.get('record_id')}` → {item.get('chain_id')}"
                         f".{', '.join(item.get('nodes') or [])}：{item.get('why')}")
    else:
        lines.append("- 本次变化的记录未被任何 canonical 节点引用。")
    if document.get("changed"):
        lines.extend(["", "### 变更来源（旧版本保留）", ""])
        for item in document["changed"]:
            lines.append(f"- `{item.get('source_id')}` 字段 {', '.join(item.get('fields') or [])}"
                         f"；旧版本：`{item.get('previous_ref')}`")
    if document.get("deleted"):
        lines.extend(["", "### 删除来源（快照保留）", ""])
        for item in document["deleted"]:
            lines.append(f"- `{item.get('source_id')}`；旧版本：`{item.get('previous_ref')}`；"
                         f"获取依据：{item.get('acquisition_basis')}")
    lines.extend(["", "## 反证影响", ""])
    if document.get("counter_impact"):
        for item in document["counter_impact"]:
            lines.append(f"- `{item.get('record_id')}`（{item.get('issue_ref') or '未知来源'}）"
                         f"：{item.get('why')}")
    else:
        lines.append("- 本次增量未涉及已登记的反证记录。")
    if identity.get("identity_drift"):
        lines.extend(["", "### 身份漂移（人工复核）", ""])
        for item in identity["identity_drift"]:
            lines.append(f"- `{item.get('source_id')}`："
                         f"{item.get('previous_author_ref')} → {item.get('current_author_ref')}"
                         f"（{item.get('basis')}）{item.get('detail')}")
    lines.extend(["", "## 建议是否重审", ""])
    if document.get("needs_re_review"):
        lines.append("- **建议重审**：新反证或已登记反证发生变化；已批准记录保持只读。")
        for reason in document.get("review_basis") or []:
            lines.append(f"  - {reason}")
    else:
        lines.append("- 暂不需要重审：未发现挑战当前决定的新材料。")
    accepted = document.get("accepted")
    lines.extend(["", "### current vs accepted", ""])
    if accepted:
        lines.append(f"- 已批准：`{accepted.get('decision_id')}`"
                     f"（approval_ref：{accepted.get('approval_ref') or '未记录'}；"
                     f"证据快照：`{accepted.get('evidence_snapshot_hash')}`）")
    else:
        lines.append("- 尚无已批准决定（`askovo delta approve --by NAME`）。")
    current = document.get("current") or {}
    lines.append(f"- 当前建议：{current.get('recommendation')}"
                 f"（decision_status：`{current.get('decision_status')}`）")
    for difference in document.get("differences") or []:
        lines.append(f"- 差异 `{difference.get('kind')}`：{difference.get('detail')}")
    lines.extend(["", "## 下一步", "", f"- {document.get('next_required_action')}", "",
                  "## 边界", "", str(document.get("boundary") or ""), ""])
    return "\n".join(lines)

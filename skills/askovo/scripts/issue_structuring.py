"""A-03 issue -> user task / demand structuring.

Turns a **local** GitHub issue export into machine candidates and lets a named
human accept or reject them. It is deliberately not a second evidence chain:

- the snapshot keeps the authorized export, its SHA-256, acquisition basis and
  retention rule (A16: a deleted source stays inspectable);
- normalized records reuse :func:`sure_engine._normalize_platform_record`, the
  same shape `collect`/`analyze`/`audit` already read;
- acceptance writes one canonical ``evidence`` record plus one
  ``demand-judgments.json`` judgment, so the existing
  ``evidence -> demand-judgments -> product-reasoning`` chain stays the only
  truth. Nothing here assigns a validated status.

Semantic rules are enforced in code, not prose (AC A13-A18):

- one login with ten issues is **one** observed user, and comments on one issue
  are context, not independent users (A13);
- distinct logins are never claimed to be distinct people (``login_only``);
- a feature request is a stated desire, not behaviour: it caps at E1 and cannot
  carry a demand claim (A14);
- no quotable body text means ``unverified`` with no quote span (A15);
- a deleted source keeps its snapshot, hash and rights note (A16);
- one counter-evidence is never outvoted by support count (A17);
- private content never reaches any study artifact: snapshots are built from a
  field whitelist (A18).

Zero network. The future live-connector seam is
:data:`LIVE_CONNECTOR_ENABLED` — a single, permanently False flag until a
reviewed GitHub connector lands.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sure_engine

SCHEMA_VERSION = "1.0"
CANDIDATES_KIND = "askovo.issue-candidates"
ACCEPTANCE_KIND = "askovo.issue-acceptance"
IMPORTS_KIND = "askovo.issue-imports"

CANDIDATES_RELATIVE = Path("04-findings/issue-candidates.json")
ACCEPTANCE_RELATIVE = Path("04-findings/issue-acceptance.jsonl")
IMPORTS_RELATIVE = Path("04-findings/issue-imports.json")
RAW_RELATIVE = Path("02-data/raw/issues")
MANIFEST_RELATIVE = Path("01-sources/manifests")
NORMALIZED_RELATIVE = Path("02-data/normalized.jsonl")
EVIDENCE_RELATIVE = Path("02-data/evidence.jsonl")
JUDGMENTS_RELATIVE = Path("04-findings/demand-judgments.json")

#: Deliberate seam for a future reviewed GitHub connector. Flipping this on
#: without the reviewed connector and its access basis would be the exact
#: bypass the repository forbids, so it stays False and is asserted in tests.
LIVE_CONNECTOR_ENABLED = False

# PRD §3 A-03: the thirteen machine-candidate fields, verbatim.
CANDIDATE_FIELDS = (
    "issue_ref",
    "author_ref",
    "created_at",
    "updated_at",
    "user_task",
    "trigger",
    "current_workaround",
    "failure_consequence",
    "requested_feature",
    "severity_candidate",
    "source_quote_span",
    "confidence_basis",
    "representativeness_warning",
)
#: Four claim kinds per the PRD plus the honest fifth for "no quotable text".
CLAIM_KINDS = (
    "bug_reproduction",
    "subjective_complaint",
    "feature_request",
    "observed_behavior",
    "unknown",
)
CONFIDENCE_BASES = ("reproducible_text", "self_report_text", "unverified")
SEVERITY_VALUES = ("critical", "high", "medium", "low", "unknown")
DISPOSITIONS = ("insufficient", "challenged", "supported_candidate")
CANDIDATE_STATUSES = ("proposed", "accepted", "rejected")

#: A stated desire is E1. Only observed behaviour or a reproduction reaches E2;
#: E3+ would require acceptance/commercial behaviour this data cannot show.
EVIDENCE_CAP = {
    "bug_reproduction": "E2",
    "observed_behavior": "E2",
    "feature_request": "E1",
    "subjective_complaint": "E1",
    "unknown": "E0",
}
_LEVEL_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4-": 4, "E4+": 5, "E5": 6}
_SEVERITY_BY_KIND = {
    "bug_reproduction": "high",
    "observed_behavior": "medium",
    "feature_request": "unknown",
    "subjective_complaint": "low",
    "unknown": "unknown",
}
_CRITICAL_LABELS = {"security", "data-loss", "datacloss", "critical", "p0", "blocker"}
_MAINTAINER_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}

_REPRO_MARKERS = (
    "steps to reproduce", "reproduce", "traceback", "stack trace", "exception",
    "复现步骤", "报错信息", "堆栈",
)
_WORKAROUND_MARKERS = (
    "by hand", "manually", "workaround", "we retry", "retry", "hand-edit", "fallback",
    "手动", "手工", "重试", "绕过", "临时",
)
_REQUEST_MARKERS = (
    "please add", "would be great", "could you", "feature request", "it would be nice",
    "support for", "请加", "希望增加", "建议增加", "能不能加", "求加", "希望支持", "加一个",
)
_CONSEQUENCE_MARKERS = (
    "fail", "fails", "breaks", "broken", "lose", "lost", "crash", "crashes", "cannot",
    "can't", "unable", "delay", "delayed", "miss", "缓慢", "失败", "崩溃", "丢失", "无法",
    "延误", "错过",
)
_TRIGGER_MARKERS = (
    "when ", "after ", "every ", "whenever", "each time", "during", "当", "每次", "一旦",
)
_FIRST_PERSON = ("we ", "i ", "our ", "my ", "us ", "我们", "我")
_COUNTER_MARKERS = (
    "does not happen", "doesn't happen", "works fine", "works for me", "no problem",
    "would not pay", "won't pay", "not a problem", "not an issue", "不会发生", "没问题",
    "正常", "不会付费",
)
_STOPWORDS = set(
    "the and for with that this from are was were you your our not but have has had will "
    "can could should about into over under more most some such than then them they their "
    "there here what when where which who whom why how all any both each few other own same "
    "so too very just also does do did we i us me my is it be to of in on at as by or an a "
    "would".split()
)
_SENTENCE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")


class IssueError(ValueError):
    """A structuring rule was violated; always carries a C-01 reason code."""

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
        raise IssueError(f"study.json not found under {Path(study_dir).resolve()}",
                         "INPUT_REQUIRED", "run `askovo do` first")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssueError(f"cannot read study.json: {exc}", "INTERNAL_ERROR")
    if not isinstance(payload, dict):
        raise IssueError("study.json must be an object", "INTERNAL_ERROR")
    return payload


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


# --------------------------------------------------------------------------- #
# import: authorized export -> snapshot + normalized records
# --------------------------------------------------------------------------- #

#: A18: the snapshot is built from this whitelist, never from the raw row, so a
#: private note (or any future private field) cannot ride along into the study.
_SNAPSHOT_FIELDS = (
    "id", "number", "title", "body", "state", "html_url", "user", "author_association",
    "created_at", "updated_at", "closed_at", "labels", "comments", "visibility",
    "deleted_at",
)
_COMMENT_FIELDS = ("user", "body", "created_at")


def _snapshot_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for field in _SNAPSHOT_FIELDS:
        if field not in raw:
            continue
        if field == "comments":
            comments = []
            for comment in raw.get("comments") or []:
                if not isinstance(comment, dict):
                    continue
                comments.append({key: comment.get(key) for key in _COMMENT_FIELDS
                                 if key in comment})
            row["comments"] = comments
        elif field == "user":
            user = raw.get("user")
            if isinstance(user, dict):
                entry = {"login": str(user.get("login") or ""),
                         "type": str(user.get("type") or "User")}
                if user.get("id") is not None:
                    entry["id"] = user.get("id")
                row["user"] = entry
            else:
                row["user"] = {"login": str(user or ""), "type": "User"}
        elif field == "labels":
            labels = []
            for label in raw.get("labels") or []:
                if isinstance(label, dict) and label.get("name"):
                    labels.append({"name": str(label["name"])})
                elif isinstance(label, str) and label.strip():
                    labels.append({"name": label.strip()})
            row["labels"] = labels
        else:
            row[field] = raw.get(field)
    return row


def _identity(login: Any, user_id: Any = None) -> Tuple[str, str]:
    """Normalize a GitHub identity.

    Logins are case-insensitive and may carry surrounding whitespace, so they are
    ``casefold``-ed before use; the numeric ``user.id`` is the stable identity and
    wins whenever the export provides it (D2: ``Alice``/``alice``/``  alice  `` is
    one observed user, and a rename does not create a second one).
    """
    normalized = str(login or "").strip().casefold()
    author_ref = f"github:{normalized}"
    has_id = user_id is not None and str(user_id).strip() != ""
    author_id = f"github-user:{user_id}" if has_id else f"login:{normalized}"
    return author_ref, author_id


def _login(raw: Dict[str, Any]) -> str:
    user = raw.get("user")
    if isinstance(user, dict):
        return str(user.get("login") or "").strip()
    return str(user or "").strip()


def _label_names(raw: Dict[str, Any]) -> List[str]:
    return [str(item.get("name") or "").lower() for item in raw.get("labels") or []
            if isinstance(item, dict)]


def _is_maintainer(raw: Dict[str, Any]) -> bool:
    return str(raw.get("author_association") or "").upper() in _MAINTAINER_ASSOCIATIONS


def _visibility_ok(raw: Dict[str, Any]) -> bool:
    visibility = str(raw.get("visibility") or "public").strip().lower()
    return visibility in ("public", "")


_SOURCE_PLAN_FIELDS = ("corpus_role", "source_family", "route_or_query", "target_records",
                       "cap_share", "access_status", "known_bias")


def _ensure_source_plan(study_dir: Path, *, record_count: int, selection_bias: str) -> None:
    """Declare the issue source in the study plan before its records become evidence.

    The audit refuses evidence from a source family the plan never named; an
    import is the human act that declares it, so the declaration is explicit and
    idempotent rather than implicit.
    """
    path = Path(study_dir) / "01-sources" / "source-plan.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, str]] = []
    if path.is_file():
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)
                        if str(row.get("source_family") or "").strip()]
        except OSError:
            rows = []
    if any(str(row.get("source_family")) == "github" for row in rows):
        return
    rows.append({
        "corpus_role": "open_scene",
        "source_family": "github",
        "route_or_query": "authorized public issue export (no live read)",
        "target_records": str(record_count),
        "cap_share": "1.00",
        "access_status": "available via authorized export",
        "known_bias": selection_bias or "self-selected public issues",
    })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_SOURCE_PLAN_FIELDS),
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in _SOURCE_PLAN_FIELDS})


def _parse_export(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    rows: List[Dict[str, Any]] = []
    if suffix == ".jsonl":
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IssueError(f"export line {index} is not valid JSON: {exc}", "INPUT_REQUIRED")
            if not isinstance(item, dict):
                raise IssueError(f"export line {index} is not an object", "INPUT_REQUIRED")
            rows.append(item)
        return rows
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("issues") or []
        if not isinstance(payload, list):
            raise IssueError("export JSON must be an array or an object with items",
                             "INPUT_REQUIRED")
        for item in payload:
            if not isinstance(item, dict):
                raise IssueError("export JSON items must be objects", "INPUT_REQUIRED")
            rows.append(item)
        return rows
    raise IssueError(f"unsupported export format {suffix!r}; use .jsonl or .json",
                     "UNSUPPORTED_SCOPE",
                     "GitHub issue export as JSONL (`gh issue list --json ...`)")


def _selection_bias(since: str, label: str, record_count: int, skipped: int) -> str:
    filters: List[str] = []
    if since:
        filters.append(f"created since {since}")
    if label:
        filters.append(f"label {label}")
    if not filters and not skipped:
        return ""
    parts = ["sample restricted to " + " and ".join(filters)] if filters else ["sample"]
    parts.append(f"{record_count} public issues")
    if skipped:
        parts.append(f"{skipped} non-public rows excluded")
    return ("; ".join(parts)
            + ". A filtered window cannot represent all users: selection bias is explicit, "
              "not corrected.")


def import_export(study_dir: Path, file_path: Path, *, authorized_by: str = "",
                  since: str = "", label: str = "", question: str = "",
                  retention_rule: str = "") -> Dict[str, Any]:
    """Snapshot an authorized export and normalize its public issues.

    Authorization is a human act: without ``authorized_by`` nothing is written
    (C-01 ``AUTH_REQUIRED``). Non-public rows are dropped and counted, never
    copied (A18).
    """
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    operator = str(authorized_by or "").strip()
    if not operator:
        raise IssueError(
            "importing an issue export requires a named authorizer (--authorized-by NAME)",
            "AUTH_REQUIRED",
            "a human must confirm the export's access and data rights before it is read")
    if LIVE_CONNECTOR_ENABLED:  # pragma: no cover - deliberate seam, never enabled here
        raise IssueError("a live GitHub connector is not reviewed; use an authorized export",
                         "UNSUPPORTED_SCOPE")
    source = Path(file_path).resolve()
    if not source.is_file():
        raise IssueError(f"export file not found: {source}", "INPUT_REQUIRED")
    rows = _parse_export(source)

    skipped_private = 0
    skipped_filter = 0
    snapshot_rows: List[Dict[str, Any]] = []
    for raw in rows:
        if not _visibility_ok(raw):
            skipped_private += 1
            continue
        created = str(raw.get("created_at") or "")
        if since and created and created[:10] < str(since):
            skipped_filter += 1
            continue
        if label and str(label).lower() not in _label_names(raw):
            skipped_filter += 1
            continue
        snapshot_rows.append(_snapshot_row(raw))

    snapshot_text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            for row in snapshot_rows)
    sha256 = _sha_text(snapshot_text)
    run_id = "issues-" + hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()[:12]
    snapshot_dir = study_dir / RAW_RELATIVE
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{run_id}.jsonl"
    if not snapshot_path.is_file():
        snapshot_path.write_text(snapshot_text, encoding="utf-8")

    bias = _selection_bias(since, label, len(snapshot_rows), skipped_private)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.issue-export-manifest",
        "run_id": run_id,
        "platform": "github",
        "study_id": str(study.get("study_id") or ""),
        "imported_at": _now(),
        "authorized_by": operator,
        "source_file": str(source),
        "snapshots": [{"path": str(snapshot_path), "sha256": sha256,
                       "records": len(snapshot_rows)}],
        "parsed": len(rows),
        "skipped_private": skipped_private,
        "skipped_filter": skipped_filter,
        "filters": {"since": since or None, "label": label or None},
        "selection_bias": bias,
        "acquisition_basis": (
            "human-authorized local export; no network read, no API call"
        ),
        "retention_rule": retention_rule or (
            "keep the snapshot with its hash; the study owns the copy and never re-reads "
            "the source"
        ),
        "deleted_records": sum(1 for row in snapshot_rows
                               if str(row.get("state") or "") == "deleted"),
        "source_availability": (
            "snapshot_only" if any(str(row.get("state") or "") == "deleted"
                                   for row in snapshot_rows) else "snapshot"
        ),
        "source_availability_note": (
            "a deleted source is recorded as snapshot_only: the study keeps the snapshot, its "
            "SHA-256 and this acquisition/retention note, and never re-reads the live source"
        ),
        "boundary": (
            "A snapshot proves what was exported at import time, not that the source still "
            "exists, that authors are distinct people, or that the sample represents all users."
        ),
    }
    manifest_dir = study_dir / MANIFEST_RELATIVE
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    _ensure_source_plan(study_dir, record_count=len(snapshot_rows),
                        selection_bias=bias)

    normalized_path = study_dir / NORMALIZED_RELATIVE
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {str(record.get("record_id")) for record in _read_jsonl(normalized_path)}
    added = 0
    with normalized_path.open("a", encoding="utf-8") as handle:
        for raw in snapshot_rows:
            login = _login(raw)
            body = str(raw.get("body") or "")
            title = str(raw.get("title") or "")
            number = raw.get("number") or raw.get("id")
            record_id = f"github:{raw.get('id') or number}"
            normalized = sure_engine._normalize_platform_record(
                {"record_id": record_id, "title": title, "body": body,
                 "url": raw.get("html_url") or "", "author": login,
                 "created_at": raw.get("created_at") or "",
                 "claim_type": "need", "evidence_form": "self_report"},
                "github", run_id, question)
            author_ref, author_id = _identity(
                login, (raw.get("user") or {}).get("id")
                if isinstance(raw.get("user"), dict) else None)
            normalized["issue"] = {
                "number": number,
                "state": str(raw.get("state") or ""),
                "updated_at": str(raw.get("updated_at") or ""),
                "author_ref": author_ref,
                "author_id": author_id,
                "user_id": ((raw.get("user") or {}).get("id")
                            if isinstance(raw.get("user"), dict) else None),
                "author_association": str(raw.get("author_association") or ""),
                "labels": [item["name"] for item in raw.get("labels") or []],
                "comments": [{"author_ref": _identity(_login(comment))[0],
                              "body": str(comment.get("body") or ""),
                              "created_at": str(comment.get("created_at") or "")}
                             for comment in raw.get("comments") or []],
                "snapshot": {"run_id": run_id, "path": str(snapshot_path), "sha256": sha256},
                "source_availability": ("snapshot_only"
                                        if str(raw.get("state") or "") == "deleted"
                                        else "snapshot"),
            }
            if record_id in existing_ids:
                continue
            handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            existing_ids.add(record_id)
            added += 1

    state_path = study_dir / IMPORTS_RELATIVE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"schema_version": SCHEMA_VERSION, "kind": IMPORTS_KIND,
             "updated_at": _now(), "imports": _read_jsonl(state_path)}
    state["imports"] = [item for item in state["imports"] if item.get("run_id") != run_id]
    state["imports"].append({
        "run_id": run_id, "manifest": str(manifest_path), "snapshot": str(snapshot_path),
        "sha256": sha256, "authorized_by": operator, "record_count": len(snapshot_rows),
        "skipped_private": skipped_private, "selection_bias": bias,
        "filters": {"since": since or None, "label": label or None},
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return {
        "status": "imported",
        "run_id": run_id,
        "snapshot": str(snapshot_path),
        "manifest": str(manifest_path),
        "sha256": sha256,
        "parsed": len(rows),
        "added": added,
        "skipped_duplicates": len(snapshot_rows) - added,
        "skipped_private": skipped_private,
        "skipped_filter": skipped_filter,
        "selection_bias": bias,
        "normalized_file": str(normalized_path),
    }


# --------------------------------------------------------------------------- #
# extraction: records -> machine candidates (deterministic, rule-based)
# --------------------------------------------------------------------------- #

def _sentences(text: str) -> List[Tuple[int, int, str]]:
    out: List[Tuple[int, int, str]] = []
    for match in _SENTENCE.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = match.start() + raw.index(stripped)
        out.append((start, start + len(stripped), stripped))
    return out


def _first(sentences: List[Tuple[int, int, str]],
           markers: Tuple[str, ...]) -> Optional[Tuple[int, int, str]]:
    for sentence in sentences:
        lowered = sentence[2].casefold()
        if any(marker in lowered for marker in markers):
            return sentence
    return None


def _extract_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Rule-extract one record. Every field states where it came from."""
    title = str(record.get("title") or "")
    text = str(record.get("text") or "")
    body = text[len(title) + 2:] if title and text.startswith(title + "\n\n") else text
    body_offset = len(text) - len(body)
    body_sentences = [item for item in _sentences(text) if item[0] >= body_offset]
    lowered_body = body.casefold()
    reproduction = ("```" in body
                    or any(marker in lowered_body for marker in _REPRO_MARKERS))
    workaround = _first(body_sentences, _WORKAROUND_MARKERS)
    consequence = _first(body_sentences, _CONSEQUENCE_MARKERS)
    request = _first(body_sentences, _REQUEST_MARKERS)
    trigger = _first(body_sentences, _TRIGGER_MARKERS)
    task: Optional[Tuple[int, int, str]] = None
    for sentence in body_sentences:
        lowered = sentence[2].casefold()
        if (any(marker in lowered for marker in _FIRST_PERSON)
                and (any(marker in lowered for marker in _WORKAROUND_MARKERS)
                     or any(marker in lowered for marker in _CONSEQUENCE_MARKERS))):
            task = sentence
            break

    if not body.strip():
        claim_kind = "unknown"
    elif reproduction:
        claim_kind = "bug_reproduction"
    elif workaround:
        claim_kind = "observed_behavior"
    elif request:
        claim_kind = "feature_request"
    elif consequence or body_sentences:
        claim_kind = "subjective_complaint"
    else:
        claim_kind = "unknown"

    quote: Optional[Tuple[int, int, str]] = None
    if body.strip():
        if reproduction:
            quote = _first(body_sentences, ("traceback", "exception", "堆栈", "报错信息"))
            quote = quote or _first(body_sentences, ("steps to reproduce", "reproduce", "复现步骤"))
        quote = quote or workaround or consequence or request
        quote = quote or (body_sentences[0] if body_sentences else None)

    if not body.strip():
        confidence_basis = "unverified"
    elif reproduction:
        confidence_basis = "reproducible_text"
    elif quote is not None:
        confidence_basis = "self_report_text"
    else:
        confidence_basis = "unverified"

    labels = [str(name).lower() for name in (record.get("issue") or {}).get("labels") or []]
    severity = _SEVERITY_BY_KIND[claim_kind]
    severity_basis = f"derived from claim_kind={claim_kind}"
    if claim_kind in ("bug_reproduction", "observed_behavior") and _CRITICAL_LABELS & set(labels):
        severity = "critical"
        severity_basis = ("label " + ", ".join(sorted(_CRITICAL_LABELS & set(labels)))
                          + f" with claim_kind={claim_kind}")
    elif claim_kind == "feature_request":
        severity_basis = "a feature request states a desire, not a severity"
    elif claim_kind == "unknown":
        severity_basis = "no quotable text; severity cannot be inferred"

    return {
        "record_id": str(record.get("record_id") or ""),
        "author_ref": str((record.get("issue") or {}).get("author_ref") or ""),
        "title": title,
        "source_text": text,
        "body": body,
        "claim_kind": claim_kind,
        "confidence_basis": confidence_basis,
        "severity_candidate": severity,
        "severity_basis": severity_basis,
        "user_task": task[2] if task else "unknown",
        "trigger": trigger[2] if trigger else "",
        "current_workaround": workaround[2] if workaround else "",
        "failure_consequence": consequence[2] if consequence else "",
        "requested_feature": request[2] if request else "",
        "source_quote_span": ({"start": quote[0], "end": quote[1], "text": quote[2]}
                              if quote else None),
        "counter": any(marker in lowered_body for marker in _COUNTER_MARKERS),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str((record.get("issue") or {}).get("updated_at") or ""),
        "source_availability": str(
            (record.get("issue") or {}).get("source_availability") or "snapshot"),
        "source_snapshot": dict((record.get("issue") or {}).get("snapshot") or {}),
    }


def _tokens(text: str) -> set:
    return {token for token in re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]{2,4}", text.lower())
            if token not in _STOPWORDS}


def _cluster(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Greedy min-overlap clustering: duplicate themes merge, sources never drop."""
    clusters: List[Dict[str, Any]] = []
    for record in records:
        tokens = _tokens(str(record.get("title") or "") + " " + str(record.get("text") or ""))
        best: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for cluster in clusters:
            shared = tokens & cluster["tokens"]
            if len(shared) < 2:
                continue
            score = len(shared) / max(1, min(len(tokens), len(cluster["tokens"])))
            if score >= 0.5 and score > best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append({"tokens": set(tokens), "records": [record]})
        else:
            best["records"].append(record)
            best["tokens"] |= tokens
    return [cluster["records"] for cluster in clusters]


def _representativeness(record_count: int, availability: str) -> str:
    note = (f"one public issue export ({record_count} record(s)); distinct logins are not "
            f"proven distinct people, and a self-selected issue sample cannot represent all users")
    if availability == "snapshot_only":
        note += "; the live source is no longer available, so only the study snapshot can be checked"
    return note


def _identity_basis_note() -> str:
    return ("distinct logins are not proven distinct people (shared accounts, bots, alt accounts); "
            "one login with N issues is still one observed user, and comments on one issue are "
            "context, not independent users")


def _import_context(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir) / IMPORTS_RELATIVE
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    imports = payload.get("imports") if isinstance(payload, dict) else None
    if not isinstance(imports, list) or not imports:
        return {}
    return imports[-1] if isinstance(imports[-1], dict) else {}


def extract_candidates(study_dir: Path, *, question: str = "") -> Dict[str, Any]:
    """Project normalized issue records into machine candidates.

    Re-extraction is deterministic and preserves human decisions: an accepted or
    rejected candidate keeps its status, edits and acceptance reference; only the
    machine-derived fields are refreshed.
    """
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    records = [record for record in _read_jsonl(study_dir / NORMALIZED_RELATIVE)
               if record.get("issue")]
    if not records:
        raise IssueError(
            "no imported issues; run `askovo issues import --file EXPORT --authorized-by NAME`",
            "INPUT_REQUIRED", "candidates come from an authorized local export, never a live read")
    records = [record for record in records
               if _visibility_ok({"visibility": (record.get("issue") or {}).get("visibility")})]
    records.sort(key=lambda record: (str(record.get("created_at") or ""),
                                     str(record.get("record_id") or "")))

    user_records = [record for record in records
                    if not _is_maintainer(record.get("issue") or {})]
    maintainer_records = [record for record in records
                          if _is_maintainer(record.get("issue") or {})]

    previous: Dict[str, Dict[str, Any]] = {}
    if (study_dir / CANDIDATES_RELATIVE).is_file():
        try:
            existing = json.loads((study_dir / CANDIDATES_RELATIVE).read_text(encoding="utf-8"))
            for item in existing.get("candidates") or []:
                if isinstance(item, dict) and item.get("id"):
                    previous[str(item["id"])] = item
        except (OSError, json.JSONDecodeError):
            previous = {}

    context = _import_context(study_dir)
    selection_bias = str(context.get("selection_bias") or "")
    candidates: List[Dict[str, Any]] = []
    maintainer_feedback: List[Dict[str, Any]] = []
    index = 0
    for partition, is_maintainer in ((user_records, False), (maintainer_records, True)):
        for cluster in _cluster(partition):
            index += 1
            candidate_id = f"IC-{index:02d}"
            extractions = [_extract_record(record) for record in cluster]
            support = [item for item in extractions if not item["counter"]]
            counter = [item for item in extractions if item["counter"]]
            primary = support[0] if support else extractions[0]
            availability = primary["source_availability"]
            if counter:
                disposition = "challenged"
            elif len(support) >= 2 and primary["confidence_basis"] != "unverified":
                disposition = "supported_candidate"
            else:
                disposition = "insufficient"
            kind = primary["claim_kind"]
            if kind in ("feature_request", "unknown"):
                demand_claim = "none"
            elif kind == "subjective_complaint":
                demand_claim = "descriptive_only"
            else:
                demand_claim = "problem" if primary["confidence_basis"] != "unverified" else "none"
            candidate = {
                "id": candidate_id,
                "issue_ref": _issue_ref(cluster[0], index),
                "author_ref": primary["author_ref"],
                "created_at": primary["created_at"],
                "updated_at": primary["updated_at"],
                "user_task": primary["user_task"],
                "trigger": primary["trigger"],
                "current_workaround": primary["current_workaround"],
                "failure_consequence": primary["failure_consequence"],
                "requested_feature": primary["requested_feature"],
                "severity_candidate": primary["severity_candidate"],
                "source_quote_span": primary["source_quote_span"],
                "confidence_basis": primary["confidence_basis"],
                "representativeness_warning": _representativeness(len(cluster), availability),
                "source_text": primary["source_text"],
                "claim_kind": kind,
                "severity_basis": primary["severity_basis"],
                "demand_claim": demand_claim,
                "disposition": disposition,
                "support_count": len(support),
                "counter_count": len(counter),
                "majority_wins": False,
                "counter_evidence": [
                    {"record_id": item["record_id"],
                     "quote": (item["source_quote_span"] or {}).get("text")
                              or item["body"][:200]}
                    for item in counter
                ],
                "source_refs": [item["record_id"] for item in extractions],
                "source_availability": availability,
                "source_snapshot": primary["source_snapshot"],
                "maintainer_feedback": is_maintainer,
                "selection_bias": selection_bias,
                "evidence_cap": EVIDENCE_CAP[kind],
                "status": "proposed",
                "edits": [],
                "accepted": None,
                "boundary": (
                    "Machine candidate only: it describes what the export says, never that the "
                    "demand is real. A human edits and accepts it, and evidence levels are "
                    "assigned by that reviewer."
                ),
            }
            previous_item = previous.get(candidate_id) or {}
            for key in ("status", "edits", "accepted"):
                if previous_item.get(key):
                    candidate[key] = previous_item[key]
            if previous_item.get("user_role"):
                candidate["user_role"] = previous_item["user_role"]
            candidates.append(candidate)
            if is_maintainer:
                maintainer_feedback.append({
                    "candidate_id": candidate_id,
                    "issue_ref": candidate["issue_ref"],
                    "author_ref": candidate["author_ref"],
                    "claim_kind": candidate["claim_kind"],
                    "source_ref": candidate["source_refs"][0],
                    "note": "maintainer/company feedback: listed separately, never counted as a user observation",
                })

    comment_count = sum(len((record.get("issue") or {}).get("comments") or [])
                        for record in records)
    comment_authors = {comment.get("author_ref")
                       for record in records
                       for comment in (record.get("issue") or {}).get("comments") or []}
    per_author: Dict[str, int] = {}
    identities: set = set()
    for record in user_records:
        issue = record.get("issue") or {}
        author = str(issue.get("author_ref") or "")
        per_author[author] = per_author.get(author, 0) + 1
        identities.add(str(issue.get("author_id") or author))
    observation = {
        "record_count": len(records),
        "observed_users": len(identities),
        "identity_basis": "login_only",
        "identity_basis_note": _identity_basis_note(),
        "records_per_author": dict(sorted(per_author.items())),
        "max_records_per_author": max(per_author.values()) if per_author else 0,
        "comment_count": comment_count,
        "comment_authors": len(comment_authors),
        "maintainer_records": len(maintainer_records),
        "note": ("records are not users and comments are not records: one issue with many "
                 "comments is still one observation"),
    }
    document = {
        "schema_version": SCHEMA_VERSION,
        "kind": CANDIDATES_KIND,
        "study_id": str(study.get("study_id") or ""),
        "generated_at": _now(),
        "question": question,
        "source": {
            "platform": "github",
            "run_id": context.get("run_id"),
            "snapshot": context.get("snapshot"),
            "sha256": context.get("sha256"),
            "authorized_by": context.get("authorized_by"),
            "selection_bias": selection_bias,
            "filters": context.get("filters") or {},
        },
        "selection_bias": selection_bias,
        "observation": observation,
        "maintainer_feedback": maintainer_feedback,
        "candidates": candidates,
        "boundary": (
            "Candidates are machine candidates. Clustering merges duplicate themes but never "
            "removes a source; a request is not demand; one counter-evidence is not outvoted."
        ),
    }
    document["digest"] = _digest({
        "candidates": [{key: value for key, value in candidate.items()
                        if key not in ("status", "edits", "accepted")}
                       for candidate in candidates],
        "observation": observation,
        "selection_bias": selection_bias,
    })
    (study_dir / CANDIDATES_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (study_dir / CANDIDATES_RELATIVE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def _issue_ref(record: Dict[str, Any], index: int) -> str:
    url = str(record.get("source_url") or "")
    match = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if match:
        return f"github:{match.group(1)}/{match.group(2)}#{match.group(3)}"
    return f"github:{record.get('record_id') or index}"


# --------------------------------------------------------------------------- #
# human review: edit / accept / reject / list / status / report
# --------------------------------------------------------------------------- #

_EDITABLE_FIELDS = set(CANDIDATE_FIELDS) | {"user_role"}
_ACCEPT_FIELDS = {"status", "confidence", "judgment_id", "context_key"}


def _load_candidates(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / CANDIDATES_RELATIVE
    if not path.is_file():
        raise IssueError("no issue candidates yet; run `askovo issues extract STUDY`",
                         "INPUT_REQUIRED")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssueError(f"cannot read issue candidates: {exc}", "INTERNAL_ERROR")
    if not isinstance(document, dict):
        raise IssueError("issue candidates document must be an object", "INTERNAL_ERROR")
    return document


def _save_candidates(study_dir: Path, document: Dict[str, Any]) -> None:
    (Path(study_dir) / CANDIDATES_RELATIVE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find_candidate(document: Dict[str, Any], candidate_id: str) -> Dict[str, Any]:
    wanted = str(candidate_id or "").strip()
    for candidate in document.get("candidates") or []:
        if isinstance(candidate, dict) and str(candidate.get("id")) == wanted:
            return candidate
    raise IssueError(f"unknown candidate {wanted!r}", "INPUT_REQUIRED",
                     "run `askovo issues list STUDY` to see candidate ids")


def _append_trail(study_dir: Path, entry: Dict[str, Any]) -> None:
    path = Path(study_dir) / ACCEPTANCE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "kind": ACCEPTANCE_KIND, **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parse_edits(pairs: List[str]) -> Dict[str, str]:
    edits: Dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in str(pair):
            raise IssueError(f"--set expects field=value, got {pair!r}", "INPUT_REQUIRED")
        key, value = str(pair).split("=", 1)
        key = key.strip()
        if key not in _EDITABLE_FIELDS:
            raise IssueError(
                f"cannot edit field {key!r}; editable: " + ", ".join(sorted(_EDITABLE_FIELDS)),
                "UNSUPPORTED_SCOPE")
        edits[key] = value.strip()
    return edits


def edit_candidate(study_dir: Path, candidate_id: str, *, by: str = "",
                   edits: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Record a human edit. Candidates are never auto-edited."""
    study_dir = Path(study_dir).resolve()
    _study(study_dir)
    operator = str(by or "").strip()
    if not operator:
        raise IssueError("editing a candidate requires a named reviewer (--by NAME)",
                         "AUTH_REQUIRED")
    changes = dict(edits or {})
    if not changes:
        raise IssueError("edit needs at least one --set field=value", "INPUT_REQUIRED")
    document = _load_candidates(study_dir)
    candidate = _find_candidate(document, candidate_id)
    for key, value in changes.items():
        candidate[key] = value
    candidate.setdefault("edits", []).append({
        "by": operator, "at": _now(), "fields": changes,
    })
    _save_candidates(study_dir, document)
    _append_trail(study_dir, {
        "candidate_id": candidate_id, "issue_ref": candidate.get("issue_ref"),
        "status": "edited", "accepted_by": operator, "accepted_at": _now(),
        "edits": changes, "evidence": None, "judgment_id": None, "reason": "",
    })
    return {"status": "edited", "candidate_id": candidate_id, "edits": changes,
            "candidate": candidate}


def _evidence_record(candidate: Dict[str, Any], *, level: str, context_key: str,
                     operator: str) -> Dict[str, Any]:
    source_text = str(candidate.get("source_text") or "")
    quote = (candidate.get("source_quote_span") or {}).get("text") or ""
    return {
        "record_id": str((candidate.get("source_refs") or ["github:unknown"])[0]),
        "context_key": context_key,
        "user_role": str(candidate.get("user_role") or "unknown"),
        "scene_trigger": str(candidate.get("trigger") or "unknown"),
        "task_outcome": str(candidate.get("user_task") or "unknown"),
        "current_substitute": str(candidate.get("current_workaround") or "unknown"),
        "friction_cost": str(candidate.get("failure_consequence") or "unknown"),
        "consequence": str(candidate.get("failure_consequence") or "unknown"),
        "evidence_level": level,
        "evidence_basis": (
            f"issue candidate {candidate.get('id')} ({candidate.get('claim_kind')}, "
            f"confidence_basis={candidate.get('confidence_basis')}); "
            f"accepted by {operator}"),
        "corpus_role": "open_scene",
        "source_family": "github",
        "source_ref": str(candidate.get("issue_ref") or ""),
        "normalized_text_hash": _sha_text(source_text or str(candidate.get("id"))),
        "text": quote or source_text,
        "claim_type": "need",
        "evidence_form": "self_report",
        "platform": "github",
        "issue_candidate_id": str(candidate.get("id") or ""),
        "imported_at": _now(),
        "boundary": (
            "Self-reported public issue text: it supports a stated task or workaround, not "
            "prevalence, payment, or causality."),
    }


def _counter_ids(candidate: Dict[str, Any]) -> List[str]:
    """The candidate's counter-evidence record ids, in a stable order.

    One helper, used by both the judgment and the chain, so the two projections
    cannot disagree (D3: A-03 -> A-04 ``review_signal``).
    """
    ids = [str(item.get("record_id") or "").strip()
           for item in candidate.get("counter_evidence") or [] if isinstance(item, dict)]
    return list(dict.fromkeys([record_id for record_id in ids if record_id]))


def _counter_record(candidate: Dict[str, Any], record_id: str, item: Dict[str, Any], *,
                    operator: str) -> Dict[str, Any]:
    """Canonical evidence record for one counter-evidence id.

    Registered with ``evidence_level: unclassified``: accepting a counter record
    must not assign it a level, and the chain may only cite records the evidence
    store contains (otherwise the brief reports a broken reference).
    """
    quote = str(item.get("quote") or "").strip()
    return {
        "record_id": record_id,
        "context_key": "",
        "user_role": str(candidate.get("user_role") or "unknown"),
        "scene_trigger": "unknown",
        "task_outcome": "unknown",
        "current_substitute": "unknown",
        "friction_cost": "unknown",
        "consequence": "unknown",
        "evidence_level": "unclassified",
        "evidence_basis": (
            f"counter-evidence of issue candidate {candidate.get('id')} "
            f"({candidate.get('claim_kind')}); accepted by {operator}; level not assigned"),
        "corpus_role": "counter",
        "source_family": "github",
        "source_ref": str(candidate.get("issue_ref") or ""),
        "normalized_text_hash": _sha_text(quote or record_id),
        "text": quote,
        "claim_type": "counter",
        "evidence_form": "self_report",
        "platform": "github",
        "issue_candidate_id": str(candidate.get("id") or ""),
        "imported_at": _now(),
        "boundary": (
            "Counter-evidence candidate: it challenges the recommendation, not an "
            "evidence level; human review decides what it means."),
    }


def _judgment(candidate: Dict[str, Any], *, judgment_id: str, record_id: str,
              context_key: str, status: str, operator: str) -> Dict[str, Any]:
    claim_kind = str(candidate.get("claim_kind") or "unknown")
    problem_ids = ([record_id] if claim_kind in ("observed_behavior", "bug_reproduction")
                   else [])
    gaps = [
        "一条公开 issue 自述不足以代表总体；样本与选择偏差需人工说明",
        "无商业行为（付费/留存/复购）证据",
    ]
    if int(candidate.get("counter_count") or 0):
        gaps.append(
            f"{candidate['counter_count']} 条反证需人工裁决：支持数不能自动淹没反证")
    if claim_kind == "feature_request":
        gaps.append("这是方案请求而非行为证据：只能支撑 stated desire（E1）")
    if str(candidate.get("confidence_basis") or "") == "unverified":
        gaps.append("无可复现文本：证据资格保持 unverified")
    return {
        "id": judgment_id,
        "context_key": context_key,
        "title": (str(candidate.get("user_task"))
                  if str(candidate.get("user_task") or "unknown") != "unknown"
                  else str(candidate.get("issue_ref") or "")),
        "user_role": str(candidate.get("user_role") or "unknown"),
        "scene": str(candidate.get("trigger") or "unknown"),
        "task": str(candidate.get("user_task") or "unknown"),
        "current_substitute": str(candidate.get("current_workaround") or "unknown"),
        "friction": str(candidate.get("failure_consequence") or "unknown"),
        "consequence": str(candidate.get("failure_consequence") or "unknown"),
        "solution": str(candidate.get("requested_feature") or "unknown"),
        "acceptance_conditions": "unknown",
        "problem_evidence_ids": problem_ids,
        "solution_evidence_ids": [],
        "commercial_evidence_ids": [],
        "counter_evidence_ids": _counter_ids(candidate),
        "status": status,
        "confidence": "low",
        "gaps": gaps,
        "next_test": "访谈 3 位实际使用者，确认该任务与当前替代做法，并补一条可复现行为证据",
        "issue_candidate_ref": {
            "candidate_id": str(candidate.get("id") or ""),
            "issue_ref": str(candidate.get("issue_ref") or ""),
            "accepted_by": operator,
            "accepted_at": _now(),
        },
    }


_NODE_STATEMENTS = {
    "scene": ("trigger", "issue 中描述的场景/触发"),
    "user": ("user_role", "issue 作者自述的角色（未证明是独立用户）"),
    "pain": ("failure_consequence", "issue 中描述的失败后果"),
    "need": ("user_task", "issue 中描述的用户任务"),
    "feature": ("requested_feature", "issue 中提出的方案请求（请求不是需求）"),
    "product": (None, "候选产品形态：尚未确定"),
    "business": (None, "商业成立需要付费/留存/复购行为证据，当前缺失"),
}


def _chain(candidate: Dict[str, Any], judgment: Dict[str, Any], *, chain_id: str,
           context_key: str, record_id: str,
           status_value: str = "hypothesis") -> Dict[str, Any]:
    """Project the accepted judgment into the canonical seven-node chain.

    Every node states its rationale; only scene/user/pain/need may cite the
    problem evidence the judgment registers, so the chain cannot smuggle
    evidence past the judgment (A17).
    """
    claim_kind = str(candidate.get("claim_kind") or "unknown")
    problem_ids = [record_id] if claim_kind in ("observed_behavior", "bug_reproduction") else []
    nodes: Dict[str, Any] = {}
    for node_name in sure_engine.REASONING_NODES:
        field_name, fallback = _NODE_STATEMENTS[node_name]
        statement = str((candidate.get(field_name) if field_name else "") or "").strip()
        if not statement or statement == "unknown":
            statement = fallback
        nodes[node_name] = {
            "statement": statement,
            "rationale": (
                f"由 issue 候选 {candidate.get('id')} 投影："
                + ("问题/任务链证据已登记在该判断中" if node_name in
                   ("scene", "user", "pain", "need")
                   else "该节点尚无独立证据，保持假设")),
            "status": "hypothesis",
            "evidence_ids": problem_ids if node_name in ("scene", "user", "pain", "need") else [],
            "assumptions": [
                "公开 issue 自述不等于独立用户，也不等于总体比例",
                "样本为自选择公开 issue，选择偏差未校正",
            ],
        }
    return {
        "id": chain_id,
        "title": str(judgment.get("title") or ""),
        "context_key": context_key,
        "demand_judgment_id": str(judgment.get("id") or ""),
        "status": status_value,
        "confidence": "low",
        "next_test": str(judgment.get("next_test") or ""),
        "alternative_explanations": [
            "另一种解释：发帖人只代表自选择样本，目标用户整体可能并不这样任务",
            "另一种解释：这是方案请求而非已发生的行为，真实需求可能更弱",
        ],
        "counter_evidence_ids": _counter_ids(candidate),
        "gaps": list(judgment.get("gaps") or []),
        "supporting_states": {
            "delivery": {"status": "unplanned", "release_plan_ref": ""},
            "outcome": {"status": "unmeasured", "metric_refs": []},
            "causal": {"status": "not-claimed", "experiment_refs": []},
        },
        "nodes": nodes,
        "issue_candidate_ref": {
            "candidate_id": str(candidate.get("id") or ""),
            "issue_ref": str(candidate.get("issue_ref") or ""),
        },
    }


def accept_candidate(study_dir: Path, candidate_id: str, *, by: str = "",
                     judgment_id: str = "", context_key: str = "",
                     evidence_level: str = "", status: str = "hypothesis",
                     edits: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Register one candidate into the canonical evidence + judgment chain.

    A named human is mandatory (``AUTH_REQUIRED``); the evidence level is capped
    by the claim kind, so a feature request can never be registered as observed
    behaviour (``POLICY_DENIED``).
    """
    study_dir = Path(study_dir).resolve()
    _study(study_dir)
    operator = str(by or "").strip()
    if not operator:
        raise IssueError(
            "accepting a candidate requires a named human reviewer (--by NAME)",
            "AUTH_REQUIRED",
            "machine candidates never promote themselves into the chain")
    document = _load_candidates(study_dir)
    candidate = _find_candidate(document, candidate_id)
    if str(candidate.get("status")) == "accepted":
        return {
            "status": "accepted",
            "already_accepted": True,
            "candidate_id": str(candidate.get("id")),
            "evidence_record_id": (candidate.get("accepted") or {}).get("evidence_record_id"),
            "evidence_level": (candidate.get("accepted") or {}).get("evidence_level"),
            "judgment_id": (candidate.get("accepted") or {}).get("judgment_id"),
            "next_required_action": "already accepted; review the judgment and collect the next gap",
        }
    claim_kind = str(candidate.get("claim_kind") or "unknown")
    cap = str(candidate.get("evidence_cap") or EVIDENCE_CAP.get(claim_kind, "E0"))
    level = str(evidence_level or cap).strip().upper()
    if level not in _LEVEL_ORDER:
        raise IssueError(f"unknown evidence_level {level!r}", "INPUT_REQUIRED",
                         "E0, E1, E2, E3, E4-, E4+, E5")
    if _LEVEL_ORDER[level] > _LEVEL_ORDER[cap]:
        raise IssueError(
            f"candidate {candidate_id} is a {claim_kind}; its evidence cap is {cap}, so {level} "
            f"is refused. A feature request states a desire (E1) and cannot be registered as "
            f"observed behaviour", "POLICY_DENIED",
            "record the request as a hypothesis, or collect behaviour evidence first")
    status_value = str(status or "hypothesis").strip()
    if status_value not in ("hypothesis", "needs-validation", "rejected", "deprioritized"):
        raise IssueError(
            f"accepting an issue candidate cannot set status {status_value!r}; a single "
            f"self-reported issue cannot validate a judgment", "POLICY_DENIED",
            "use hypothesis or needs-validation; validated needs the full three-chain evidence")
    changes = dict(edits or {})
    unknown = sorted(set(changes) - _EDITABLE_FIELDS)
    if unknown:
        raise IssueError(
            "cannot edit field(s) " + ", ".join(unknown) + "; editable: "
            + ", ".join(sorted(_EDITABLE_FIELDS)), "UNSUPPORTED_SCOPE")
    for key, value in changes.items():
        candidate[key] = value
    context = str(context_key or "").strip()
    record = _evidence_record(candidate, level=level, context_key=context, operator=operator)
    evidence_path = study_dir / EVIDENCE_RELATIVE
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {str(item.get("record_id")) for item in _read_jsonl(evidence_path)}
    counter_records = [
        _counter_record(candidate, record_id, item, operator=operator)
        for record_id, item in ((str(entry.get("record_id") or "").strip(), entry)
                                for entry in candidate.get("counter_evidence") or []
                                if isinstance(entry, dict))
        if record_id
    ]
    with evidence_path.open("a", encoding="utf-8") as handle:
        if record["record_id"] not in existing_ids:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing_ids.add(record["record_id"])
        for counter_record in counter_records:
            if counter_record["record_id"] in existing_ids:
                continue
            handle.write(json.dumps(counter_record, ensure_ascii=False) + "\n")
            existing_ids.add(counter_record["record_id"])

    judgments_path = study_dir / JUDGMENTS_RELATIVE
    judgments_path.parent.mkdir(parents=True, exist_ok=True)
    judgments: List[Dict[str, Any]] = []
    if judgments_path.is_file():
        try:
            loaded = json.loads(judgments_path.read_text(encoding="utf-8"))
            judgments = [item for item in loaded if isinstance(item, dict)] \
                if isinstance(loaded, list) else []
        except (OSError, json.JSONDecodeError):
            judgments = []
    wanted_id = str(judgment_id or "").strip() or f"D{len(judgments) + 1:02d}"
    judgment = _judgment(candidate, judgment_id=wanted_id, record_id=record["record_id"],
                         context_key=context, status=status_value, operator=operator)
    judgments = [item for item in judgments if str(item.get("id")) != wanted_id]
    judgments.append(judgment)
    judgments_path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

    # The accepted judgment is projected into the canonical seven-node chain: the
    # evidence -> demand-judgments -> product-reasoning join stays the only truth.
    reasoning_path = study_dir / "04-findings" / "product-reasoning.json"
    reasoning: Dict[str, Any] = {}
    if reasoning_path.is_file():
        try:
            loaded = json.loads(reasoning_path.read_text(encoding="utf-8"))
            reasoning = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            reasoning = {}
    chains = [item for item in reasoning.get("chains") or [] if isinstance(item, dict)]
    chain_id = ""
    for item in chains:
        if str(item.get("demand_judgment_id")) == wanted_id:
            chain_id = str(item.get("id") or "")
            break
    if not chain_id:
        taken = {str(item.get("id")) for item in chains}
        position = 1
        while f"PR{position:02d}" in taken:
            position += 1
        chain_id = f"PR{position:02d}"
    chain_status = status_value if status_value in ("rejected", "deprioritized") else "hypothesis"
    chains = [item for item in chains
              if str(item.get("id")) != chain_id
              and str(item.get("demand_judgment_id")) != wanted_id]
    chain = _chain(candidate, judgment, chain_id=chain_id, context_key=context,
                   record_id=record["record_id"], status_value=chain_status)
    chains.append(chain)
    reasoning["chains"] = chains
    reasoning.setdefault("schema_version", "2.0")
    reasoning.setdefault("flow", list(sure_engine.REASONING_NODES))
    reasoning_path.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

    accepted_at = _now()
    candidate["status"] = "accepted"
    candidate["accepted"] = {
        "accepted_by": operator, "accepted_at": accepted_at,
        "evidence_record_id": record["record_id"], "evidence_level": level,
        "judgment_id": wanted_id, "context_key": context,
    }
    candidate.setdefault("edits", []).append({"by": operator, "at": accepted_at,
                                             "fields": changes})
    _save_candidates(study_dir, document)
    _append_trail(study_dir, {
        "candidate_id": str(candidate.get("id")), "issue_ref": candidate.get("issue_ref"),
        "status": "accepted", "accepted_by": operator, "accepted_at": accepted_at,
        "edits": changes,
        "evidence": {"record_id": record["record_id"], "evidence_level": level,
                     "context_key": context},
        "judgment_id": wanted_id, "reason": "",
    })
    return {
        "status": "accepted",
        "already_accepted": False,
        "candidate_id": str(candidate.get("id")),
        "evidence_record_id": record["record_id"],
        "evidence_level": level,
        "judgment_id": wanted_id,
        "judgment": judgment,
        "evidence_file": str(evidence_path),
        "judgments_file": str(judgments_path),
        "chain_id": chain_id,
        "chain_file": str(reasoning_path),
        "next_required_action": (
            "人工复核该判断与缺口，并按需补一条可复现行为证据；accepted 不等于 validated"),
        "boundary": ("验收只把候选写入 canonical 链；判断状态、证据等级代表强度与总体推断"
                     "仍由人工与后续证据决定。"),
    }


def reject_candidate(study_dir: Path, candidate_id: str, *, by: str = "",
                     reason: str = "") -> Dict[str, Any]:
    """Reject a candidate: it never enters the chain, and the reason is recorded."""
    study_dir = Path(study_dir).resolve()
    _study(study_dir)
    operator = str(by or "").strip()
    if not operator:
        raise IssueError("rejecting a candidate requires a named reviewer (--by NAME)",
                         "AUTH_REQUIRED")
    why = str(reason or "").strip()
    if not why:
        raise IssueError("rejecting a candidate requires --reason", "INPUT_REQUIRED",
                         "an unexplained rejection is not reviewable later")
    document = _load_candidates(study_dir)
    candidate = _find_candidate(document, candidate_id)
    candidate["status"] = "rejected"
    candidate["rejected"] = {"by": operator, "at": _now(), "reason": why}
    _save_candidates(study_dir, document)
    _append_trail(study_dir, {
        "candidate_id": str(candidate.get("id")), "issue_ref": candidate.get("issue_ref"),
        "status": "rejected", "accepted_by": operator, "accepted_at": _now(),
        "edits": {}, "evidence": None, "judgment_id": None, "reason": why,
    })
    return {"status": "rejected", "candidate_id": str(candidate.get("id")), "reason": why,
            "next_required_action": "该候选不进入主链；如需重开，请新导出并重新 extract"}


def list_candidates(study_dir: Path, *, status: str = "", claim_kind: str = "",
                    limit: int = 50) -> Dict[str, Any]:
    """List machine candidates, optionally filtered by status or claim kind."""
    document = _load_candidates(Path(study_dir).resolve())
    items = [item for item in document.get("candidates") or [] if isinstance(item, dict)]
    if status:
        items = [item for item in items if str(item.get("status")) == str(status)]
    if claim_kind:
        items = [item for item in items if str(item.get("claim_kind")) == str(claim_kind)]
    return {
        "count": len(items),
        "total": len(document.get("candidates") or []),
        "candidates": items[: max(1, int(limit))],
        "selection_bias": document.get("selection_bias") or "",
        "observation": document.get("observation") or {},
        "artifact": str(Path(study_dir).resolve() / CANDIDATES_RELATIVE),
        "boundary": document.get("boundary") or "",
    }


def status(study_dir: Path) -> Dict[str, Any]:
    """C-01 status projection for issue structuring."""
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    path = study_dir / CANDIDATES_RELATIVE
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "study_id": str(study.get("study_id") or ""),
            "state": "no_data",
            "record_count": 0,
            "observed_users": 0,
            "candidates": 0,
            "proposed": 0,
            "accepted": 0,
            "rejected": 0,
            "challenged": 0,
            "selection_bias": "",
            "next_required_action": (
                "askovo issues import STUDY --file EXPORT.jsonl --authorized-by NAME，"
                "然后 askovo issues extract STUDY"),
            "artifact": None,
            "boundary": "尚未导入任何 issue 导出。",
        }
    document = _load_candidates(study_dir)
    items = [item for item in document.get("candidates") or [] if isinstance(item, dict)]
    proposed = sum(1 for item in items if item.get("status") == "proposed")
    accepted = sum(1 for item in items if item.get("status") == "accepted")
    rejected = sum(1 for item in items if item.get("status") == "rejected")
    challenged = sum(1 for item in items if item.get("disposition") == "challenged")
    observation = document.get("observation") or {}
    if proposed:
        state = "review_required"
        next_action = (f"{proposed} 条候选等待人工编辑/接受："
                       f"askovo issues accept STUDY --candidate IC-01 --by NAME")
    else:
        state = "ready"
        next_action = "候选均已处理：补可复现行为证据或运行 askovo audit STUDY"
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": str(study.get("study_id") or ""),
        "state": state,
        "record_count": int(observation.get("record_count") or 0),
        "observed_users": int(observation.get("observed_users") or 0),
        "identity_basis": observation.get("identity_basis"),
        "maintainer_records": int(observation.get("maintainer_records") or 0),
        "comment_count": int(observation.get("comment_count") or 0),
        "candidates": len(items),
        "proposed": proposed,
        "accepted": accepted,
        "rejected": rejected,
        "challenged": challenged,
        "selection_bias": document.get("selection_bias") or "",
        "next_required_action": next_action,
        "artifact": str(path),
        "boundary": document.get("boundary") or "",
    }


def report(study_dir: Path) -> Dict[str, Any]:
    """Markdown projection of the candidates, with the observation caveats inline."""
    study_dir = Path(study_dir).resolve()
    document = _load_candidates(study_dir)
    observation = document.get("observation") or {}
    lines = [
        "# Issue → 用户任务/需求结构化（机器候选）",
        "",
        f"- 记录数：**{observation.get('record_count', 0)}**；"
        f"观测用户数：**{observation.get('observed_users', 0)}**"
        f"（identity_basis：`{observation.get('identity_basis')}`）",
        f"- 维护者/公司内部反馈：{observation.get('maintainer_records', 0)} 条（单列，不计入用户）",
        f"- 评论数：{observation.get('comment_count', 0)}（评论是语境，不是独立用户）",
        "",
        "> 记录数不是用户数：同一登录发 10 条仍是一名观测用户；不同登录也未证明是不同的人。",
        "",
    ]
    if document.get("selection_bias"):
        lines.extend([f"**选择偏差**：{document['selection_bias']}", ""])
    lines.extend(["## 候选", ""])
    for candidate in document.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        lines.append(
            f"### {candidate.get('id')} · {candidate.get('issue_ref')}"
            f"（`{candidate.get('claim_kind')}` / `{candidate.get('disposition')}`）")
        lines.append("")
        lines.append(f"- 用户任务：{candidate.get('user_task')}")
        lines.append(f"- 触发：{candidate.get('trigger') or '—'}")
        lines.append(f"- 当前替代做法：{candidate.get('current_workaround') or '—'}")
        lines.append(f"- 失败后果：{candidate.get('failure_consequence') or '—'}")
        lines.append(f"- 方案请求：{candidate.get('requested_feature') or '—'}")
        lines.append(f"- 严重度候选：`{candidate.get('severity_candidate')}`"
                     f"（{candidate.get('severity_basis')}）")
        lines.append(f"- 置信基础：`{candidate.get('confidence_basis')}`；"
                     f"证据上限：`{candidate.get('evidence_cap')}`")
        lines.append(f"- 支持 / 反证：{candidate.get('support_count')} / "
                     f"{candidate.get('counter_count')}（多数不淹没反证）")
        lines.append(f"- 状态：`{candidate.get('status')}`")
        lines.append(f"- {candidate.get('representativeness_warning')}")
        lines.append("")
    lines.extend(["## 边界", "", str(document.get("boundary") or ""), ""])
    markdown = "\n".join(lines)
    return {"markdown": markdown, "candidates": len(document.get("candidates") or []),
            "observation": observation}

"""Human review of capture candidates: the only bridge into the evidence store.

`askovo capture page` writes *candidates* under ``01-sources/captures/``. This
module is the review gate the 2026-11-17 review (§2.4/§4.1) requires:

- a capture candidate never promotes itself; a **named human** must accept it
  (``AUTH_REQUIRED`` otherwise);
- acceptance appends exactly one record to the canonical
  ``02-data/evidence.jsonl`` — there is no second fact chain — with full
  back-links (capture id, capture JSON path, URL, screenshot hash) so every
  conclusion can be traced to the collected source;
- a visible page can document context (E0), stated need (E1) or observed
  current practice/friction (E2). It can never prove concept acceptance (E3)
  or payment/retention (E4+/E5); requesting those levels is ``POLICY_DENIED``;
- acceptance writes **no demand judgment and no chain node**: judgments stay
  human-authored through the existing judgment/loop flows;
- accept/reject update the capture document and append to
  ``01-sources/captures/review-trail.jsonl`` as one journalled transaction
  (``write_integrity``), so an interrupted review leaves a recoverable state;
- the ``capture`` source family is declared in ``01-sources/source-plan.csv``
  idempotently, because the audit refuses evidence from an unplanned family.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sure_engine
import write_integrity

EVIDENCE_RELATIVE = Path("02-data/evidence.jsonl")
CAPTURES_RELATIVE = Path("01-sources/captures")
TRAIL_RELATIVE = Path("01-sources/captures/review-trail.jsonl")
SOURCE_PLAN_RELATIVE = Path("01-sources/source-plan.csv")

# askovo.LEVELS is the frozen vocabulary; a visible page tops out at E2
# (observed current practice/friction documented on the page itself).
CAPTURE_EVIDENCE_LEVELS = ("E0", "E1", "E2")
CAPTURE_LEVEL_CAP = "E2"
CORPUS_ROLES = ("direct_solution", "open_scene", "substitute_rejector",
                "post_purchase_support", "control")
SOURCE_FAMILY = "capture"

_SOURCE_PLAN_FIELDS = ("corpus_role", "source_family", "route_or_query", "target_records",
                       "cap_share", "access_status", "known_bias")


class CaptureReviewError(ValueError):
    """A capture review rule was violated; carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INTERNAL_ERROR",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_capture(study_dir: Path, capture_id: str) -> Dict[str, Any]:
    wanted = str(capture_id or "").strip()
    if not wanted:
        raise CaptureReviewError("review needs --capture <capture_id>", "INPUT_REQUIRED",
                                 "run `askovo capture list STUDY` to see candidate ids")
    path = study_dir / CAPTURES_RELATIVE / f"{wanted}.json"
    if not path.is_file():
        raise CaptureReviewError(f"unknown capture {wanted!r}", "INPUT_REQUIRED",
                                 "run `askovo capture list STUDY` to see candidate ids")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureReviewError(
            f"cannot parse capture {wanted}: {type(exc).__name__}: {exc}",
            "INTERNAL_ERROR",
            "repair or delete the capture document; refusing to review a file whose "
            "shape is unknown") from exc
    if not isinstance(payload, dict):
        raise CaptureReviewError(f"capture {wanted} is not a JSON object", "INTERNAL_ERROR")
    return payload


def _read_evidence(study_dir: Path) -> List[Dict[str, Any]]:
    path = study_dir / EVIDENCE_RELATIVE
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaptureReviewError(
                f"cannot parse {EVIDENCE_RELATIVE}: {exc}", "INTERNAL_ERROR",
                "repair the evidence store; refusing to append to a file whose shape "
                "is unknown") from exc
        if isinstance(item, dict):
            records.append(item)
    return records


def _ensure_source_plan(study_dir: Path, *, record_count: int) -> None:
    """Declare the capture family before its records become evidence (idempotent)."""
    path = study_dir / SOURCE_PLAN_RELATIVE
    rows: List[Dict[str, str]] = []
    if path.is_file():
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)
                        if str(row.get("source_family") or "").strip()]
        except OSError as exc:
            raise CaptureReviewError(
                f"cannot read source plan {path}: {type(exc).__name__}: {exc}",
                "INTERNAL_ERROR",
                "repair source-plan.csv; refusing to overwrite a plan whose rows could "
                "not be read") from exc
    if any(str(row.get("source_family")) == SOURCE_FAMILY for row in rows):
        return
    rows.append({
        "corpus_role": "open_scene",
        "source_family": SOURCE_FAMILY,
        "route_or_query": "authorized visible page via local CDP (text/screenshot/OCR)",
        "target_records": str(record_count),
        "cap_share": "0.50",
        "access_status": "available with --ack-terms from an authorized session",
        "known_bias": "visible-page self-report; single-page selection bias, not a population",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_SOURCE_PLAN_FIELDS),
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in _SOURCE_PLAN_FIELDS})


def _capture_text(payload: Dict[str, Any], from_text: str) -> str:
    if from_text == "ocr":
        ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
        text = str(ocr.get("text") or "")
        if not text:
            raise CaptureReviewError(
                "this capture has no OCR text to register", "INPUT_REQUIRED",
                "use --from page, or re-run capture with --ocr on a machine with Vision")
        return text
    return str(payload.get("text") or "")


def _evidence_record(payload: Dict[str, Any], *, level: str, corpus_role: str,
                     context_key: str, operator: str, text: str) -> Dict[str, Any]:
    capture_id = str(payload.get("capture_id") or "")
    capture_rel = str(CAPTURES_RELATIVE / f"{capture_id}.json")
    return {
        "record_id": f"cap-{capture_id}",
        "context_key": context_key,
        "user_role": "unknown",
        "scene_trigger": "unknown",
        "task_outcome": "unknown",
        "current_substitute": "unknown",
        "friction_cost": "unknown",
        "consequence": "unknown",
        "evidence_level": level,
        "evidence_basis": (
            f"capture candidate {capture_id} ({payload.get('url')}); reviewed and "
            f"accepted by {operator}"),
        "corpus_role": corpus_role,
        "source_family": SOURCE_FAMILY,
        "source_ref": capture_rel,
        "normalized_text_hash": _sha_text(text),
        "text": text,
        "claim_type": "need",
        "evidence_form": "self_report",
        "platform": "web",
        "capture_id": capture_id,
        "capture_url": str(payload.get("url") or ""),
        "capture_screenshot": str(payload.get("screenshot") or ""),
        "capture_text_sha256": str(payload.get("text_sha256") or ""),
        "capture_ocr_text_sha256": str(
            (payload.get("ocr") or {}).get("text_sha256") or ""),
        "reviewed_by": operator,
        "reviewed_at": _now(),
        "imported_at": sure_engine.now(),
        "boundary": (
            "Single authorized visible page (self-report): it documents what this page "
            "says, not population prevalence, causality or payment."),
    }


def list_candidates(study_dir: Path) -> Dict[str, Any]:
    captures_dir = Path(study_dir).resolve() / CAPTURES_RELATIVE
    captures: List[Dict[str, Any]] = []
    if captures_dir.is_dir():
        for path in sorted(captures_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                captures.append({"capture_id": path.stem, "evidence_status": "unreadable"})
                continue
            if not isinstance(payload, dict):
                continue
            captures.append({
                "capture_id": str(payload.get("capture_id") or path.stem),
                "captured_at": payload.get("captured_at"),
                "url": payload.get("url"),
                "title": payload.get("title"),
                "text_length": payload.get("text_length"),
                "ocr_error": (payload.get("ocr") or {}).get("error") or "",
                "evidence_status": payload.get("evidence_status") or "candidate",
                "record_id": f"cap-{payload.get('capture_id') or path.stem}",
            })
    return {"status": "listed", "captures": captures,
            "note": "candidates only; `capture accept --by NAME` registers evidence"}


def accept(study_dir: Path, capture_id: str, *, by: str = "",
           evidence_level: str = "E1", corpus_role: str = "open_scene",
           context_key: str = "", from_text: str = "page") -> Dict[str, Any]:
    """Register one reviewed capture into the canonical evidence store."""
    study_dir = Path(study_dir).resolve()
    operator = str(by or "").strip()
    if not operator:
        raise CaptureReviewError(
            "accepting a capture requires a named human reviewer (--by NAME)",
            "AUTH_REQUIRED",
            "a capture candidate never promotes itself into the evidence store")
    level = str(evidence_level or "E1").strip().upper()
    if level not in CAPTURE_EVIDENCE_LEVELS:
        raise CaptureReviewError(
            f"a visible page cannot support evidence_level {level!r}: allowed "
            f"{'/'.join(CAPTURE_EVIDENCE_LEVELS)} (cap {CAPTURE_LEVEL_CAP})",
            "POLICY_DENIED",
            "acceptance or payment needs concept tests (E3) or transactions (E4+/E5), "
            "not a page capture")
    if corpus_role not in CORPUS_ROLES:
        raise CaptureReviewError(
            f"unknown corpus_role {corpus_role!r}; choose from: "
            + ", ".join(CORPUS_ROLES), "INPUT_REQUIRED")
    if from_text not in ("page", "ocr"):
        raise CaptureReviewError("--from must be page or ocr", "INPUT_REQUIRED")
    payload = _load_capture(study_dir, capture_id)
    capture_id = str(payload.get("capture_id") or capture_id)
    status = str(payload.get("evidence_status") or "candidate")
    if status == "rejected":
        raise CaptureReviewError(
            f"capture {capture_id} was rejected on review and stays rejected",
            "POLICY_DENIED", "capture the page again if it must be re-reviewed")
    text = _capture_text(payload, from_text)
    record_id = f"cap-{capture_id}"
    _ensure_source_plan(study_dir, record_count=1)
    try:
        with write_integrity.Transaction(
                study_dir, purpose=f"capture accept {capture_id}",
                meta={"capture_id": capture_id, "operator": operator}) as txn:
            records = _read_evidence(study_dir)
            existing = {str(item.get("record_id")) for item in records}
            if status == "accepted":
                if record_id not in existing:
                    raise CaptureReviewError(
                        f"capture {capture_id} is marked accepted but evidence record "
                        f"{record_id} is missing from {EVIDENCE_RELATIVE}",
                        "INTERNAL_ERROR",
                        "restore the evidence record or reset the capture to candidate; "
                        "an accepted flag without its record is not success")
                review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
                return {
                    "status": "accepted",
                    "already_accepted": True,
                    "capture_id": capture_id,
                    "evidence_record_id": record_id,
                    "evidence_level": review.get("evidence_level") or level,
                    "next_required_action": "already accepted; analyze or collect the next gap",
                }
            record = _evidence_record(payload, level=level, corpus_role=corpus_role,
                                      context_key=str(context_key or "").strip(),
                                      operator=operator, text=text)
            if record_id not in existing:
                txn.add(EVIDENCE_RELATIVE,
                        json.dumps(record, ensure_ascii=False) + "\n", mode="append")
            payload["evidence_status"] = "accepted"
            payload["review"] = {
                "reviewed_by": operator, "reviewed_at": _now(),
                "action": "accepted", "evidence_level": level,
                "corpus_role": corpus_role, "from_text": from_text,
                "evidence_record_id": record_id,
            }
            txn.add(CAPTURES_RELATIVE / f"{capture_id}.json",
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    mode="replace")
            txn.add(TRAIL_RELATIVE, json.dumps({
                "capture_id": capture_id, "action": "accepted",
                "reviewed_by": operator, "reviewed_at": _now(),
                "evidence_record_id": record_id, "evidence_level": level,
                "corpus_role": corpus_role, "from_text": from_text, "reason": "",
            }, ensure_ascii=False) + "\n", mode="append")
            txn.commit()
            return {
                "status": "accepted",
                "already_accepted": False,
                "capture_id": capture_id,
                "evidence_record_id": record_id,
                "evidence_level": level,
                "evidence_file": str(study_dir / EVIDENCE_RELATIVE),
                "next_required_action": (
                    "record is in the evidence store; run `askovo analyze` and review "
                    "judgments — acceptance registers no demand judgment"),
            }
    except write_integrity.IntegrityError as exc:
        raise CaptureReviewError(
            f"write integrity failure: {exc}", "INTERNAL_ERROR",
            "inspect 05-audit write journal; the review is recoverable") from exc


def reject(study_dir: Path, capture_id: str, *, by: str = "", reason: str = "") -> Dict[str, Any]:
    """Mark a candidate rejected; the evidence store is never touched."""
    study_dir = Path(study_dir).resolve()
    operator = str(by or "").strip()
    if not operator:
        raise CaptureReviewError(
            "rejecting a capture requires a named human reviewer (--by NAME)",
            "AUTH_REQUIRED")
    rationale = str(reason or "").strip()
    if not rationale:
        raise CaptureReviewError("reject needs --reason (why this page is not evidence)",
                                 "INPUT_REQUIRED")
    payload = _load_capture(study_dir, capture_id)
    capture_id = str(payload.get("capture_id") or capture_id)
    try:
        with write_integrity.Transaction(
                study_dir, purpose=f"capture reject {capture_id}",
                meta={"capture_id": capture_id, "operator": operator}) as txn:
            payload["evidence_status"] = "rejected"
            payload["review"] = {
                "reviewed_by": operator, "reviewed_at": _now(),
                "action": "rejected", "reason": rationale,
            }
            txn.add(CAPTURES_RELATIVE / f"{capture_id}.json",
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    mode="replace")
            txn.add(TRAIL_RELATIVE, json.dumps({
                "capture_id": capture_id, "action": "rejected",
                "reviewed_by": operator, "reviewed_at": _now(),
                "evidence_record_id": None, "reason": rationale,
            }, ensure_ascii=False) + "\n", mode="append")
            txn.commit()
            return {"status": "rejected", "capture_id": capture_id,
                    "evidence_written": False,
                    "next_required_action": "candidate stays out of the evidence store"}
    except write_integrity.IntegrityError as exc:
        raise CaptureReviewError(f"write integrity failure: {exc}", "INTERNAL_ERROR") from exc

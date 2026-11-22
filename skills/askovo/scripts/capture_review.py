"""Named-human review is the only bridge from page captures into evidence.

``askovo capture page`` writes untrusted candidates under
``01-sources/captures/``. Acceptance normalizes one reviewed record through the
existing import normalizer and appends it to the canonical
``02-data/evidence.jsonl``. It never authors a demand judgment, a seven-node
chain, a decision record, or a business conclusion.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import sure_engine
import write_integrity

EVIDENCE_RELATIVE = Path("02-data/evidence.jsonl")
CAPTURES_RELATIVE = Path("01-sources/captures")
TRAIL_RELATIVE = Path("01-sources/captures/review-trail.jsonl")
SOURCE_PLAN_RELATIVE = Path("01-sources/source-plan.csv")

# A visible page can document context, a stated need, or current practice. A
# reviewer may choose a lower level, but OCR/capture never unlocks E3/E4/E5 on
# its own: E3 is reachable only through an explicit concept-test record.
CAPTURE_EVIDENCE_LEVELS = ("E0", "E1", "E2")
CAPTURE_LEVEL_CAP = "E2"
CAPTURE_CONCEPT_LEVEL = "E3"
CONCEPT_TEST_FIELDS = ("stimulus", "sample_size", "response_metric", "result")
# Evidence levels are derived from the source type, the reviewed text and the
# reviewer's observation — never taken from a self-declared --evidence-level.
# The flag is only a cap; a request above the derivation is registered lower.
LEVEL_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3}
LEVEL_DERIVATION_VERSION = "askovo-level-derivation/1"
LEVEL_MIN_SUBSTANTIVE_CHARS = 20
OBSERVATION_MODES = ("context", "statement", "practice")
CORPUS_ROLES = ("direct_solution", "open_scene", "substitute_rejector",
                "post_purchase_support", "control")
SOURCE_FAMILY = "capture"
CAPTURE_SCHEMA = "askovo.page-capture/1"

_SOURCE_PLAN_FIELDS = ("corpus_role", "source_family", "route_or_query", "target_records",
                       "cap_share", "access_status", "known_bias")
_PROVENANCE_FIELDS = (
    "platform", "capture_id", "capture_url", "capture_final_url", "capture_platform",
    "capture_screenshot", "capture_screenshot_ref", "capture_screenshot_sha256",
    "capture_text_sha256", "capture_ocr_engine", "capture_ocr_text",
    "capture_ocr_text_sha256", "capture_text_source", "captured_at", "collected_at",
    "source_url", "text_excerpt", "reviewed_by", "reviewed_at", "human_review_status",
    "review_confirmation", "boundary",
)


class CaptureReviewError(ValueError):
    """A capture review rule was violated; carries a stable reason code."""

    def __init__(self, message: str, reason_code: str = "INTERNAL_ERROR",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


def _now() -> str:
    return sure_engine.now()


def _sha_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bare_sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _capture_path(study_dir: Path, capture_id: str) -> Path:
    wanted = str(capture_id or "").strip()
    if not wanted or wanted in {".", ".."} or Path(wanted).name != wanted:
        raise CaptureReviewError(
            "review needs a safe --capture <capture_id>", "INPUT_REQUIRED",
            "run `askovo capture list STUDY` to see candidate ids")
    return study_dir / CAPTURES_RELATIVE / f"{wanted}.json"


def _load_capture(study_dir: Path, capture_id: str) -> Dict[str, Any]:
    path = _capture_path(study_dir, capture_id)
    wanted = path.stem
    if not path.is_file():
        raise CaptureReviewError(f"unknown capture {wanted!r}", "INPUT_REQUIRED",
                                 "run `askovo capture list STUDY` to see candidate ids")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureReviewError(
            f"cannot parse capture {wanted}: {type(exc).__name__}: {exc}",
            "INTERNAL_ERROR",
            "repair the capture document; refusing to review an unreadable file") from exc
    if not isinstance(payload, dict):
        raise CaptureReviewError(f"capture {wanted} is not a JSON object", "INTERNAL_ERROR")
    if str(payload.get("capture_id") or "") != wanted:
        raise CaptureReviewError(
            f"capture id mismatch: filename is {wanted!r}, payload says "
            f"{payload.get('capture_id')!r}", "INTERNAL_ERROR")
    return payload


def _read_evidence(study_dir: Path) -> List[Dict[str, Any]]:
    try:
        return write_integrity.read_jsonl(
            study_dir / EVIDENCE_RELATIVE, missing_ok=True,
            label="canonical evidence store")
    except write_integrity.IntegrityError as exc:
        raise CaptureReviewError(str(exc), "INTERNAL_ERROR",
                                 "repair the evidence store; no review was written") from exc


def _source_plan_payload(study_dir: Path) -> Optional[bytes]:
    """Return a non-destructive source-plan update, or None when already declared."""
    path = study_dir / SOURCE_PLAN_RELATIVE
    rows: List[Dict[str, str]] = []
    fields: List[str] = list(_SOURCE_PLAN_FIELDS)
    if path.is_file():
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = list(reader.fieldnames or fields)
                for required in _SOURCE_PLAN_FIELDS:
                    if required not in fields:
                        fields.append(required)
                rows = [dict(row) for row in reader
                        if str(row.get("source_family") or "").strip()]
        except (OSError, csv.Error) as exc:
            raise CaptureReviewError(
                f"cannot read source plan {path}: {type(exc).__name__}: {exc}",
                "INTERNAL_ERROR",
                "repair source-plan.csv; refusing to overwrite an unreadable plan") from exc
    if any(str(row.get("source_family")) == SOURCE_FAMILY for row in rows):
        return None
    rows.append({
        "corpus_role": "open_scene",
        "source_family": SOURCE_FAMILY,
        "route_or_query": "reviewed authorized visible page via local CDP (text/screenshot/OCR)",
        "target_records": "1",
        "cap_share": "0.50",
        "access_status": "candidate accepted by a named human reviewer",
        "known_bias": "operator-selected visible page; OCR can err; not a population sample",
    })
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    return output.getvalue().encode("utf-8")


def _capture_text(payload: Dict[str, Any], from_text: str) -> str:
    if from_text == "ocr":
        ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
        text = str(ocr.get("text") or "")
    else:
        text = str(payload.get("text") or "")
    if not text.strip():
        raise CaptureReviewError(
            f"this capture has no {from_text} text to register", "INPUT_REQUIRED",
            "choose --from with actual text, or reject the candidate; no text may be invented")
    return text


def derive_capture_level(text: str, from_text: str, observation: str = "",
                         concept_test: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Derive the evidence level from source type, text substance and review mode.

    A self-declared level is never trusted: the reviewer can request a lower cap,
    never a higher level. A visible page is at most one voiced statement (E1) or
    a documented current practice (E2); E3 exists only through a concept-test
    record, and thin or context-only material stays E0.
    """
    normalized = str(observation or "").strip().lower()
    if normalized and normalized not in OBSERVATION_MODES:
        raise CaptureReviewError(
            f"unknown --observation {observation!r}; choose from: "
            + ", ".join(OBSERVATION_MODES), "INPUT_REQUIRED",
            "context = surroundings only; statement = one voiced statement; "
            "practice = an observed or documented current workflow/spend")
    visible_chars = len("".join(str(text or "").split()))
    inputs = {
        "from_text": from_text,
        "observation": normalized or "statement",
        "visible_chars": visible_chars,
        "min_substantive_chars": LEVEL_MIN_SUBSTANTIVE_CHARS,
        "concept_test": bool(concept_test),
    }
    if concept_test:
        return {
            "level": CAPTURE_CONCEPT_LEVEL,
            "basis": (
                f"derived E3 from a concept-test record (n={concept_test.get('sample_size')}, "
                f"metric={concept_test.get('response_metric')}); source={from_text}"),
            "inputs": inputs,
        }
    if visible_chars < LEVEL_MIN_SUBSTANTIVE_CHARS:
        return {
            "level": "E0",
            "basis": (
                f"derived E0: reviewed text has {visible_chars} visible characters "
                f"(minimum {LEVEL_MIN_SUBSTANTIVE_CHARS}); a page fragment is context, "
                "not a voiced need or a practice"),
            "inputs": inputs,
        }
    if normalized == "context":
        return {
            "level": "E0",
            "basis": "derived E0: the reviewer marked this material as surrounding context",
            "inputs": inputs,
        }
    if normalized == "practice":
        if from_text == "ocr":
            return {
                "level": "E1",
                "basis": (
                    "derived E1: practice was marked, but OCR transcription cannot evidence "
                    "a documented workflow/spend; use the human-read page text for E2"),
                "inputs": inputs,
            }
        return {
            "level": "E2",
            "basis": (
                "derived E2: reviewer observed a documented current practice/workflow/spend "
                "on the page"),
            "inputs": inputs,
        }
    return {
        "level": "E1",
        "basis": (
            "derived E1: one visible page statement (a voiced need/opinion); E2 requires "
            "an explicit --observation practice"),
        "inputs": inputs,
    }


def _validate_capture_material(study_dir: Path, payload: Dict[str, Any]) -> str:
    """Verify that the reviewed bytes are the governed bytes that were captured."""
    capture_id = str(payload.get("capture_id") or "")
    if payload.get("schema") != CAPTURE_SCHEMA:
        raise CaptureReviewError(
            f"capture {capture_id} has unsupported schema {payload.get('schema')!r}",
            "POLICY_DENIED", "only governed page-capture candidates can be accepted")
    if payload.get("ack_terms") is not True:
        raise CaptureReviewError(
            "capture has no explicit terms/authorization acknowledgement", "AUTH_REQUIRED")
    if not str(payload.get("captured_at") or "").strip():
        raise CaptureReviewError("capture has no captured_at timestamp", "INTERNAL_ERROR")
    original_url = str(payload.get("url") or "")
    source_url = str(payload.get("final_url") or original_url)
    original_platform = sure_engine._platform_for_capture_host(
        urllib.parse.urlparse(original_url).hostname or "")
    platform = sure_engine._platform_for_capture_host(
        urllib.parse.urlparse(source_url).hostname or "")
    if platform not in sure_engine.CDP_TARGET_HOSTS or original_platform != platform:
        raise CaptureReviewError(
            "capture source is outside the approved CDP platform set or changed platform",
            "POLICY_DENIED",
            "Blocked platforms, changed platforms and arbitrary hosts never use the CDP exception")
    try:
        sure_engine._validate_cdp_target(platform, original_url)
        sure_engine._validate_cdp_target(platform, source_url)
    except ValueError as exc:
        raise CaptureReviewError(str(exc), "POLICY_DENIED") from exc
    if str(payload.get("capture_platform") or "") != platform:
        raise CaptureReviewError("capture platform does not match its final URL", "INTERNAL_ERROR")
    governance = payload.get("governance") if isinstance(payload.get("governance"), dict) else {}
    required_governance = {
        "scope": "allowed_sources_matched", "adapter": "enabled",
        "registry_review": "current", "challenge_check": "passed", "cdp_loopback": True,
    }
    for field, expected in required_governance.items():
        if governance.get(field) != expected:
            raise CaptureReviewError(
                f"capture governance check {field!r} is missing or not passed",
                "POLICY_DENIED", "re-capture through the governed capture page entry")

    text = str(payload.get("text") or "")
    if str(payload.get("text_sha256") or "") != _bare_sha_text(text):
        raise CaptureReviewError("page text hash mismatch; candidate may have changed",
                                 "INTERNAL_ERROR")
    ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
    ocr_text = str(ocr.get("text") or "")
    if str(ocr.get("text_sha256") or "") != _bare_sha_text(ocr_text):
        raise CaptureReviewError("OCR text hash mismatch; candidate may have changed",
                                 "INTERNAL_ERROR")
    screenshot = study_dir / CAPTURES_RELATIVE / f"{capture_id}.png"
    if not screenshot.is_file():
        raise CaptureReviewError(f"capture screenshot is missing: {screenshot}", "INTERNAL_ERROR")
    try:
        screenshot_hash = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    except OSError as exc:
        raise CaptureReviewError(f"cannot read capture screenshot: {exc}", "INTERNAL_ERROR") from exc
    if str(payload.get("screenshot_sha256") or "") != screenshot_hash:
        raise CaptureReviewError("screenshot hash mismatch; candidate may have changed",
                                 "INTERNAL_ERROR")
    return platform


def _evidence_record(payload: Dict[str, Any], *, level: str, corpus_role: str,
                     context_key: str, operator: str, reviewed_at: str, text: str,
                     from_text: str, platform: str,
                     concept_test: Optional[Dict[str, Any]] = None,
                     level_basis: str = "", requested_level: str = "",
                     observation: str = "") -> Dict[str, Any]:
    """Reuse the existing import normalization for the canonical evidence fields."""
    capture_id = str(payload.get("capture_id") or "")
    capture_rel = str(CAPTURES_RELATIVE / f"{capture_id}.json")
    screenshot_rel = str(CAPTURES_RELATIVE / f"{capture_id}.png")
    ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
    source_url = str(payload.get("final_url") or payload.get("url") or "")
    basis = (
        f"capture candidate {capture_id} ({source_url}); human-reviewed text "
        f"source={from_text}; accepted by {operator}")
    if concept_test:
        basis += (
            f"; E3 concept test: stimulus={concept_test.get('stimulus')}; "
            f"n={concept_test.get('sample_size')}; "
            f"metric={concept_test.get('response_metric')}; "
            f"result={concept_test.get('result')}")
    raw = {
        "record_id": f"cap-{capture_id}",
        "context_key": context_key,
        "user_role": "unknown",
        "scene_trigger": "unknown",
        "task_outcome": "unknown",
        "current_substitute": "unknown",
        "friction_cost": "unknown",
        "consequence": "unknown",
        "evidence_level": level,
        "evidence_basis": basis,
        "corpus_role": corpus_role,
        "source_family": SOURCE_FAMILY,
        "source_ref": capture_rel,
        "normalized_text_hash": _sha_text(text),
        "text": text,
        "claim_type": "context" if level == "E0" else "need",
        "evidence_form": "self_report",
        "method_id": "capture_human_review",
        "platform": "web",
    }
    defaults = {
        "source_family": SOURCE_FAMILY,
        "source_ref": capture_rel,
        "claim_type": raw["claim_type"],
        "evidence_form": "self_report",
        "method_id": "capture_human_review",
        "product_domain": "unknown",
    }
    record = sure_engine._normalize_record(raw, 1, defaults)
    record["level_derivation_version"] = LEVEL_DERIVATION_VERSION
    record["level_basis"] = level_basis
    record["requested_evidence_level"] = requested_level
    record["level_observation"] = observation
    provenance = {
        "platform": "web",
        "capture_id": capture_id,
        "capture_url": str(payload.get("url") or ""),
        "capture_final_url": source_url,
        "capture_platform": platform,
        "capture_screenshot": str(payload.get("screenshot") or ""),
        "capture_screenshot_ref": screenshot_rel,
        "capture_screenshot_sha256": str(payload.get("screenshot_sha256") or ""),
        "capture_text_sha256": str(payload.get("text_sha256") or ""),
        "capture_ocr_engine": str(ocr.get("engine") or ""),
        "capture_ocr_text": str(ocr.get("text") or ""),
        "capture_ocr_text_sha256": str(ocr.get("text_sha256") or ""),
        "capture_text_source": from_text,
        "captured_at": str(payload.get("captured_at") or ""),
        "collected_at": str(payload.get("captured_at") or ""),
        "source_url": source_url,
        "text_excerpt": text,
        "reviewed_by": operator,
        "reviewed_at": reviewed_at,
        "human_review_status": "reviewed",
        "review_confirmation": "named_human_accept",
        "boundary": (
            "One authorized visible page; OCR may contain recognition errors. Human "
            "acceptance registers this record only: no prevalence, causality, product "
            "acceptance, payment, business decision, or decision adoption is inferred."),
    }
    for key in _PROVENANCE_FIELDS:
        record[key] = provenance[key]
    return record


def validate_evidence_record(study_dir: Path, record: Dict[str, Any]) -> List[str]:
    """Audit one capture evidence row and its reviewed source join.

    The CLI evidence gate calls this for every ``source_family=capture`` row, so
    manually appending an unreviewed OCR row cannot bypass ``capture accept``.
    """
    study_dir = Path(study_dir).resolve()
    record_id = str(record.get("record_id") or "<unknown>")
    errors: List[str] = []
    capture_id = str(record.get("capture_id") or "")
    if record_id != f"cap-{capture_id}" or not capture_id:
        return [f"{record_id} capture record_id/capture_id join is invalid"]
    for field in ("reviewed_by", "reviewed_at", "source_url", "capture_screenshot_ref",
                  "capture_screenshot_sha256", "capture_text_sha256",
                  "capture_ocr_text_sha256"):
        if not str(record.get(field) or "").strip():
            errors.append(f"{record_id} missing reviewed capture provenance: {field}")
    if record.get("human_review_status") != "reviewed":
        errors.append(f"{record_id} is not marked human_review_status=reviewed")
    if record.get("review_confirmation") != "named_human_accept":
        errors.append(f"{record_id} has no named-human acceptance confirmation")
    try:
        payload = _load_capture(study_dir, capture_id)
        if payload.get("evidence_status") != "accepted":
            errors.append(f"{record_id} source capture is not accepted")
        review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
        if str(review.get("evidence_record_id") or "") != record_id:
            errors.append(f"{record_id} is not the capture's accepted evidence record")
        if str(review.get("reviewed_by") or "") != str(record.get("reviewed_by") or ""):
            errors.append(f"{record_id} reviewer differs from the capture review")
        if str(review.get("reviewed_at") or "") != str(record.get("reviewed_at") or ""):
            errors.append(f"{record_id} review timestamp differs from the capture review")
        record_level = str(record.get("evidence_level") or "")
        if record_level not in CAPTURE_EVIDENCE_LEVELS + (CAPTURE_CONCEPT_LEVEL,):
            errors.append(f"{record_id} exceeds the capture E0/E1/E2 level cap")
        if record_level == CAPTURE_CONCEPT_LEVEL:
            concept = review.get("concept_test") if isinstance(review.get("concept_test"), dict) else {}
            missing = [name for name in CONCEPT_TEST_FIELDS
                       if not str(concept.get(name) or "").strip()]
            if missing:
                errors.append(f"{record_id} E3 record lacks a concept-test record: "
                              + ", ".join(missing))
        for review_field, record_field in (
                ("evidence_level", "evidence_level"), ("corpus_role", "corpus_role"),
                ("context_key", "context_key"), ("from_text", "capture_text_source"),
                ("requested_evidence_level", "requested_evidence_level"),
                ("level_basis", "level_basis"),
                ("level_derivation_version", "level_derivation_version"),
                ("level_observation", "level_observation")):
            if str(review.get(review_field) or "") != str(record.get(record_field) or ""):
                errors.append(f"{record_id} {record_field} differs from the capture review")
        platform = _validate_capture_material(study_dir, payload)
        expected_ref = str(CAPTURES_RELATIVE / f"{capture_id}.json")
        if str(record.get("source_ref") or "") != expected_ref:
            errors.append(f"{record_id} source_ref must be {expected_ref}")
        comparisons = {
            "source_url": str(payload.get("final_url") or payload.get("url") or ""),
            "capture_url": str(payload.get("url") or ""),
            "capture_final_url": str(payload.get("final_url") or payload.get("url") or ""),
            "captured_at": str(payload.get("captured_at") or ""),
            "capture_screenshot_ref": str(CAPTURES_RELATIVE / f"{capture_id}.png"),
            "capture_screenshot_sha256": str(payload.get("screenshot_sha256") or ""),
            "capture_text_sha256": str(payload.get("text_sha256") or ""),
            "capture_ocr_text_sha256": str((payload.get("ocr") or {}).get("text_sha256") or ""),
            "capture_ocr_text": str((payload.get("ocr") or {}).get("text") or ""),
            "capture_platform": platform,
        }
        for field, expected in comparisons.items():
            if str(record.get(field) or "") != expected:
                errors.append(f"{record_id} {field} does not match its reviewed capture")
        selected_text = (str((payload.get("ocr") or {}).get("text") or "")
                         if record.get("capture_text_source") == "ocr"
                         else str(payload.get("text") or ""))
        if str(record.get("text") or "") != selected_text:
            errors.append(f"{record_id} text differs from its reviewed page/OCR source")
        if str(record.get("normalized_text_hash") or "") != _sha_text(selected_text):
            errors.append(f"{record_id} normalized_text_hash does not match the reviewed text")
        derivation_version = str(record.get("level_derivation_version") or "")
        if derivation_version:
            if derivation_version != LEVEL_DERIVATION_VERSION:
                errors.append(
                    f"{record_id} level derivation version {derivation_version!r} is unknown")
            concept_for_derive = (review.get("concept_test")
                                  if isinstance(review.get("concept_test"), dict) else None)
            try:
                derived = derive_capture_level(
                    selected_text, str(review.get("from_text") or "page"),
                    observation=str(review.get("level_observation")
                                    or record.get("level_observation") or ""),
                    concept_test=concept_for_derive)
            except CaptureReviewError as exc:
                errors.append(f"{record_id} level derivation failed: {exc}")
            else:
                if record_level != derived["level"]:
                    errors.append(
                        f"{record_id} evidence_level {record_level!r} does not match the "
                        f"derived level {derived['level']!r}; a self-declared level is not "
                        "evidence")
                if not str(record.get("level_basis") or "").strip():
                    errors.append(f"{record_id} missing level_basis")
    except CaptureReviewError as exc:
        errors.append(f"{record_id} reviewed source validation failed: {exc}")
    return errors


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
            "note": "candidates only; `capture accept --by NAME [--observation ...]` "
                    "registers evidence; the evidence level is derived, not self-declared"}


def _load_concept_test(path: Path) -> Dict[str, Any]:
    """Load the reviewer-supplied concept-test record that is the only route to E3."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CaptureReviewError(
            f"cannot read --concept-test {path}: {exc}", "INPUT_REQUIRED",
            "write the concept-test record as JSON before accepting E3") from exc
    except json.JSONDecodeError as exc:
        raise CaptureReviewError(
            f"--concept-test {path} is not valid JSON: {exc}", "INPUT_REQUIRED") from exc
    if not isinstance(data, dict):
        raise CaptureReviewError(
            "--concept-test must be a JSON object", "INPUT_REQUIRED")
    missing = [name for name in CONCEPT_TEST_FIELDS
               if not str(data.get(name) or "").strip()]
    if missing:
        raise CaptureReviewError(
            "concept-test record is missing: " + ", ".join(missing), "INPUT_REQUIRED",
            "E3 概念测试必须写明 stimulus（给被试看的刺激物）、sample_size（有效样本数）、"
            "response_metric（读数指标）、result（读数结果）")
    try:
        sample_size = int(str(data.get("sample_size")).strip())
    except (TypeError, ValueError) as exc:
        raise CaptureReviewError(
            "concept-test sample_size must be a positive integer", "INPUT_REQUIRED") from exc
    if sample_size <= 0:
        raise CaptureReviewError(
            "concept-test sample_size must be a positive integer", "INPUT_REQUIRED")
    return {name: data.get(name) for name in CONCEPT_TEST_FIELDS}


def accept(study_dir: Path, capture_id: str, *, by: str = "",
           evidence_level: str = "", corpus_role: str = "open_scene",
           context_key: str = "", from_text: str = "page",
           concept_test: Optional[Path] = None,
           observation: str = "") -> Dict[str, Any]:
    """Register one explicitly reviewed capture into canonical evidence.

    ``evidence_level`` is a requested cap only: the registered level is derived
    from the source type, the reviewed text and the reviewer's observation, and a
    request above the derivation is downgraded (``level_capped``).
    """
    study_dir = Path(study_dir).resolve()
    operator = str(by or "").strip()
    if not operator:
        raise CaptureReviewError(
            "accepting a capture requires a named human reviewer (--by NAME)",
            "AUTH_REQUIRED",
            "a capture candidate never promotes itself into the evidence store")
    level = str(evidence_level or "").strip().upper()
    concept: Optional[Dict[str, Any]] = None
    if level == CAPTURE_CONCEPT_LEVEL:
        if concept_test is None:
            raise CaptureReviewError(
                f"a visible page cannot support evidence_level {level!r}: allowed "
                f"{'/'.join(CAPTURE_EVIDENCE_LEVELS)} (cap {CAPTURE_LEVEL_CAP}); "
                "E3 requires a concept-test record via --concept-test",
                "POLICY_DENIED",
                "E3 需概念测试记录：--concept-test（写明 stimulus/sample_size/"
                "response_metric/result 的 JSON）；E4+/E5 需成交记录")
        concept = _load_concept_test(Path(concept_test))
    elif level and level not in CAPTURE_EVIDENCE_LEVELS:
        raise CaptureReviewError(
            f"a visible page cannot support evidence_level {level!r}: allowed "
            f"{'/'.join(CAPTURE_EVIDENCE_LEVELS)} (cap {CAPTURE_LEVEL_CAP})",
            "POLICY_DENIED",
            "acceptance or payment needs concept tests (E3) or transactions (E4+/E5), "
            "not a page capture")
    if concept_test is not None and concept is None:
        concept = _load_concept_test(Path(concept_test))
    if str(observation or "").strip().lower() not in ("",) + OBSERVATION_MODES:
        raise CaptureReviewError(
            f"unknown --observation {observation!r}; choose from: "
            + ", ".join(OBSERVATION_MODES), "INPUT_REQUIRED",
            "context = surroundings only; statement = one voiced statement; "
            "practice = an observed or documented current workflow/spend")
    if corpus_role not in CORPUS_ROLES:
        raise CaptureReviewError(
            f"unknown corpus_role {corpus_role!r}; choose from: "
            + ", ".join(CORPUS_ROLES), "INPUT_REQUIRED")
    if from_text not in ("page", "ocr"):
        raise CaptureReviewError("--from must be page or ocr", "INPUT_REQUIRED")
    try:
        with write_integrity.Transaction(
                study_dir, purpose=f"capture accept {capture_id}",
                meta={"capture_id": capture_id, "operator": operator}) as txn:
            payload = _load_capture(study_dir, capture_id)
            capture_id = str(payload["capture_id"])
            status = str(payload.get("evidence_status") or "candidate")
            if status == "rejected":
                raise CaptureReviewError(
                    f"capture {capture_id} was rejected on review and stays rejected",
                    "POLICY_DENIED", "capture the page again if it must be re-reviewed")
            if status not in ("candidate", "accepted"):
                raise CaptureReviewError(
                    f"capture {capture_id} has unknown evidence_status {status!r}",
                    "INTERNAL_ERROR")
            records = _read_evidence(study_dir)
            by_id = {str(item.get("record_id")): item for item in records}
            record_id = f"cap-{capture_id}"
            if status == "accepted":
                record = by_id.get(record_id)
                if record is None:
                    raise CaptureReviewError(
                        f"capture {capture_id} is marked accepted but evidence record "
                        f"{record_id} is missing", "INTERNAL_ERROR",
                        "restore the canonical record; an accepted flag alone is not success")
                join_errors = validate_evidence_record(study_dir, record)
                if join_errors:
                    raise CaptureReviewError(
                        "accepted capture/evidence join is invalid: " + "; ".join(join_errors),
                        "INTERNAL_ERROR")
                plan_payload = _source_plan_payload(study_dir)
                if plan_payload is not None:
                    txn.add(SOURCE_PLAN_RELATIVE, plan_payload, mode="replace")
                    txn.commit()
                review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
                return {
                    "status": "accepted", "already_accepted": True,
                    "capture_id": capture_id, "evidence_record_id": record_id,
                    "evidence_level": review.get("evidence_level") or level,
                    "requested_evidence_level": review.get("requested_evidence_level", ""),
                    "level_basis": review.get("level_basis", ""),
                    "level_derivation_version": review.get(
                        "level_derivation_version", LEVEL_DERIVATION_VERSION),
                    "level_observation": review.get("level_observation", ""),
                    "next_required_action": "already accepted; analyze or collect the next gap",
                }
            if record_id in by_id:
                raise CaptureReviewError(
                    f"evidence record {record_id} already exists while the capture is still "
                    "a candidate", "INTERNAL_ERROR",
                    "do not append OCR rows manually; remove the conflicting row or repair "
                    "the reviewed join before acceptance")
            text = _capture_text(payload, from_text)
            platform = _validate_capture_material(study_dir, payload)
            derived = derive_capture_level(
                text, from_text, observation=observation, concept_test=concept)
            derived_level = str(derived["level"])
            effective = derived_level
            level_capped = False
            if level and LEVEL_ORDER[level] > LEVEL_ORDER[derived_level]:
                level_capped = True
            elif level:
                effective = level
            reviewed_at = _now()
            observation_mode = str(observation or "").strip().lower()
            record = _evidence_record(
                payload, level=effective, corpus_role=corpus_role,
                context_key=str(context_key or "").strip(), operator=operator,
                reviewed_at=reviewed_at, text=text, from_text=from_text, platform=platform,
                concept_test=concept, level_basis=str(derived["basis"]),
                requested_level=level, observation=observation_mode)
            payload["evidence_status"] = "accepted"
            payload["review"] = {
                "reviewed_by": operator, "reviewed_at": reviewed_at,
                "action": "accepted", "confirmation": "named_human_accept",
                "evidence_level": effective, "corpus_role": corpus_role,
                "context_key": str(context_key or "").strip(), "from_text": from_text,
                "evidence_record_id": record_id,
                "requested_evidence_level": level,
                "level_basis": str(derived["basis"]),
                "level_derivation_version": LEVEL_DERIVATION_VERSION,
                "level_observation": observation_mode,
            }
            if concept:
                payload["review"]["concept_test"] = concept
            txn.add(EVIDENCE_RELATIVE,
                    json.dumps(record, ensure_ascii=False) + "\n", mode="append")
            txn.add(CAPTURES_RELATIVE / f"{capture_id}.json",
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    mode="replace")
            txn.add(TRAIL_RELATIVE, json.dumps({
                "capture_id": capture_id, "action": "accepted",
                "reviewed_by": operator, "reviewed_at": reviewed_at,
                "confirmation": "named_human_accept", "evidence_record_id": record_id,
                "evidence_level": effective, "corpus_role": corpus_role,
                "context_key": str(context_key or "").strip(), "from_text": from_text,
                "requested_evidence_level": level,
                "level_basis": str(derived["basis"]),
                "level_derivation_version": LEVEL_DERIVATION_VERSION,
                "level_observation": observation_mode,
                "source_url": record["source_url"], "source_ref": record["source_ref"],
                "screenshot_sha256": record["capture_screenshot_sha256"],
                "text_sha256": record["capture_text_sha256"],
                "ocr_text_sha256": record["capture_ocr_text_sha256"], "reason": "",
                **({"concept_test": concept} if concept else {}),
            }, ensure_ascii=False) + "\n", mode="append")
            plan_payload = _source_plan_payload(study_dir)
            if plan_payload is not None:
                txn.add(SOURCE_PLAN_RELATIVE, plan_payload, mode="replace")
            txn.commit()
            return {
                "status": "accepted", "already_accepted": False,
                "capture_id": capture_id, "evidence_record_id": record_id,
                "evidence_level": effective, "reviewed_by": operator,
                "reviewed_at": reviewed_at, "source_url": record["source_url"],
                "source_ref": record["source_ref"],
                "requested_evidence_level": level,
                "level_basis": str(derived["basis"]),
                "level_derivation_version": LEVEL_DERIVATION_VERSION,
                "level_capped": level_capped,
                "level_observation": observation_mode,
                "evidence_file": str(study_dir / EVIDENCE_RELATIVE),
                "next_required_action": (
                    "run `askovo analyze`; human review must still register any judgment/chain "
                    "links — acceptance authors no business conclusion"),
            }
    except write_integrity.IntegrityError as exc:
        raise CaptureReviewError(
            f"write integrity failure: {exc}", "INTERNAL_ERROR",
            "inspect the write journal; the review is recoverable") from exc


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
    try:
        with write_integrity.Transaction(
                study_dir, purpose=f"capture reject {capture_id}",
                meta={"capture_id": capture_id, "operator": operator}) as txn:
            payload = _load_capture(study_dir, capture_id)
            capture_id = str(payload["capture_id"])
            status = str(payload.get("evidence_status") or "candidate")
            if status == "accepted":
                raise CaptureReviewError(
                    "an accepted capture cannot be rejected while its evidence remains",
                    "POLICY_DENIED", "use the canonical correction/review flow; do not orphan evidence")
            if status == "rejected":
                return {"status": "rejected", "already_rejected": True,
                        "capture_id": capture_id, "evidence_written": False}
            reviewed_at = _now()
            payload["evidence_status"] = "rejected"
            payload["review"] = {
                "reviewed_by": operator, "reviewed_at": reviewed_at,
                "action": "rejected", "confirmation": "named_human_reject",
                "reason": rationale,
            }
            txn.add(CAPTURES_RELATIVE / f"{capture_id}.json",
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    mode="replace")
            txn.add(TRAIL_RELATIVE, json.dumps({
                "capture_id": capture_id, "action": "rejected",
                "reviewed_by": operator, "reviewed_at": reviewed_at,
                "confirmation": "named_human_reject", "evidence_record_id": None,
                "reason": rationale,
            }, ensure_ascii=False) + "\n", mode="append")
            txn.commit()
            return {"status": "rejected", "capture_id": capture_id,
                    "evidence_written": False,
                    "next_required_action": "candidate stays out of the evidence store"}
    except write_integrity.IntegrityError as exc:
        raise CaptureReviewError(f"write integrity failure: {exc}", "INTERNAL_ERROR") from exc

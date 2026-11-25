"""Named-human review for primary-research capture-plan candidates."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import capture_plan
import capture_review
import sure_engine
import write_integrity

SOURCE_FAMILY = "primary_research"
EVIDENCE_RELATIVE = Path("02-data/evidence.jsonl")
TRAIL_RELATIVE = Path("01-sources/primary-research/review-trail.jsonl")
SOURCE_PLAN_RELATIVE = Path("01-sources/source-plan.csv")
LEVELS = ("E0", "E1", "E2")
LEVEL_ORDER = {"E0": 0, "E1": 1, "E2": 2}
DERIVATION_VERSION = "askovo-primary-candidate-review/1"
SOURCE_PLAN_FIELDS = ("corpus_role", "source_family", "route_or_query", "target_records",
                      "cap_share", "access_status", "known_bias")


class PrimaryReviewError(capture_plan.CapturePlanError):
    pass


def study_root_for_plan(plan_path: Path) -> Path:
    path = Path(plan_path).resolve()
    for parent in path.parents:
        if (parent / "study.json").is_file() \
                and (parent / capture_plan.CANONICAL_REF).is_file():
            return parent
    raise PrimaryReviewError(
        "capture plan must live inside its study", "STUDY_NOT_FOUND",
        "Use the default 04-findings/capture-plans location inside the study.")


def load_evidence_records(study_dir: Path) -> List[Dict[str, Any]]:
    try:
        return write_integrity.read_jsonl(
            Path(study_dir) / EVIDENCE_RELATIVE, missing_ok=True,
            label="canonical evidence store")
    except write_integrity.IntegrityError as exc:
        raise PrimaryReviewError(str(exc), "INTERNAL_ERROR") from exc


def _text(candidate: Dict[str, Any], observation: str) -> str:
    if observation == "practice":
        return str(candidate.get("behavior_ref") or "").strip()
    if observation == "context":
        return str(candidate.get("note") or candidate.get("behavior_ref")
                   or candidate.get("user_voice") or "").strip()
    return str(candidate.get("user_voice") or candidate.get("note") or "").strip()


def _derive(text: str, observation: str) -> Dict[str, str]:
    visible = len("".join(text.split()))
    if visible < capture_review.LEVEL_MIN_SUBSTANTIVE_CHARS or observation == "context":
        return {"level": "E0", "basis": "Primary candidate contains context or insufficient substantive text."}
    if observation == "practice":
        return {"level": "E2", "basis": "Named reviewer confirmed the recorded participant practice/behavior."}
    return {"level": "E1", "basis": "Named reviewer confirmed one participant statement."}


def _selected_level(text: str, observation: str, requested: str) -> Dict[str, Any]:
    derived = _derive(text, observation)
    effective = derived["level"]
    if requested and LEVEL_ORDER[requested] < LEVEL_ORDER[effective]:
        effective = requested
    return {"level": effective, "basis": derived["basis"],
            "level_capped": bool(requested and requested != effective)}


def _record_id(plan: Dict[str, Any], candidate_id: str) -> str:
    return "cpc-%s-%s" % (plan.get("plan_id"), candidate_id)


def _source_plan_payload(study_dir: Path, plan: Dict[str, Any]) -> Optional[bytes]:
    path = Path(study_dir) / SOURCE_PLAN_RELATIVE
    rows = []
    fields = list(SOURCE_PLAN_FIELDS)
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or fields)
            for required in SOURCE_PLAN_FIELDS:
                if required not in fields:
                    fields.append(required)
            rows = [dict(row) for row in reader if str(row.get("source_family") or "").strip()]
    if any(str(row.get("source_family")) == SOURCE_FAMILY for row in rows):
        return None
    rows.append({
        "corpus_role": "open_scene",
        "source_family": SOURCE_FAMILY,
        "route_or_query": "authorized primary-research capture plan %s" % plan.get("plan_id"),
        "target_records": str((plan.get("target_participants") or {}).get("count") or 1),
        "cap_share": "1.00",
        "access_status": "named-human reviewed candidate under an authorized capture plan",
        "known_bias": "Authorized research sample; not a population prevalence estimate.",
    })
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    return output.getvalue().encode("utf-8")


def _evidence_record(plan: Dict[str, Any], candidate: Dict[str, Any], *,
                     plan_ref: str, record_id: str, reviewer: str, reviewed_at: str,
                     observation: str, corpus_role: str, requested_level: str,
                     selected: Dict[str, Any], text: str) -> Dict[str, Any]:
    level = selected["level"]
    raw = {
        "record_id": record_id,
        "context_key": plan["context_key"],
        "user_role": "research_participant",
        "scene_trigger": plan.get("objective") or "unknown",
        "task_outcome": candidate.get("consequence") or "unknown",
        "current_substitute": candidate.get("alternative_behavior") or "unknown",
        "friction_cost": "unknown",
        "consequence": candidate.get("consequence") or "unknown",
        "evidence_level": level,
        "evidence_basis": selected["basis"],
        "corpus_role": corpus_role,
        "source_family": SOURCE_FAMILY,
        "source_ref": plan_ref,
        "source_url": candidate.get("source_ref") or "",
        "created_at": "",
        "collected_at": candidate.get("collected_at") or "",
        "normalized_text_hash": capture_review._sha_text(text),
        "text": text,
        "claim_type": "context" if level == "E0" else "need",
        "evidence_form": "behavior_log" if observation == "practice" else "self_report",
        "method_id": "capture_plan_human_review",
        "platform": "primary_research",
    }
    defaults = {
        "source_family": SOURCE_FAMILY,
        "source_ref": plan_ref,
        "claim_type": raw["claim_type"],
        "evidence_form": raw["evidence_form"],
        "method_id": "capture_plan_human_review",
        "product_domain": "unknown",
    }
    record = sure_engine._normalize_record(raw, 1, defaults)
    record.update({
        "reviewed_by": reviewer,
        "reviewed_at": reviewed_at,
        "human_review_status": "reviewed",
        "review_confirmation": "named_human_accept",
        "review_reason": str(candidate.get("review", {}).get("reason") or ""),
        "primary_plan_id": plan["plan_id"],
        "primary_candidate_id": candidate["candidate_id"],
        "primary_candidate_hash": candidate["candidate_hash"],
        "primary_authorization_scope_hash": plan["authorization"]["scope_hash"],
        "primary_source_ref": candidate.get("source_ref") or "",
        "participant_ref": candidate.get("participant_ref") or "",
        "consent_ref": candidate.get("consent_ref") or "",
        "level_observation": observation,
        "level_basis": selected["basis"],
        "level_derivation_version": DERIVATION_VERSION,
        "requested_evidence_level": requested_level,
        "boundary": "One reviewed research candidate; no prevalence, causality, demand verdict or business acceptance is inferred.",
    })
    return record


def review_candidate(plan_path: Path, candidate_id: str, *, by: str,
                     decision: str, reason: str, at: Optional[str] = None,
                     observation: str = "statement", corpus_role: str = "open_scene",
                     evidence_level: str = "") -> Dict[str, Any]:
    reviewer = str(by or "").strip()
    reason_text = str(reason or "").strip()
    if not reviewer:
        raise PrimaryReviewError("candidate review needs a named reviewer", "AUTH_REQUIRED")
    if decision not in ("accept", "reject"):
        raise PrimaryReviewError("decision must be accept or reject", "INPUT_REQUIRED")
    if not reason_text:
        raise PrimaryReviewError("candidate review needs a reason", "REASON_REQUIRED")
    observation = str(observation or "statement").lower()
    if observation not in capture_review.OBSERVATION_MODES:
        raise PrimaryReviewError("unknown observation mode", "INPUT_REQUIRED")
    if corpus_role not in capture_review.CORPUS_ROLES:
        raise PrimaryReviewError("unknown corpus_role", "INPUT_REQUIRED")
    requested_level = str(evidence_level or "").upper()
    if requested_level and requested_level not in LEVELS:
        raise PrimaryReviewError("primary candidate review allows only E0/E1/E2", "POLICY_DENIED")
    plan_path = Path(plan_path).resolve()
    study_dir = study_root_for_plan(plan_path)
    plan_ref = plan_path.relative_to(study_dir).as_posix()
    try:
        with write_integrity.Transaction(
                study_dir, purpose="primary candidate review %s" % candidate_id,
                meta={"candidate_id": candidate_id, "operator": reviewer}) as txn:
            plan = capture_plan.load_plan(plan_path)
            authorization = plan.get("authorization") or {}
            if authorization.get("status") != "authorized" \
                    or authorization.get("scope_hash") != capture_plan.scope_hash(plan):
                raise PrimaryReviewError("candidate review needs current plan authorization",
                                         "AUTHORIZATION_REQUIRED")
            candidate = next((row for row in plan.get("candidates") or []
                              if str(row.get("candidate_id")) == str(candidate_id)), None)
            if candidate is None:
                raise PrimaryReviewError("unknown candidate %s" % candidate_id, "INPUT_REQUIRED")
            if capture_plan.candidate_hash(candidate) != candidate.get("candidate_hash"):
                raise PrimaryReviewError("candidate content changed after import", "CANDIDATE_CHANGED")
            record_id = _record_id(plan, str(candidate_id))
            if decision == "reject":
                if candidate.get("state") == "accepted":
                    raise PrimaryReviewError("an accepted candidate cannot be rejected retroactively",
                                             "POLICY_DENIED")
                if candidate.get("state") == "rejected":
                    return {"status": "rejected", "already_rejected": True,
                            "candidate_id": str(candidate_id)}
                candidate["state"] = "rejected"
                candidate["usable"] = False
                candidate["review"] = {
                    "reviewed_by": reviewer, "reviewed_at": str(at or sure_engine.now()),
                    "decision": "rejected", "reason": reason_text,
                    "candidate_hash": candidate["candidate_hash"],
                }
                capture_plan._append_log(plan, at=candidate["review"]["reviewed_at"],
                                         actor=reviewer, action="candidate_reject",
                                         fields=["candidates"], note=reason_text)
                txn.add(Path(plan_ref), (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode(),
                        mode="replace")
                txn.add(TRAIL_RELATIVE, json.dumps({
                    "plan_id": plan["plan_id"], "candidate_id": str(candidate_id),
                    "decision": "rejected", **candidate["review"],
                }, ensure_ascii=False) + "\n", mode="append")
                txn.commit()
                return {"status": "rejected", "already_rejected": False,
                        "candidate_id": str(candidate_id)}

            if candidate.get("state") == "accepted":
                record = next((row for row in load_evidence_records(study_dir)
                               if str(row.get("record_id")) == record_id), None)
                if record is None:
                    raise PrimaryReviewError("accepted candidate has no canonical evidence record",
                                             "INTERNAL_ERROR")
                join_errors = validate_evidence_record(study_dir, record)
                if join_errors:
                    raise PrimaryReviewError("accepted candidate/evidence join is invalid: %s"
                                             % "; ".join(join_errors), "INTERNAL_ERROR")
                return {"status": "accepted", "already_accepted": True,
                        "candidate_id": str(candidate_id), "evidence_record_id": record_id,
                        "evidence_level": record["evidence_level"]}
            if candidate.get("state") != "candidate" or candidate.get("usable") is not True:
                raise PrimaryReviewError("candidate is not eligible for acceptance", "INVALID_STATE")
            missing = [key for key in ("source_ref", "collected_at", "consent_ref", "participant_ref")
                       if not str(candidate.get(key) or "").strip()]
            if missing:
                raise PrimaryReviewError("candidate is missing: %s" % ", ".join(missing),
                                         "PROVENANCE_REQUIRED")
            text = _text(candidate, observation)
            if not text:
                raise PrimaryReviewError("selected observation has no reviewable text", "INPUT_REQUIRED")
            selected = _selected_level(text, observation, requested_level)
            reviewed_at = str(at or sure_engine.now())
            candidate["review"] = {
                "reviewed_by": reviewer, "reviewed_at": reviewed_at,
                "decision": "accepted", "reason": reason_text,
                "candidate_hash": candidate["candidate_hash"],
                "evidence_record_id": record_id, "evidence_level": selected["level"],
                "observation": observation, "corpus_role": corpus_role,
                "requested_evidence_level": requested_level,
                "authorization_scope_hash": authorization["scope_hash"],
                "text_sha256": capture_review._sha_text(text),
            }
            record = _evidence_record(
                plan, candidate, plan_ref=plan_ref, record_id=record_id,
                reviewer=reviewer, reviewed_at=reviewed_at, observation=observation,
                corpus_role=corpus_role, requested_level=requested_level,
                selected=selected, text=text)
            if any(str(row.get("record_id")) == record_id for row in load_evidence_records(study_dir)):
                raise PrimaryReviewError("canonical evidence record already exists", "INTERNAL_ERROR")
            candidate["state"] = "accepted"
            candidate["usable"] = True
            capture_plan._append_log(plan, at=reviewed_at, actor=reviewer,
                                     action="candidate_accept", fields=["candidates"], note=reason_text)
            txn.add(EVIDENCE_RELATIVE, json.dumps(record, ensure_ascii=False) + "\n", mode="append")
            txn.add(Path(plan_ref), (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode(),
                    mode="replace")
            txn.add(TRAIL_RELATIVE, json.dumps({
                "plan_id": plan["plan_id"], "candidate_id": str(candidate_id),
                **candidate["review"],
            }, ensure_ascii=False) + "\n", mode="append")
            source_plan = _source_plan_payload(study_dir, plan)
            if source_plan is not None:
                txn.add(SOURCE_PLAN_RELATIVE, source_plan, mode="replace")
            txn.commit()
            return {"status": "accepted", "already_accepted": False,
                    "candidate_id": str(candidate_id), "evidence_record_id": record_id,
                    "evidence_level": record["evidence_level"],
                    "level_capped": selected["level_capped"]}
    except write_integrity.IntegrityError as exc:
        raise PrimaryReviewError("write integrity failure: %s" % exc, "INTERNAL_ERROR") from exc


def validate_evidence_record(study_dir: Path, record: Dict[str, Any]) -> List[str]:
    errors = []
    try:
        plan_id = str(record.get("primary_plan_id") or "")
        candidate_id = str(record.get("primary_candidate_id") or "")
        if str(record.get("record_id")) != "cpc-%s-%s" % (plan_id, candidate_id):
            errors.append("primary research record id does not match its plan/candidate join")
        plan_ref = str(record.get("source_ref") or "")
        plan_path = (Path(study_dir) / plan_ref).resolve()
        plan_path.relative_to(Path(study_dir).resolve())
        plan = capture_plan.load_plan(plan_path)
        if str(plan.get("plan_id")) != plan_id:
            errors.append("primary plan id differs from its source plan")
        candidate = next((row for row in plan.get("candidates") or []
                          if str(row.get("candidate_id")) == candidate_id), None)
        if candidate is None or candidate.get("state") != "accepted":
            return errors + ["accepted primary candidate is missing from its source plan"]
        review = candidate.get("review") or {}
        for field, expected in (
                ("reviewed_by", review.get("reviewed_by")),
                ("reviewed_at", review.get("reviewed_at")),
                ("primary_candidate_hash", review.get("candidate_hash")),
                ("primary_authorization_scope_hash", review.get("authorization_scope_hash")),
                ("evidence_level", review.get("evidence_level")),
                ("level_observation", review.get("observation"))):
            if str(record.get(field) or "") != str(expected or ""):
                errors.append("%s differs from the candidate review" % field)
        if capture_plan.candidate_hash(candidate) != candidate.get("candidate_hash") \
                or capture_plan.candidate_hash(candidate) != record.get("primary_candidate_hash"):
            errors.append("candidate hash differs from the reviewed candidate")
        text = _text(candidate, str(review.get("observation") or "statement"))
        if str(record.get("text") or "") != text \
                or str(record.get("normalized_text_hash") or "") != capture_review._sha_text(text):
            errors.append("reviewed text or text hash differs from the candidate")
        for field in ("consent_ref", "participant_ref", "collected_at"):
            if str(record.get(field) or "") != str(candidate.get(field) or "") \
                    or not str(record.get(field) or "").strip():
                errors.append("%s is missing or differs from the candidate" % field)
        if record.get("human_review_status") != "reviewed" \
                or record.get("review_confirmation") != "named_human_accept":
            errors.append("named-human review confirmation is missing")
        if str(record.get("source_url") or "") != str(candidate.get("source_ref") or ""):
            errors.append("source_url differs from the candidate source")
        selected = _selected_level(text, str(review.get("observation") or "statement"),
                                   str(review.get("requested_evidence_level") or ""))
        if str(record.get("evidence_level")) != selected["level"]:
            errors.append("evidence level differs from the review derivation")
    except (OSError, ValueError, capture_plan.CapturePlanError) as exc:
        errors.append("primary candidate/evidence join cannot be validated: %s" % exc)
    return errors

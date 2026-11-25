"""Read-only projection from an Askovo capture plan to the shared experiment contract."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import capture_plan
import primary_candidate_review

SCHEMA = "ovo.experiment-contract/1"


class ExperimentExportError(capture_plan.CapturePlanError):
    pass


def design_hash(document: Dict[str, Any]) -> str:
    projection = {key: document.get(key) for key in
                  ("hypothesis", "design", "window", "stop_conditions")}
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _instant(value: Any, *, end: bool = False) -> str:
    text = str(value or "").strip()
    if len(text) == 10:
        return text + ("T23:59:59Z" if end else "T00:00:00Z")
    return text


def _state(plan: Dict[str, Any]) -> str:
    return {
        "draft": "registered",
        "needs_review": "registered",
        "authorized": "registered",
        "collecting": "running",
        "candidates_ready": "completed",
        "closed": "completed",
        "cancelled": "cancelled",
        "stale": "stopped",
    }.get(str(plan.get("state") or ""), "stopped")


def _candidate_hash(candidate: Dict[str, Any]) -> str:
    canonical = json.dumps(candidate, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def from_capture_plan(plan: Dict[str, Any], spec: Dict[str, Any],
                      origin_version: str, *, evidence_records: Any = None,
                      study_dir: Any = None) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ExperimentExportError("experiment design must be a JSON object",
                                    "DESIGN_REQUIRED")
    missing = [key for key in ("hypothesis", "design", "registered_by", "registered_at")
               if not spec.get(key)]
    if "external_actions" not in spec:
        missing.append("external_actions")
    if missing:
        raise ExperimentExportError(
            "experiment export needs: " + ", ".join(missing), "DESIGN_REQUIRED",
            "The host agent supplies the hypothesis and design; Askovo never invents them.")
    design = copy.deepcopy(spec["design"])
    if not isinstance(design, dict):
        raise ExperimentExportError("design must be an object", "DESIGN_REQUIRED")
    design.setdefault("population", "; ".join(str((plan.get("target_participants") or {}).get(key) or "")
                                               for key in ("segment", "criteria")).strip("; "))
    window = {
        "start": _instant((plan.get("window") or {}).get("start")),
        "end": _instant((plan.get("window") or {}).get("end"), end=True),
    }
    authorization = plan.get("authorization") if isinstance(plan.get("authorization"), dict) else {}
    authorization_ref = str(authorization.get("authorization_ref") or "").strip()
    if spec.get("external_actions") is True and (
            authorization.get("status") != "authorized" or not authorization_ref):
        raise ExperimentExportError(
            "external research needs an authorized capture plan and authorization_ref",
            "AUTHORIZATION_REQUIRED")

    bindings = spec.get("observation_bindings") or {}
    evidence_by_id = {str(row.get("record_id") or ""): row
                      for row in (evidence_records or []) if isinstance(row, dict)}
    observations = []
    for candidate in plan.get("candidates") or []:
        candidate_id = str(candidate.get("candidate_id") or "")
        binding = bindings.get(candidate_id)
        if not isinstance(binding, dict):
            raise ExperimentExportError(
                "candidate %s needs an arm_id and metric_id binding" % candidate_id,
                "OBSERVATION_BINDING_REQUIRED")
        value_text = str(binding.get("value_text") or candidate.get("user_voice")
                         or candidate.get("note") or "").strip()
        observation = {
            "observation_id": candidate_id,
            "arm_id": str(binding.get("arm_id") or ""),
            "metric_id": str(binding.get("metric_id") or ""),
            "subject_ref": str(candidate.get("participant_ref") or candidate_id),
            "observed_at": str(candidate.get("collected_at") or ""),
            "source_ref": "askovo-capture-plan:%s/%s" % (plan.get("plan_id"), candidate_id),
            "source_hash": _candidate_hash(candidate),
            "evidence_grade": "reported",
            "eligible": False,
            "exclusion_reason": "Capture candidate awaits named human evidence review.",
        }
        if candidate.get("state") == "accepted":
            review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
            record_id = str(review.get("evidence_record_id") or "")
            canonical = evidence_by_id.get(record_id)
            if canonical is None or study_dir is None:
                raise ExperimentExportError(
                    "accepted candidate needs its canonical evidence record and study root",
                    "EVIDENCE_REQUIRED")
            join_errors = primary_candidate_review.validate_evidence_record(
                Path(study_dir), canonical)
            if join_errors:
                raise ExperimentExportError(
                    "accepted candidate/evidence join is invalid: " + "; ".join(join_errors),
                    "EVIDENCE_JOIN_INVALID")
            observation["source_ref"] = "askovo-evidence:%s" % record_id
            observation["source_hash"] = _candidate_hash(canonical)
            observation["evidence_grade"] = (
                "observed" if review.get("observation") == "practice" else "reported")
            observation["eligible"] = True
            observation["exclusion_reason"] = ""
        if "value_number" in binding:
            observation["value_number"] = binding["value_number"]
        elif value_text:
            observation["value_text"] = value_text
        observations.append(observation)

    outcome = copy.deepcopy(spec.get("outcome") or {
        "status": "not_evaluated",
        "causality": "not_claimed",
        "evidence_refs": [],
        "evaluated_by": "",
        "evaluated_at": "",
        "notes": "No outcome is inferred from capture candidates.",
    })
    if outcome.get("status") in ("supports_hypothesis", "refutes_hypothesis"):
        eligible = {row["observation_id"] for row in observations if row["eligible"]}
        if not eligible.intersection(outcome.get("evidence_refs") or []):
            raise ExperimentExportError(
                "unreviewed capture candidates cannot support a decisive outcome",
                "EVIDENCE_NOT_ELIGIBLE")
    document = {
        "schema": SCHEMA,
        "experiment_id": str(plan.get("plan_id") or ""),
        "origin_product": "askovo",
        "origin_version": str(origin_version),
        "task_id": "%s/%s" % (plan.get("study_id"), plan.get("chain_id")),
        "title": str(plan.get("objective") or plan.get("research_question") or ""),
        "state": _state(plan),
        "hypothesis": copy.deepcopy(spec["hypothesis"]),
        "design": design,
        "window": window,
        "stop_conditions": list(plan.get("stop_conditions") or []),
        "external_actions": spec["external_actions"],
        "authorization_refs": [authorization_ref] if authorization_ref else [],
        "registered_by": str(spec["registered_by"]),
        "registered_at": str(spec["registered_at"]),
        "observations": observations,
        "outcome": outcome,
    }
    if spec.get("decision"):
        document["decision"] = copy.deepcopy(spec["decision"])
    document["design_sha256"] = design_hash(document)
    return document


def write_new(document: Dict[str, Any], path: Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

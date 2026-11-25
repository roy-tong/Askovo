"""Named participant screening with separate eligibility, consent and readiness."""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "askovo.participant-screening/1"
CONSENT_STATES = ("accepted", "pending", "declined", "withdrawn")


def build(plan, reviews, *, reviewed_by, reviewed_at=""):
    if not isinstance(plan, dict):
        raise ValueError("capture plan must be an object")
    target = plan.get("target_participants") if isinstance(plan.get("target_participants"), dict) else {}
    if not str(target.get("criteria") or "").strip():
        raise ValueError("capture plan needs target_participants.criteria")
    if not str(reviewed_by or "").strip():
        raise ValueError("reviewed_by is required")
    if not isinstance(reviews, list):
        raise ValueError("screening reviews must be an array")
    participants = []
    seen = {}
    duplicates = 0
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("screening review must be an object")
        for key in ("participant_ref", "source_ref", "reason"):
            if not str(review.get(key) or "").strip():
                raise ValueError("screening.%s is required" % key)
        if not isinstance(review.get("eligible"), bool):
            raise ValueError("eligible must be a boolean")
        evidence = review.get("evidence_refs")
        if not isinstance(evidence, list) or not all(str(value or "").strip() for value in evidence):
            raise ValueError("evidence_refs must be an array of references")
        if review["eligible"] and not evidence:
            raise ValueError("eligible participant needs evidence_refs")
        consent = str(review.get("consent_state") or "")
        if consent not in CONSENT_STATES:
            raise ValueError("consent_state must be accepted/pending/declined/withdrawn")
        row = {
            "participant_ref": review["participant_ref"], "source_ref": review["source_ref"],
            "eligible": review["eligible"], "evidence_refs": list(evidence),
            "consent_state": consent,
            "research_ready": review["eligible"] and consent == "accepted",
            "reason": review["reason"],
            "review": {"reviewed_by": str(reviewed_by), "reviewed_at": str(reviewed_at or "")},
        }
        ref = row["participant_ref"]
        if ref in seen:
            if seen[ref] != row:
                raise ValueError("participant_ref conflict")
            duplicates += 1
            continue
        seen[ref] = row
        participants.append(row)
    summary = {
        "reviewed": len(participants),
        "eligible": sum(row["eligible"] for row in participants),
        "research_ready": sum(row["research_ready"] for row in participants),
        "pending_consent": sum(row["consent_state"] == "pending" for row in participants),
        "not_ready_declined": sum(row["consent_state"] == "declined" for row in participants),
        "not_ready_withdrawn": sum(row["consent_state"] == "withdrawn" for row in participants),
        "duplicates": duplicates,
    }
    return {
        "schema": SCHEMA, "plan_id": str(plan.get("plan_id") or ""),
        "chain_id": str(plan.get("chain_id") or ""),
        "target": {"segment": target.get("segment") or "", "criteria": target["criteria"],
                   "count": target.get("count")},
        "participants": participants, "summary": summary,
        "source_plan_mutated": False, "recruitment_executed": False,
        "external_actions": 0,
        "boundary": "Named screening and consent declarations only. Research readiness is not recruitment, actual participation, evidence quality, representativeness or a demand verdict.",
    }


def write_new(document, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return target

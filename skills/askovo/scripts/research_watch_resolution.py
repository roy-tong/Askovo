"""Read-only Askovo watch projection into the shared Problem Resolution Contract."""
from __future__ import annotations

from pathlib import Path

import research_watch
import write_integrity

SCHEMA = "ovo.problem-resolution/1"


def _base(state, watch, code, summary, refs, observed_at):
    return {
        "schema": SCHEMA,
        "problem_id": watch["watch_id"] + "-resolution",
        "product": "askovo",
        "task_id": str(state.get("study_id") or ""),
        "observed_at": observed_at,
        "observation": {
            "code": code,
            "summary": summary,
            "external_effect_status": "none",
            "evidence_refs": refs,
        },
    }


def _business(state, watch, code, summary, refs, observed_at, options):
    document = _base(state, watch, code, summary, refs, observed_at)
    document["requested_resolution"] = "business_decision"
    document["decision"] = {
        "evidence_refs": refs,
        "options": [{"option_id": option_id, "impact": impact} for option_id, impact in options],
    }
    return document


def build(study_dir: Path, watch_id: str):
    study_dir = Path(study_dir).resolve()
    state = research_watch._load_state(study_dir)
    watch = research_watch._find(state, watch_id)
    history = write_integrity.read_jsonl(
        research_watch._history_path(study_dir), missing_ok=True, label="research watch history")
    runs = [row for row in history if row.get("watch_id") == watch_id]
    latest = runs[-1] if runs else None
    refs = ["research-watch:%s/%s" % (state.get("study_id"), watch_id)]
    observed_at = watch.get("created_at")

    if watch.get("state") == "paused":
        return _business(
            state, watch, "RESEARCH_WATCH_PAUSED", "The watch is paused by the research owner.",
            refs, observed_at,
            (("resume_watch", "Resume future local review ticks; no review is run by this projection."),
             ("remain_paused", "Preserve the pause and make no research or decision change.")))
    if latest is None:
        document = _base(
            state, watch, "RESEARCH_REVIEW_NOT_RUN", "The watch has not completed its first local review.",
            refs, observed_at)
        document["requested_resolution"] = "data_needed"
        document["data"] = {
            "request_id": watch_id + "-local-review",
            "source": "local-decision-review",
            "access_basis": "existing study and named watch owner",
            "automatic_fetch_attempted": False,
            "side_effect_free_fetch": True,
        }
        return document

    refs.append(latest["run_id"])
    observed_at = latest.get("completed_at") or latest.get("started_at") or observed_at
    if latest.get("review_json_path"):
        refs.append(latest["review_json_path"])
    if latest.get("status") == "failed":
        return _business(
            state, watch, "RESEARCH_REVIEW_EXECUTION_FAILED",
            "The local review did not complete; inspect its error before another run.", refs, observed_at,
            (("inspect_review_failure", "Inspect the recorded error and preserve state; no automatic retry is applied."),
             ("pause_watch", "Stop future review ticks until the research owner resolves the failure.")))
    if latest.get("review_status") != "pass":
        return _business(
            state, watch, "RESEARCH_REVIEW_GAPS",
            "The deterministic review reports gaps that need research-owner judgment.", refs, observed_at,
            (("address_review_gaps", "Repair research artifacts or evidence through their named review paths."),
             ("defer_product_decision", "Keep the product decision unresolved and preserve every reported gap.")))
    if latest.get("source_changed_since_last_run"):
        return _business(
            state, watch, "RESEARCH_SOURCE_CHANGED",
            "Study source files changed; review their semantic impact before reusing a decision.", refs, observed_at,
            (("review_source_changes", "Inspect the changed sources and obtain any required semantic review."),
             ("keep_decision_unresolved", "Do not infer that the existing product decision still holds.")))
    raise ValueError("watch has no resolution problem: %s" % watch_id)

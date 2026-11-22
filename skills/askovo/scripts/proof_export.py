from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import decision_brief
import decision_review

PROOF_SCHEMA = "ovo.proof/1"
CHECKS_SCHEMA = "ovo.proof-checks/1"
REPLAY_SCHEMA = "ovo.replay-manifest/1"


class ProofExportError(ValueError):
    def __init__(self, message: str, reason_code: str = "INPUT_REQUIRED") -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in value)
    return cleaned.strip("-") or "study"


def _evidence(entry_id: str, source_ref: str, digest: str, observed_at: str,
              trust: str = "observed") -> Dict[str, Any]:
    return {
        "evidence_id": entry_id,
        "kind": "source_document",
        "source_ref": source_ref,
        "source_hash": digest,
        "observed_at": observed_at,
        "collected_by": "askovo proof export",
        "trust": trust,
    }


def _status(checks: List[Dict[str, Any]]) -> str:
    statuses = {item["status"] for item in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if statuses & {"UNCHECKED", "INDETERMINATE"}:
        return "BLOCKED"
    if "EXPIRED" in statuses:
        return "EXPIRED"
    return "PASS"


def export_proof(study_dir: str | Path, out_dir: str | Path, *, by: str,
                 task_id: str = "", classification: str = "private") -> Dict[str, Any]:
    if not by.strip():
        raise ProofExportError("a named artifact reviewer is required", "REVIEW_REQUIRED")
    if classification not in ("private", "synthetic", "public-redacted"):
        raise ProofExportError("unknown proof classification", "INPUT_REQUIRED")
    study_dir = Path(study_dir).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        raise ProofExportError("output directory already exists; choose a new path", "OUTPUT_EXISTS")
    if not (study_dir / "study.json").is_file():
        raise ProofExportError("study.json not found", "INPUT_REQUIRED")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=out_dir.name + ".tmp-", dir=str(out_dir.parent)))
    try:
        study = json.loads((study_dir / "study.json").read_text(encoding="utf-8"))
        review_payload = None
        if not (study_dir / "05-audit" / "decision-review.json").is_file():
            review_payload = decision_review.build_review(study_dir)
        brief = decision_brief.build(study_dir, task_id=task_id, review_payload=review_payload)
        brief["canonical_refs"] = [
            str(Path(value).relative_to(study_dir)) if str(value).startswith(str(study_dir))
            else Path(value).name
            for value in brief.get("canonical_refs") or []
        ]
        brief_json = temp / "artifacts" / "decision-brief.json"
        brief_md = temp / "artifacts" / "decision-brief.md"
        _write_json(brief_json, brief)
        brief_md.write_text(decision_brief.render_markdown(brief), encoding="utf-8")
        generated_at = _now()
        stale = brief.get("artifact_status") == "stale"
        decision = study.get("decision") or {}
        scope = study.get("scope") or {}
        study_id = str(study.get("study_id") or study_dir.name)
        safe_study_id = _safe_id(study_id)
        contract_id = "askovo-%s-proof" % safe_study_id
        trace_id = "trace-%s-proof" % safe_study_id
        criterion = "Decision Brief 及其 canonical 引用可读取，输入指纹和过期状态已保留"
        contract = {
            "schema": "ovo.task-contract/1",
            "contract_id": contract_id,
            "version": "1",
            "created_at": generated_at,
            "owner": str(decision.get("owner") or "unspecified-decision-owner"),
            "product": "askovo",
            "goal": str(decision.get("question") or "Project one product decision into a reviewable brief"),
            "inputs": [
                {"ref": relative, "kind": "canonical_study_input"}
                for relative in (
                    "study.json", "04-findings/product-reasoning.json",
                    "04-findings/demand-judgments.json", "02-data/evidence.jsonl",
                ) if (study_dir / relative).is_file()
            ],
            "deliverables": [{
                "id": "decision-brief",
                "description": "Decision Brief、证据引用、未知项与重放说明",
                "acceptance_criteria": [criterion],
                "out_of_scope": list(scope.get("prohibited_inferences") or []) + [
                    "自动批准产品决定", "证明市场需求、商业成功或因果",
                ],
            }],
            "approved_by": str(decision.get("owner") or "declared-decision-owner"),
        }
        steps = [{
            "step_id": "project-decision-brief",
            "action": "project_decision_brief",
            "started_at": generated_at,
            "ended_at": generated_at,
            "status": "ok",
            "tool": "askovo decision_brief.build",
            "output_ref": "artifacts/decision-brief.json",
        }]
        trace = {
            "schema": "ovo.execution-trace/1",
            "trace_id": trace_id,
            "contract_id": contract_id,
            "started_at": generated_at,
            "finished_at": generated_at,
            "actor": "askovo proof export",
            "steps": steps,
        }
        entries = []
        for relative in (
            "study.json", "04-findings/product-reasoning.json",
            "04-findings/demand-judgments.json", "02-data/evidence.jsonl",
        ):
            path = study_dir / relative
            if path.is_file():
                entries.append(_evidence(
                    "source-" + _safe_id(relative), relative, _digest(path), generated_at))
        entries.extend([
            _evidence("decision-brief-json", "artifacts/decision-brief.json",
                      _digest(brief_json), generated_at, "derived"),
            _evidence("decision-brief-md", "artifacts/decision-brief.md",
                      _digest(brief_md), generated_at, "derived"),
        ])
        ledger = {
            "schema": "ovo.evidence-ledger/1",
            "ledger_id": "ledger-%s-proof" % safe_study_id,
            "contract_id": contract_id,
            "entries": entries,
        }
        acceptance = {
            "schema": "ovo.acceptance-record/1",
            "acceptance_id": "accept-decision-brief",
            "contract_id": contract_id,
            "trace_id": trace_id,
            "deliverable_id": "decision-brief",
            "criterion": criterion,
            "verdict": "UNPROVEN" if stale else "PASS",
            "evidence_refs": [] if stale else ["decision-brief-json", "decision-brief-md"],
            "checked_by": by,
            "checked_at": generated_at,
            "notes": "；".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
                for item in (brief.get("stale_reasons") or [])
            ) if stale else "Brief bytes and source fingerprint recorded",
        }
        bundle = {
            "schema": "ovo.acceptance-bundle/1",
            "task_contract": contract,
            "execution_trace": trace,
            "evidence_ledger": ledger,
            "acceptances": [acceptance],
            "escalations": [],
        }
        artifact_status = "EXPIRED" if stale else "PASS"
        artifact_reason = "Brief is stale; replay requires refreshed canonical inputs" if stale else ""
        checks = [
            {
                "check_id": "artifact-readable",
                "level": "P1",
                "status": artifact_status,
                "claim": "Decision Brief 是 canonical 输入的可读取投影",
                "checker": {"name": "askovo decision_brief", "version": str(study.get("method_version") or "dev"),
                            "independence": "executor_observed"},
                "evidence_refs": [] if stale else ["decision-brief-json", "decision-brief-md"],
                "scope": "当前 study 输入指纹；只证明产物投影，不证明建议正确",
                "reason": artifact_reason,
                "valid_until": None,
            },
            {
                "check_id": "independent-semantic-review",
                "level": "P3",
                "status": "UNCHECKED",
                "claim": "独立复核者接受研究语义与证据资格",
                "checker": {"name": "external semantic reviewer", "version": "pending",
                            "independence": "independent_validator"},
                "evidence_refs": [],
                "scope": "研究语义、反证和适用范围",
                "reason": "导出器不能替代独立人工语义复核",
                "valid_until": None,
            },
            {
                "check_id": "external-decision-adoption",
                "level": "P4",
                "status": "UNCHECKED",
                "claim": "负责人实际采用、拒绝或改期该决定",
                "checker": {"name": "decision owner receipt", "version": "pending",
                            "independence": "external_observation"},
                "evidence_refs": [],
                "scope": "实际投入或路线图处置；不包含因果归因",
                "reason": "没有随包提供独立外部处置回执",
                "valid_until": None,
            },
        ]
        checks_doc = {"schema": CHECKS_SCHEMA, "contract_id": contract_id, "checks": checks}
        replay = {
            "schema": REPLAY_SCHEMA,
            "contract_id": contract_id,
            "status": "AVAILABLE",
            "commands": [
                {"name": "rebuild-brief", "argv": ["askovo", "brief", "${STUDY_DIR}"]},
                {"name": "validate-proof", "argv": ["python3", "-m", "ovo_acceptance", "proof", "${PROOF_DIR}"]},
            ],
            "inputs": [
                {"ref": entry["source_ref"], "sha256": entry["source_hash"]}
                for entry in entries if entry["kind"] == "source_document"
            ],
            "missing": [],
        }
        proof = {
            "schema": PROOF_SCHEMA,
            "proof_id": "proof-%s" % safe_study_id,
            "contract_id": contract_id,
            "product": "askovo",
            "generated_at": generated_at,
            "environment": {
                "product_version": str(study.get("method_version") or "dev"),
                "runtime": "Python " + sys.version.split()[0],
                "platform": sys.platform,
            },
            "artifacts": [
                {"artifact_id": "decision-brief-json", "path": "artifacts/decision-brief.json",
                 "sha256": _digest(brief_json), "classification": classification},
                {"artifact_id": "decision-brief-md", "path": "artifacts/decision-brief.md",
                 "sha256": _digest(brief_md), "classification": classification},
            ],
            "replay": {"manifest": "replay/manifest.json", "status": "AVAILABLE", "missing": []},
            "limitations": list(brief.get("limitations") or []) + [
                "Proof Bundle 不批准产品决定，不证明商业结果或因果",
                "P3 独立语义复核与 P4 外部采用保持未检查，直到另有合格回执",
            ],
        }
        _write_json(temp / "bundle.json", bundle)
        _write_json(temp / "contract.json", contract)
        with (temp / "trace.jsonl").open("w", encoding="utf-8") as handle:
            for step in steps:
                handle.write(json.dumps(step, ensure_ascii=False) + "\n")
        _write_json(temp / "checks.json", checks_doc)
        _write_json(temp / "proof.json", proof)
        _write_json(temp / "replay" / "manifest.json", replay)
        temp.rename(out_dir)
        return {
            "status": "exported",
            "schema": "askovo.proof-export/1",
            "out": str(out_dir),
            "proof_id": proof["proof_id"],
            "proof_status": _status(checks),
            "source_fingerprint": brief.get("source_fingerprint"),
            "study_mutated": False,
            "causality": "not_claimed",
        }
    except decision_brief.BriefError as exc:
        shutil.rmtree(temp, ignore_errors=True)
        raise ProofExportError(str(exc), exc.reason_code) from exc
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

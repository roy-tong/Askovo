#!/usr/bin/env python3
"""askovo MCP server: expose the deterministic CLI surface as MCP tools over stdio.

This server speaks the Model Context Protocol stdio transport (newline-delimited
JSON-RPC 2.0) using only the Python standard library. It wraps the same command
functions used by askovo.py, so the Skill, the CLI, and MCP share one behavior.
It adds no research judgment and performs no network collection.

Exit codes are preserved inside tool results:
0 success, 1 failed gate (a valid research status), 3 no feasible platform
(also a valid research status), 2 usage or environment error (reported as a
tool error).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# Run both from a Git checkout and from the bundled askovo/runtime/scripts.
# The standalone MCP entry must locate the shared package, not duplicate it.
_PACKAGE_PARENT = HERE.parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))
ASKOVO_CLI_PATH = HERE / "askovo.py"

_spec = importlib.util.spec_from_file_location("askovo_cli", ASKOVO_CLI_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load askovo.py beside this server: {ASKOVO_CLI_PATH}")
askovo_cli = importlib.util.module_from_spec(_spec)
sys.modules["askovo_cli"] = askovo_cli
_spec.loader.exec_module(askovo_cli)

SERVER_NAME = "askovo"
SERVER_VERSION = askovo_cli.ASKOVO_VERSION
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_INSTRUCTIONS = (
    "Askovo product and business reasoning, deterministic surface for product managers, user "
    "researchers, user operations, market analysis, requirements analysis and business analysis. "
    "Start with askovo_route or askovo_do across software / hardware / consumer / automotive / "
    "mobile. The primary spine is scene -> user -> pain -> need -> feature -> product -> business; "
    "collection and analysis only support weak nodes and inferences. askovo_roles provides 80 role "
    "contracts, KPI/SOP/templates, 11 industry overlays and orchestration-only study workbenches. "
    "(1) askovo_do scaffolds the study and product-reasoning.json; askovo_roles scaffold explicitly creates the bound role workbench; (2) askovo_chain renders the "
    "reasoning canvas; (3) askovo_platforms and askovo_collect gather permitted supporting "
    "material; (4) askovo_analyze describes it; optional semantic=true adds constrained unverified "
    "candidates with exact quotes and a critic pass, never evidence levels or conclusions; "
    "askovo_semantic lists/validates candidates and exports only CLI-reviewed E2 collected statements; "
    "semantic accept/reject is human-only in the CLI; (5) askovo_audit checks product/business "
    "rationales, evidence gates and per-claim verdicts; (6) askovo_deliver assembles the "
    "business plan (plan), corpus analysis (analysis), chain-led memo, MRD, PRD, BRD, ops or tracker. Legacy text/platform planning remains available as "
    "askovo_plan; askovo_check remains the low-level gate command. "
    "askovo_decide_start / askovo_decide_status / askovo_decide_result track one decision question "
    "as a task over the same loop (dry run by default; decide never authorizes or assesses). "
    "askovo_primary_research exposes local survey/landing/prototype/diary create, import, status and export plus explicit token invitations and source-bound deployment; serve, "
    "public recruitment and candidate accept/reject remain outside MCP. "
    "askovo_research_watch creates and explicitly ticks durable local decision-review watches; execute reuses a separately authorized research run before review; "
    "no path is a daemon, automatically authorizes collection, promotes evidence or rewrites decisions. "
    "exit codes: 1 = failed gate or claim exceeding evidence, 3 = no feasible platform or "
    "adapter, 4 = safety/ethics gate not acknowledged. These are research statuses to report, "
    "never reasons to substitute a commercial provider, merchant API, saved login, internal "
    "endpoint, or browser automation. Records are not users; convenience samples do not "
    "support prevalence or market-size claims. For judgment rules read the Skill, not just "
    "these tools."
)
PLATFORMS = ("reddit", "x", "youtube", "amazon", "jd", "taobao", "kickstarter")
STAGES = askovo_cli.STAGES

_PLATFORM_TYPES_TEXT = "comma-separated: forum,social,video,ecommerce,crowdfunding"


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _need_string(arguments: dict[str, Any]) -> str:
    """The request text: `query` (CLI vocabulary) is accepted as an alias of `need`."""
    value = arguments.get("need")
    if value is None:
        value = arguments.get("query")
    return _string(value, "need")


def _optional_string(arguments: dict[str, Any], field: str) -> str | None:
    value = arguments.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string when provided")
    return value


def _boolean(arguments: dict[str, Any], field: str, default: bool = False) -> bool:
    value = arguments.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _platform_list(arguments: dict[str, Any], field: str) -> list[str]:
    value = arguments.get(field, [])
    if isinstance(value, str):
        tokens = [token.strip() for token in value.split(",")]
    elif isinstance(value, list):
        tokens = [str(token).strip() for token in value]
    else:
        raise ValueError(f"{field} must be a list or comma-separated string")
    invalid = [token for token in tokens if token and token not in PLATFORMS]
    if invalid:
        raise ValueError(f"unknown platforms in {field}: {', '.join(invalid)}")
    return [token for token in tokens if token]


def _namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _build_plan(arguments: dict[str, Any]) -> argparse.Namespace:
    study_dir = _string(arguments.get("study_dir"), "study_dir")
    goal = _string(arguments.get("goal"), "goal")
    region = _string(arguments.get("region"), "region")
    platform_types = _string(arguments.get("platform_types"), "platform_types")
    mode = str(arguments.get("mode", "standard") or "standard").replace("-", "_")
    if mode not in askovo_cli.PLAN_MODES:
        raise ValueError(f"mode must be one of: {', '.join(askovo_cli.PLAN_MODES)}")
    sample_size = arguments.get("sample_size")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 1:
        raise ValueError("sample_size must be a positive integer")
    return _namespace(
        study_dir=study_dir,
        goal=goal,
        region=region,
        sample_size=sample_size,
        platform_types=platform_types,
        market=_optional_string(arguments, "market"),
        languages=_optional_string(arguments, "languages"),
        time_window=_optional_string(arguments, "time_window"),
        decision=_optional_string(arguments, "decision"),
        study_id=_optional_string(arguments, "study_id"),
        title=_optional_string(arguments, "title"),
        mode=mode,
        force=bool(arguments.get("force", False)),
    )


def _build_init(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        study_id=_string(arguments.get("study_id"), "study_id"),
        title=_string(arguments.get("title"), "title"),
        decision=_string(arguments.get("decision"), "decision"),
        platform=_platform_list(arguments, "platforms"),
    )


def _build_check(arguments: dict[str, Any]) -> argparse.Namespace:
    stage = arguments.get("stage", "full")
    if stage not in STAGES:
        raise ValueError(f"stage must be one of: {', '.join(STAGES)}")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        stage=stage,
        write_report=_boolean(arguments, "write_report"),
    )


def _build_audit(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        claim=_optional_string(arguments, "claim"),
        json=True,
    )


def _build_signals(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_lexicon(arguments: dict[str, Any]) -> argparse.Namespace:
    min_per_term = arguments.get("min_per_term")
    if min_per_term is not None and (
        not isinstance(min_per_term, int) or isinstance(min_per_term, bool) or min_per_term < 1
    ):
        raise ValueError("min_per_term must be a positive integer when provided")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        min_per_term=min_per_term,
    )


def _build_report(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        output=_optional_string(arguments, "output"),
    )


def _build_connectors(arguments: dict[str, Any]) -> argparse.Namespace:
    platform = _optional_string(arguments, "platform")
    if platform is not None and platform not in PLATFORMS:
        raise ValueError(f"platform must be one of: {', '.join(PLATFORMS)}")
    return _namespace(platform=platform, include_blocked=_boolean(arguments, "include_blocked"))


def _string_list(arguments: dict[str, Any], key: str) -> list[str] | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError(f"{key} must be a string or array of strings")


def _build_route(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        need=_need_string(arguments),
        domain=_optional_string(arguments, "domain"),
        stage=_optional_string(arguments, "stage"),
        intent=_optional_string(arguments, "intent"),
        json=True,
    )


def _build_do(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        need=_need_string(arguments),
        study=_optional_string(arguments, "study"),
        domain=_optional_string(arguments, "domain"),
        stage=_optional_string(arguments, "stage"),
        intent=_optional_string(arguments, "intent"),
        dry_run=_boolean(arguments, "dry_run"),
        ack_risk=_boolean(arguments, "ack_risk"),
        force=_boolean(arguments, "force"),
        json=True,
    )


def _build_platforms(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        need=_need_string(arguments),
        domain=_optional_string(arguments, "domain"),
        claim_type=_string_list(arguments, "claim_type"),
        bulk=_boolean(arguments, "bulk"),
        field_notes=_boolean(arguments, "field_notes"),
        strategies=_boolean(arguments, "strategies"),
        policies=_boolean(arguments, "policies"),
        platform=_optional_string(arguments, "platform"),
        json=True,
    )


def _build_collect(arguments: dict[str, Any]) -> argparse.Namespace:
    limit = arguments.get("limit", 100)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        platform=_string(arguments.get("platform"), "platform"),
        query=_string(arguments.get("query"), "query"),
        limit=limit,
        dry_run=_boolean(arguments, "dry_run", True),
        fixture=_optional_string(arguments, "fixture"),
        cdp_url=_optional_string(arguments, "cdp_url"),
        url=_optional_string(arguments, "url"),
        ack_terms=_boolean(arguments, "ack_terms"),
        attach_existing=_boolean(arguments, "attach_existing"),
    )


def _build_queue_add(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        platform=_string(arguments.get("platform"), "platform"),
        query=_string(arguments.get("query"), "query"),
        limit=int(arguments.get("limit", 100)),
        fixture=_optional_string(arguments, "fixture"),
        cdp_url=_optional_string(arguments, "cdp_url"),
        url=_optional_string(arguments, "url"),
        ack_terms=_boolean(arguments, "ack_terms"),
        max_attempts=int(arguments.get("max_attempts", 3)),
    )


def _build_queue_run(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        workers=int(arguments.get("workers", 2)),
        min_interval=arguments.get("min_interval"),
        lease_seconds=float(arguments.get("lease_seconds", 300)),
    )


def _build_queue_status(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_stage(arguments: dict[str, Any]) -> argparse.Namespace:
    args_value = arguments.get("args", [])
    if not isinstance(args_value, list) or not all(isinstance(item, str) for item in args_value):
        raise ValueError("args must be an array of strings when provided")
    return _namespace(
        stage_name=_string(arguments.get("stage"), "stage"),
        stage_args=list(args_value),
    )


def _build_economics(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_psm(arguments: dict[str, Any]) -> argparse.Namespace:
    currency = arguments.get("currency", "未注明币种")
    if not isinstance(currency, str):
        raise ValueError("currency must be a string when provided")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        input=_string(arguments.get("input"), "input"),
        currency=currency,
    )


def _build_research(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("plan", "status", "run"):
        raise ValueError("action must be plan, status or run")
    actions = _optional_string(arguments, "actions")
    if action == "plan" and not actions:
        raise ValueError("actions is required for research plan")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        action=action,
        actions=actions,
        reset=False,
        authorize=False,   # human-only CLI operation; MCP never self-authorizes
        by="",
        max_steps=int(arguments.get("max_steps", 1)),
        analyze=_boolean(arguments, "analyze"),
    )


def _build_decide_start(arguments: dict[str, Any]) -> argparse.Namespace:
    task = arguments.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an askovo.decision-task/1 object")
    return _namespace(
        action="start",
        task_id="",
        workspace=_optional_string(arguments, "workspace") or "",
        input="",
        question="",
        repo="",
        decision_type="",
        max_records=askovo_cli.decide.DEFAULT_MAX_RECORDS,
        fixture="",
        deadline="",
        approved_by="",
        allowed_source=[],
        study=_optional_string(arguments, "study") or "",
        task="",
        run=_boolean(arguments, "run"),
        dry_run=False,
        format="json",
        by="",
        since="",
        task_input=task,
    )


def _build_decide_task_id(action: str):
    def build(arguments: dict[str, Any]) -> argparse.Namespace:
        return _namespace(
            action=action,
            task_id=_string(arguments.get("task_id"), "task_id"),
            workspace=_optional_string(arguments, "workspace") or "",
            input="",
            question="",
            repo="",
            decision_type="",
            max_records=askovo_cli.decide.DEFAULT_MAX_RECORDS,
            fixture="",
            deadline="",
            approved_by="",
            allowed_source=[],
            study="",
            task="",
            run=False,
            dry_run=False,
            format="json",
            by=_optional_string(arguments, "by") or "",
            since=_optional_string(arguments, "since") or "",
        )

    return build


def _build_loop(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("plan", "status", "report", "run"):
        raise ValueError("action must be plan, status, report or run")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        action=action,
        reset=False,
        authorize=False,   # human-only CLI operation; MCP never self-authorizes
        by="",
        max_rounds=int(arguments.get("max_rounds", 3)),
        max_actions=int(arguments.get("max_actions", 3)),
        max_records=int(arguments.get("max_records", 300)),
    )


def _build_review(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        json=_boolean(arguments, "json"),
    )


def _build_research_watch(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("create", "status", "run", "execute", "pause", "resume", "resolution"):
        raise ValueError("research watch action must be create, status, run, execute, pause, resume or resolution")
    values = {
        "watch_action": action,
        "study_dir": _string(arguments.get("study_dir"), "study_dir"),
        "question": "",
        "interval_hours": 0,
        "by": "",
        "delta_file": "",
        "delta_authorized_by": "",
        "now": "",
        "due": _boolean(arguments, "due"),
        "watch_id": "",
        "max_steps": 1,
    }
    if action == "create":
        interval = arguments.get("interval_hours")
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
            raise ValueError("interval_hours must be a positive number")
        values.update(
            question=_string(arguments.get("question"), "question"),
            interval_hours=interval,
            by=_string(arguments.get("by"), "by"),
            delta_file=_optional_string(arguments, "delta_file") or "",
            delta_authorized_by=_optional_string(arguments, "delta_authorized_by") or "",
        )
    if action in ("pause", "resume", "resolution"):
        values["watch_id"] = _string(arguments.get("watch_id"), "watch_id")
    elif action in ("run", "execute"):
        values["watch_id"] = _optional_string(arguments, "watch_id") or ""
    if action == "execute":
        steps = arguments.get("max_steps", 1)
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 20:
            raise ValueError("max_steps must be an integer from 1 to 20")
        values["max_steps"] = steps
    return _namespace(**values)


def _build_decision(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("record", "adopt", "list", "replay"):
        raise ValueError("action must be record, adopt, list or replay")
    version = arguments.get("version")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 1):
        raise ValueError("version must be a positive integer")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        action=action,
        chain=_optional_string(arguments, "chain") or "",
        record_id=_optional_string(arguments, "record_id") or "",
        version=version,
        by=_optional_string(arguments, "by") or "",
        scope=_optional_string(arguments, "scope") or "",
        adoption_evidence=_string_list(arguments, "adoption_evidence") or [],
        decision=_optional_string(arguments, "decision") or "",
        hypothesis=_optional_string(arguments, "hypothesis") or "",
        observation=_string_list(arguments, "observation") or [],
        evidence=_string_list(arguments, "evidence") or [],
        contradiction=_string_list(arguments, "contradiction") or [],
        recommendation=_optional_string(arguments, "recommendation") or "",
        revision=_optional_string(arguments, "revision") or "",
        next_action=_optional_string(arguments, "next_action") or "",
        json=_boolean(arguments, "json", True),
    )


def _build_analyze(arguments: dict[str, Any]) -> argparse.Namespace:
    provider = _optional_string(arguments, "semantic_provider") or "auto"
    if provider not in ("auto", "openai", "offline"):
        raise ValueError("semantic_provider must be auto, openai or offline")
    retrieval = _optional_string(arguments, "retrieval") or "auto"
    if retrieval not in ("auto", "keyword", "embedding"):
        raise ValueError("retrieval must be auto, keyword or embedding")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        question=_optional_string(arguments, "question"),
        semantic=_boolean(arguments, "semantic", False),
        semantic_provider=provider,
        allow_external=_boolean(arguments, "allow_external", False),
        semantic_max_records=int(arguments.get("semantic_max_records") or 120),
        semantic_batch_size=int(arguments.get("semantic_batch_size") or 20),
        retrieval=retrieval,
    )


def _command_semantic(args: argparse.Namespace) -> int:
    action = str(args.action)
    if action not in ("list", "export", "validate"):
        raise ValueError("action must be list, export or validate; semantic review is human-only via CLI")
    return int(getattr(askovo_cli.semantic_candidates, "cmd_" + action)(args))


def _build_semantic(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("list", "export", "validate"):
        raise ValueError("action must be list, export or validate; semantic review is human-only via CLI")
    if action == "validate" and not _optional_string(arguments, "file"):
        raise ValueError("file is required for validate")
    return _namespace(
        action=action,
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        file=_optional_string(arguments, "file") or "",
        candidate=_optional_string(arguments, "candidate") or "",
        decision=_optional_string(arguments, "decision") or "",
        reviewer=_optional_string(arguments, "reviewer") or "",
        note=_optional_string(arguments, "note") or "",
        store=_optional_string(arguments, "store") or "",
        by=_optional_string(arguments, "by") or "",
        product=_optional_string(arguments, "product") or "",
        region=_optional_string(arguments, "region") or "",
        export_now=_boolean(arguments, "export_now", False),
        json=True,
    )


def _build_instruments(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_codebook(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _command_observation(args: argparse.Namespace) -> int:
    action = str(args.action)
    if action not in ("validate", "record", "list", "export"):
        raise ValueError("action must be validate, record, list or export")
    return int(getattr(askovo_cli.observation, "cmd_" + action)(args))


def _build_observation(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("validate", "record", "list", "export"):
        raise ValueError("action must be validate, record, list or export")
    return _namespace(
        action=action,
        file=_optional_string(arguments, "file") or "",
        store=_optional_string(arguments, "store") or "",
        study=_optional_string(arguments, "study") or "",
        replace=_boolean(arguments, "replace", False),
        json=_boolean(arguments, "json", True),
    )


def _build_proof_export(arguments: dict[str, Any]) -> argparse.Namespace:
    classification = _optional_string(arguments, "classification") or "private"
    if classification not in ("private", "synthetic", "public-redacted"):
        raise ValueError("classification must be private, synthetic or public-redacted")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        out=_string(arguments.get("out"), "out"),
        by=_string(arguments.get("by"), "by"),
        task=_optional_string(arguments, "task") or "",
        classification=classification,
    )


def _build_deliver(arguments: dict[str, Any]) -> argparse.Namespace:
    kind = arguments.get("kind", "memo")
    if kind not in ("memo", "report", "mrd", "prd", "brd", "ops", "decision", "tracker", "signoff", "plan", "needs", "analysis", "role", "lifecycle", "web"):
        raise ValueError("kind must be memo, report, mrd, prd, brd, ops, decision, tracker, signoff, plan, needs, analysis, role, lifecycle or web")
    role = _string(arguments.get("role"), "role") if kind == "role" else _optional_string(arguments, "role")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        kind=kind,
        role=role,
        deliverable=_optional_string(arguments, "deliverable"),
        industry=_optional_string(arguments, "industry"),
        chain=_optional_string(arguments, "chain"),
        baseline=_optional_string(arguments, "baseline"),
    )


def _build_boundary(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        requirements=_string(arguments.get("requirements"), "requirements"),
        output=_string(arguments.get("output"), "output"),
        match_threshold=float(arguments.get("match_threshold", 0.30)),
        inflate_ratio=float(arguments.get("inflate_ratio", 3.0)),
    )


def _build_cost(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("log", "report"):
        raise ValueError("action must be log or report")
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        action=action,
        task=_optional_string(arguments, "task") or "",
        minutes=int(arguments["minutes"]) if arguments.get("minutes") is not None else 0,
        baseline_minutes=int(arguments["baseline_minutes"]) if arguments.get("baseline_minutes") is not None else None,
        note=_optional_string(arguments, "note") or "",
    )


def _build_roles(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action not in ("list", "show", "recommend", "scaffold", "template"):
        raise ValueError("action must be list, show, recommend, scaffold or template")
    role_value: Any = ""
    study_dir = ""
    goal = ""
    if action in ("show", "template"):
        role_value = _string(arguments.get("role"), "role")
    elif action == "recommend":
        goal = _string(arguments.get("goal"), "goal")
    elif action == "scaffold":
        study_dir = _string(arguments.get("study_dir"), "study_dir")
        raw_roles = arguments.get("roles", [])
        if not isinstance(raw_roles, list) or any(not isinstance(item, str) or not item.strip() for item in raw_roles):
            raise ValueError("roles must be an array of non-empty role id strings")
        role_value = raw_roles
    task = _optional_string(arguments, "task")
    if task is not None and task not in askovo_cli.role_catalog.TASK_TYPES:
        raise ValueError("task must be one of: " + ", ".join(askovo_cli.role_catalog.TASK_TYPES))
    scale = _optional_string(arguments, "scale")
    if scale is not None and scale not in askovo_cli.role_catalog.SCALE_CAPS:
        raise ValueError("scale must be lean, standard or cross_functional")
    return _namespace(
        action=action,
        lifecycle=_optional_string(arguments, "lifecycle"),
        industry=_optional_string(arguments, "industry"),
        query=_optional_string(arguments, "query"),
        role=role_value,
        goal=goal,
        stage=_optional_string(arguments, "stage"),
        base_domain=_optional_string(arguments, "base_domain"),
        task=task,
        scale=scale,
        all_templates=_boolean(arguments, "all_templates"),
        study_dir=study_dir,
        chain=_optional_string(arguments, "chain"),
        deliverable=_optional_string(arguments, "deliverable"),
        output=_optional_string(arguments, "output"),
        force=False,
        json=True,
    )


def _build_methods(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        domain=_string(arguments.get("domain"), "domain"),
        stage=_optional_string(arguments, "stage"),
        json=True,
    )


def _build_domains(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(json=True)


def _tool_platform_map(arguments: dict[str, Any]) -> dict[str, Any]:
    platform_map = askovo_cli._load_platform_map()
    registry = askovo_cli._connector_index()
    platforms: dict[str, Any] = {}
    for platform, meta in platform_map.get("platforms", {}).items():
        entry: dict[str, Any] = dict(meta) if isinstance(meta, dict) else {}
        connector_id = entry.get("connector_id")
        if connector_id and connector_id in registry:
            connector = registry[connector_id]
            entry["registry_decision"] = connector.get("decision")
            entry["reviewed_revision"] = connector.get("reviewed_revision")
        platforms[platform] = entry
    return {
        "exit_code": 0,
        "result": {
            "schema_version": platform_map.get("schema_version"),
            "updated_at": platform_map.get("updated_at"),
            "platform_types": platform_map.get("platform_types", {}),
            "regions": platform_map.get("regions", {}),
            "platforms": platforms,
            "meaning": (
                "Availability, not permission: enabled platforms still need study-specific "
                "access, policy, and data-rights review."
            ),
        },
    }


def _build_primary_research(arguments: dict[str, Any]) -> argparse.Namespace:
    action = _string(arguments.get("action"), "action")
    if action in ("survey_create", "survey_status", "survey_export_candidates"):
        values = {"survey_action": action.replace("survey_", "").replace("export_candidates", "export-candidates")}
        if action == "survey_create":
            values.update(spec=_string(arguments.get("spec"), "spec"),
                          out=_string(arguments.get("out"), "out"))
        else:
            values["dir"] = _string(arguments.get("dir"), "dir")
            if action == "survey_export_candidates":
                values["out"] = _string(arguments.get("out"), "out")
        return _namespace(**values)
    if action in ("landing_create", "landing_status", "landing_export", "landing_deploy"):
        values = {"landing_action": action.replace("landing_", "")}
        if action == "landing_create":
            values.update(spec=_string(arguments.get("spec"), "spec"),
                          out=_string(arguments.get("out"), "out"))
        else:
            values["dir"] = _string(arguments.get("dir"), "dir")
            if action == "landing_export":
                values.update(design=_string(arguments.get("design"), "design"),
                              out=_string(arguments.get("out"), "out"))
            elif action == "landing_deploy":
                values.update(adapter=_string(arguments.get("adapter"), "adapter"),
                              out=_string(arguments.get("out"), "out"))
        return _namespace(**values)
    if action == "screening_export":
        return _namespace(plan_action="screen",
                          plan=_string(arguments.get("plan"), "plan"),
                          file=_string(arguments.get("file"), "file"),
                          by=_string(arguments.get("by"), "by"),
                          out=_string(arguments.get("out"), "out"), at="")
    if action == "screening_invitations":
        return _namespace(plan_action="invitations",
                          plan=_string(arguments.get("plan"), "plan"),
                          file=_string(arguments.get("file"), "file"),
                          experiment_id=_string(arguments.get("experiment_id"), "experiment_id"),
                          out=_string(arguments.get("out"), "out"))
    if action in ("prototype_create", "prototype_import", "prototype_status", "prototype_export"):
        values = {"experiment_kind": "prototype",
                  "prototype_action": action.replace("prototype_", "")}
        if action == "prototype_create":
            values.update(spec=_string(arguments.get("spec"), "spec"),
                          out=_string(arguments.get("out"), "out"))
        else:
            values["dir"] = _string(arguments.get("dir"), "dir")
            if action == "prototype_import":
                values.update(file=_string(arguments.get("file"), "file"),
                              by=_string(arguments.get("by"), "by"))
            elif action == "prototype_export":
                values["out"] = _string(arguments.get("out"), "out")
        return _namespace(**values)
    if action in ("diary_create", "diary_import", "diary_status", "diary_export"):
        values = {"experiment_kind": "diary", "diary_action": action.replace("diary_", "")}
        if action == "diary_create":
            values.update(spec=_string(arguments.get("spec"), "spec"),
                          out=_string(arguments.get("out"), "out"))
        else:
            values["dir"] = _string(arguments.get("dir"), "dir")
            if action == "diary_import":
                values.update(file=_string(arguments.get("file"), "file"),
                              by=_string(arguments.get("by"), "by"))
            elif action == "diary_export":
                values["out"] = _string(arguments.get("out"), "out")
            else:
                values["at"] = str(arguments.get("at") or "")
        return _namespace(**values)
    raise ValueError("primary research action must be local create/import/status/export; serve and human review stay in CLI")


def _command_primary_research(args: argparse.Namespace) -> int:
    if hasattr(args, "plan_action"):
        return askovo_cli.command_capture_plan(args)
    if hasattr(args, "survey_action"):
        return askovo_cli.command_survey(args)
    return askovo_cli.command_experiment(args)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "askovo_plan",
        "description": (
            "Turn a research goal, region, sample size, and platform types into an Askovo study "
            "workspace: platform feasibility from the connector registry, sample quotas, scaled "
            "route targets, a feasibility report, and a collection task list. Exit code 3 means "
            "no requested platform has an enabled connector; report the gap instead of "
            "substituting a commercial or login-based route."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string", "description": "absolute path for the new study workspace"},
                "goal": {"type": "string", "description": "research target: product, user, or scene"},
                "region": {"enum": ["cn", "overseas", "global"]},
                "sample_size": {"type": "integer", "minimum": 1, "maximum": 100000},
                "platform_types": {"type": "string", "description": _PLATFORM_TYPES_TEXT},
                "mode": {
                    "enum": ["standard", "unnamed-experience"],
                    "description": "unnamed-experience grounds a seed lexicon (edge language, substitute behaviors, psychophysical dimensions, literature anchors) before keyword routes",
                },
                "market": {"type": "string", "description": "optional market label, e.g. us or de"},
                "languages": {"type": "string", "description": "comma-separated language codes"},
                "time_window": {"type": "string", "description": "START:END ISO dates"},
                "decision": {"type": "string", "description": "decision question this study informs"},
                "study_id": {"type": "string"},
                "title": {"type": "string"},
                "force": {
                    "type": "boolean",
                    "description": "existing study: write a plan proposal under 01-sources/plan-proposal/ without overwriting study.json or source-plan.csv",
                },
            },
            "required": ["study_dir", "goal", "region", "sample_size", "platform_types"],
        },
    },
    {
        "name": "askovo_init",
        "description": (
            "Create an Askovo study workspace from the bundled template with selected platform "
            "route files. Use askovo_plan instead when the region and platform types are the input."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "study_id": {"type": "string"},
                "title": {"type": "string"},
                "decision": {"type": "string"},
                "platforms": {
                    "type": "array",
                    "items": {"enum": list(PLATFORMS)},
                    "description": "platforms to enable; omit for a platform-less study",
                },
            },
            "required": ["study_dir", "study_id", "title", "decision"],
        },
    },
    {
        "name": "askovo_check",
        "description": (
            "Audit one research stage (design, evidence, decision, or full). A failed gate is a "
            "valid research status: repair the artifact or report the evidence gap."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "stage": {"enum": list(STAGES)},
                "write_report": {"type": "boolean", "description": "write 05-audit/latest.json and latest.md"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_audit",
        "description": (
            "Audit a study end to end: run all gates, compute deterministic corpus signals, and "
            "return per-claim verdicts (supported / exceeds_evidence / open). Use this first when "
            "the user asks whether existing material can support a decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "claim": {"type": "string", "description": "optional filter: claim id, title, or status"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_signals",
        "description": (
            "Compute deterministic corpus signals from 02-data/evidence.jsonl into "
            "04-findings/signals.json: level/role distributions, role x level matrix, "
            "source-family concentration, duplicate rate, time spread, chain readiness, gates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"study_dir": {"type": "string"}},
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_lexicon",
        "description": (
            "Compute lexicon term yield and stock-corpus sufficiency for an unnamed-experience "
            "study: per-term and per-grounding-path record counts, acceptance-association "
            "proxy, zero-yield terms, demand fossils, and a sufficiency verdict against "
            "--min-per-term. Exit code 1 (insufficient) means collect more, not loosen the gate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "min_per_term": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "minimum graded records per lexicon term",
                },
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_report",
        "description": (
            "Assemble the Chinese research-status report into 06-report/research-status.md from the study "
            "contract, product chain, source plan, manifests, signals, judgments, and blocked routes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "output": {"type": "string", "description": "report path; defaults to 06-report/research-status.md"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_connectors",
        "description": (
            "List reviewed open-source connector decisions from the registry. Blocked entries "
            "are hidden unless include_blocked is true; keep them visible when choosing routes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"enum": list(PLATFORMS)},
                "include_blocked": {"type": "boolean"},
            },
        },
    },
    {
        "name": "askovo_route",
        "description": (
            "Classify a request into product domain (software/hardware/consumer/"
            "automotive/mobile), lifecycle stage, intent, claim types, risk flags, a "
            "seven-node product/business reasoning flow and a recommended method pack. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "need": {"type": "string", "description": "the request/question text"},
                "query": {"type": "string", "description": "alias of need (CLI vocabulary)"},
                "domain": {"enum": ["software", "hardware", "consumer", "automotive", "mobile"]},
                "stage": {"enum": ["discovery", "concept", "prototype", "validation", "pricing", "prelaunch", "postlaunch", "audit"]},
                "intent": {"enum": ["route", "plan", "instruments", "import", "sources", "collect", "analyze", "audit", "deliver"]},
            },
            "required": ["need"],
        },
    },
    {
        "name": "askovo_do",
        "description": (
            "The single entry point: route the request and scaffold a study with a seven-node "
            "product/business reasoning canvas, method choice, research plan, evidence plan and "
            "instruments. Safety-gated requests return exit 4 until a human acknowledges the review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "need": {"type": "string", "description": "the request/question text"},
                "query": {"type": "string", "description": "alias of need (CLI vocabulary)"},
                "study": {"type": "string", "description": "workspace path; omit for a default path"},
                "domain": {"enum": ["software", "hardware", "consumer", "automotive", "mobile"]},
                "stage": {"enum": ["discovery", "concept", "prototype", "validation", "pricing", "prelaunch", "postlaunch", "audit"]},
                "intent": {"enum": ["route", "plan", "instruments", "import", "sources", "collect", "analyze", "audit", "deliver"]},
                "dry_run": {"type": "boolean", "default": False},
                "ack_risk": {"type": "boolean", "default": False},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["need"],
        },
    },
    {
        "name": "askovo_platforms",
        "description": (
            "Rank platforms by data availability, access mode, evidence fit, bulk capability, "
            "bias and legal limits. Use before promising any platform coverage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "need": {"type": "string", "description": "the request/question text"},
                "query": {"type": "string", "description": "alias of need (CLI vocabulary)"},
                "domain": {"enum": ["software", "hardware", "consumer", "automotive", "mobile"]},
                "claim_type": {"type": "array", "items": {"enum": ["need", "acceptance", "usability", "performance", "commercial", "safety"]}},
                "bulk": {"type": "boolean", "default": False},
                "field_notes": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return the field-verified restriction/solution notes for the ranked platforms.",
                },
                "strategies": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return the cross-platform collection strategies (rotation, lanes, quota, cooldowns).",
                },
                "policies": {
                    "type": "boolean",
                    "default": False,
                    "description": "Return the enforced CDP runtime budgets (one goto per cell, timeout cooldown, session time-box, budget headroom).",
                },
                "platform": {
                    "type": "string",
                    "description": "Filter to one platform id (catalog platform or a field-note source type).",
                },
            },
            "required": ["need"],
        },
    },
    {
        "name": "askovo_collect",
        "description": (
            "Run a supported collector, authorized visible-page CDP transport, or local fixture/export, "
            "with quota, run manifest and dedup. Defaults to dry-run. Blocked platforms return exit 3."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "platform": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "default": 100},
                "dry_run": {"type": "boolean", "default": True},
                "fixture": {"type": "string", "description": "local JSONL/CSV for offline collection"},
                "cdp_url": {"type": "string", "description": "Chrome DevTools endpoint, e.g. http://127.0.0.1:9222"},
                "url": {"type": "string", "description": "authorized visible page URL for CDP"},
                "ack_terms": {"type": "boolean", "default": False},
                "attach_existing": {
                    "type": "boolean", "default": False,
                    "description": "attach to the exact already-open authorized page without opening a new tab",
                },
            },
            "required": ["study_dir", "platform", "query"],
        },
    },
    {
        "name": "askovo_research",
        "description": (
            "Plan or run a bounded research action list. MCP can create/plan/status and run only "
            "an action list that a human already authorized in the CLI; it cannot authorize a new "
            "list or bypass the study Design gate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "action": {"enum": ["plan", "status", "run"]},
                "actions": {"type": "string", "description": "action-list JSON for plan/run"},
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                "analyze": {"type": "boolean", "default": False},
            },
            "required": ["study_dir", "action"],
        },
    },
    {
        "name": "askovo_research_loop",
        "description": (
            "Detect research gaps, plan round actions and run only the envelope a human already "
            "authorized in the CLI. Collected records become review candidates; the loop never "
            "assigns an evidence level, validates a claim, or bypasses the Design gate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "action": {"enum": ["plan", "status", "report", "run"]},
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3},
                "max_actions": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3},
                "max_records": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 300},
            },
            "required": ["study_dir", "action"],
        },
    },
    {
        "name": "askovo_decide_start",
        "description": (
            "Register or resume one decision question (askovo.decision-task/1, PRD §2.2) as a "
            "tracked research task. Dry run by default: it scopes the task and writes the "
            "research-loop plan without reading a single record. `run` advances only inside an "
            "envelope a human already authorized with `askovo loop authorize`; decide never "
            "authorizes and never assesses. An unsupported decision_type or source is refused "
            "with a reason code instead of a look-alike task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "decide workspace (default: $ASKOVO_DECIDE_HOME or ./askovo-decide)",
                },
                "task": {
                    "type": "object",
                    "description": "askovo.decision-task/1 document (PRD §2.2 minimal start input)",
                },
                "study": {
                    "type": "string",
                    "description": "bind an existing study instead of scaffolding a new one",
                },
                "run": {
                    "type": "boolean",
                    "default": False,
                    "description": "advance past planning; still gated by the loop's human authorization",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "askovo_decide_status",
        "description": (
            "C-01 status projection for one decide task: product state, next_actor, "
            "next_required_action, blocked_reason_code, last_updated_at, "
            "has_pending_external_effect, artifact_refs, budget and the remaining gaps. A status "
            "always names a concrete next step; delivered never means decision_approved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "task_id": {"type": "string", "description": "decide task id, e.g. A-TASK-1A2B3C4D"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "askovo_decide_result",
        "description": (
            "Result projection for one decide task: partial Decision Brief, evidence index, "
            "validation backlog, canonical refs and review status. artifact_status=partial lists "
            "every gap; decision_state stays not_approved because delivered research never means "
            "decision_approved or hypothesis_validated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "task_id": {"type": "string", "description": "decide task id, e.g. A-TASK-1A2B3C4D"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "askovo_review",
        "description": (
            "Deterministic decision review: audit gate, evidence sufficiency, decision readiness, "
            "falsifiability, bias/coverage and deliverable freshness. It reports quality items; it "
            "does not decide, score business success, or replace semantic review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "json": {"type": "boolean", "default": False},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_analyze",
        "description": (
            "Normalize, dedup and describe collected material: platform/claim/form distributions, "
            "time spread, top terms and question-matching excerpts. Descriptive only; no causality."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "question": {"type": "string"},
                "semantic": {"type": "boolean", "default": False,
                             "description": "add constrained unverified candidates; default off"},
                "semantic_provider": {"enum": ["auto", "openai", "offline"], "default": "auto"},
                "allow_external": {"type": "boolean", "default": False,
                                   "description": "authorize sending source text to a remote model"},
                "semantic_max_records": {"type": "integer", "minimum": 1, "default": 120},
                "semantic_batch_size": {"type": "integer", "minimum": 1, "default": 20},
                "retrieval": {"enum": ["auto", "keyword", "embedding"], "default": "auto"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_instruments",
        "description": "Generate interview, observation, task, sensory, pricing, beta or safety instruments for a study.",
        "inputSchema": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]},
    },
    {
        "name": "askovo_codebook",
        "description": "Scaffold a claim-type codebook (need/acceptance/usability/performance/commercial/safety).",
        "inputSchema": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]},
    },
    {
        "name": "askovo_chain",
        "description": "Scaffold if needed and render the canonical scene-user-pain-need-feature-product-business reasoning chain; every node requires a rationale, not just evidence IDs.",
        "inputSchema": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]},
    },
    {
        "name": "askovo_decision",
        "description": (
            "Record, adopt, list and replay versioned DecisionRecords inside the canonical seven-node "
            "product-reasoning.json. Adoption is a separate named-owner receipt with scope and evidence; "
            "it is never inferred from a record or brief. Captures original hypotheses, candidate actions, "
            "basis, observations and revisions. Contradictions may trigger safe hold without auto-validating "
            "candidates, causality, implementation or commercial outcomes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "action": {"enum": ["record", "adopt", "list", "replay"]},
                "chain": {"type": "string", "description": "existing chain id; required for record"},
                "record_id": {"type": "string"},
                "version": {"type": "integer", "minimum": 1},
                "by": {"type": "string", "description": "record: decision-maker; adopt: accountable owner"},
                "scope": {"type": "string", "description": "adopt: exact adopted scope"},
                "adoption_evidence": {"type": "array", "items": {"type": "string"}, "description": "adopt: observable receipt/source"},
                "decision": {"type": "string"},
                "hypothesis": {"type": "string", "description": "declared study hypothesis id"},
                "observation": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "string"}, "description": "registered evidence ids"},
                "contradiction": {
                    "type": "array", "items": {"type": "string"},
                    "description": "registered evidence ids with an existing contradicts/counter mapping",
                },
                "recommendation": {
                    "type": "string",
                    "description": "optional replacement; omitted means deterministic safe hold",
                },
                "revision": {"type": "string"},
                "next_action": {"type": "string"},
                "json": {"type": "boolean", "default": True},
            },
            "required": ["study_dir", "action"],
        },
    },
    {
        "name": "askovo_deliver",
        "description": "Assemble the demand-first needs report (optional baseline comparison), full business plan, decision package, MRD/PRD/BRD, operations/tracker, a role deliverable, or a self-contained Web reading surface projected read-only from the canonical chain. kind=role requires role and never authors findings from a blank template.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "kind": {"enum": ["memo", "report", "mrd", "prd", "brd", "ops", "decision", "tracker", "signoff", "plan", "needs", "analysis", "role", "lifecycle", "web"], "default": "memo"},
                "role": {"type": "string", "description": "kind=role: R52 or role alias"},
                "deliverable": {"type": "string", "description": "kind=role: deliverable id or name"},
                "industry": {"type": "string", "description": "kind=role: optional industry overlay"},
                "chain": {"type": "string", "description": "kind=role: explicit PRxx chain target"},
                "baseline": {"type": "string", "description": "kind=needs: previous study directory or product-reasoning.json"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_methods",
        "description": "List methods for a product domain and lifecycle stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"enum": ["software", "hardware", "consumer", "automotive", "mobile"]},
                "stage": {"enum": ["discovery", "concept", "prototype", "validation", "pricing", "prelaunch", "postlaunch", "audit"]},
            },
            "required": ["domain"],
        },
    },
    {
        "name": "askovo_domains",
        "description": "List the five product research packs and their stages.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "askovo_boundary",
        "description": "F2 boundary audit: deterministic lexical Added/Missing/Inflated lists between a requirements doc and an AI-produced doc; candidates for human review, never error verdicts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "requirements": {"type": "string", "description": "path to the original requirements/intent doc"},
                "output": {"type": "string", "description": "path to the AI-produced doc"},
                "match_threshold": {"type": "number", "default": 0.30},
                "inflate_ratio": {"type": "number", "default": 3.0},
            },
            "required": ["study_dir", "requirements", "output"],
        },
    },
    {
        "name": "askovo_cost",
        "description": "F4 verification cost log: record manual minutes per task (optionally with a no-tool baseline) and report arithmetic totals; not a productivity proof.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "action": {"enum": ["log", "report"]},
                "task": {"type": "string"},
                "minutes": {"type": "integer", "minimum": 1},
                "baseline_minutes": {"type": "integer", "minimum": 1},
                "note": {"type": "string"},
            },
            "required": ["study_dir", "action"],
        },
    },
    {
        "name": "askovo_queue_add",
        "description": "Enqueue a durable collection job. Supports fixtures, CDP visible pages (ack_terms required), retries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "platform": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "default": 100},
                "fixture": {"type": "string"},
                "cdp_url": {"type": "string"},
                "url": {"type": "string"},
                "ack_terms": {"type": "boolean", "default": False},
                "max_attempts": {"type": "integer", "minimum": 1, "default": 3},
            },
            "required": ["study_dir", "platform", "query"],
        },
    },
    {
        "name": "askovo_queue_run",
        "description": "Run the durable queue with N workers, leases, retries and per-platform rate limits until it drains.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "workers": {"type": "integer", "minimum": 1, "default": 2},
                "min_interval": {"type": "number", "description": "override per-platform seconds; 0 for tests"},
                "lease_seconds": {"type": "number", "default": 300},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "askovo_queue_status",
        "description": "Show queue counts, records and recent errors.",
        "inputSchema": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]},
    },
    {
        "name": "askovo_stage",
        "description": (
            "Forward to a consolidated dataset-pipeline stage script (label-feedback, "
            "build-primary-dataset, audit-workbook, ...). Rule labels are candidate discovery; "
            "evidence still requires human gold review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": list(askovo_cli.STAGE_COMMANDS)},
                "args": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["stage"],
        },
    },
    {
        "name": "askovo_economics",
        "description": (
            "Project the business node's unit economics: arithmetic over numeric, unit-matched, "
            "source-referenced inputs only. null means unknown, never zero; not commercial proof."
        ),
        "inputSchema": {"type": "object", "properties": {"study_dir": {"type": "string"}}, "required": ["study_dir"]},
    },
    {
        "name": "askovo_psm",
        "description": (
            "Van Westendorp price-sensitivity projection from a four-question CSV "
            "(too_cheap/cheap/expensive/too_expensive). Stated intent, not paid behavior evidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "input": {"type": "string", "description": "CSV file path"},
                "currency": {"type": "string"},
            },
            "required": ["study_dir", "input"],
        },
    },
    {
        "name": "askovo_roles",
        "description": (
            "Use the 80-role product-innovation operating system. list/search role families; "
            "show responsibilities, KPI formulas/guardrails, SOP quality gates and deliverable "
            "templates; infer task and select a minimum sufficient team by goal/industry/stage; "
            "return an adaptive output contract (primary/supporting deliverables, format, length, "
            "audience, structure, evidence display); scaffold an orchestration-only study "
            "workbench with only the task's templates by default. Role completion never validates "
            "a claim or approves engineering, clinical, safety, compliance, production or commercial release."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"enum": ["list", "show", "recommend", "scaffold", "template"]},
                "query": {"type": "string", "description": "list: role name/alias/work search"},
                "role": {"type": "string", "description": "show/template: R09 or a role alias"},
                "roles": {"type": "array", "items": {"type": "string"}, "description": "scaffold: optional role ids; first is accountable"},
                "goal": {"type": "string", "description": "recommend: product/business goal"},
                "industry": {"type": "string", "description": "one of the 11 industry context ids"},
                "lifecycle": {"type": "string", "description": "L01-L10"},
                "stage": {"enum": list(askovo_cli.sure_engine.STAGES)},
                "task": {"enum": list(askovo_cli.role_catalog.TASK_TYPES), "description": "task type; inferred when omitted"},
                "scale": {"enum": list(askovo_cli.role_catalog.SCALE_CAPS), "description": "lean/standard/cross_functional"},
                "all_templates": {"type": "boolean", "default": False, "description": "scaffold: generate all selected-role templates instead of this task's outputs"},
                "base_domain": {"enum": list(askovo_cli.sure_engine.domain_packs().keys())},
                "study_dir": {"type": "string", "description": "scaffold: existing study workspace"},
                "chain": {"type": "string", "description": "scaffold: canonical PRxx chain; required for multi-chain studies"},
                "deliverable": {"type": "string", "description": "template: deliverable id or name"},
                "output": {"type": "string", "description": "template: optional local Markdown output"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "askovo_platform_map",
        "description": (
            "Show how regions (cn/overseas/global) and platform types resolve to platforms and "
            "registry decisions. Read this before promising a user any platform coverage."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# Local document intake shares the same underlying adapter as askovo document.
# It writes only the explicitly requested local Markdown and provenance sidecar;
# it does not make a research claim or run a network collector.
TOOLS.append({
    "name": "askovo_document",
    "description": ("Convert one authorized local text/PDF/Office document into Markdown "
                    "and a source-hash provenance sidecar. Optional Docling for non-text "
                    "formats; output is unreviewed and not automatically study evidence."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "local source path only"},
            "output": {"type": "string", "description": "local .md output path"},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["source", "output"],
    },
})

TOOLS.append({
    "name": "askovo_observation",
    "description": "Validate, record, list or export the shared product-observation contract; E2 candidates still need human review.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"enum": ["validate", "record", "list", "export"]},
            "file": {"type": "string"}, "store": {"type": "string"},
            "study": {"type": "string"}, "replace": {"type": "boolean", "default": False},
        },
        "required": ["action"],
    },
})

TOOLS.append({
    "name": "askovo_semantic",
    "description": ("List, export or validate constrained semantic candidates. "
                    "Candidates stay unverified, carry exact record quotes and a critic pass; "
                    "accept/reject is human-only in the CLI, and MCP can export only an existing accepted review."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"enum": ["list", "export", "validate"]},
            "study_dir": {"type": "string"},
            "file": {"type": "string"},
            "candidate": {"type": "string"},
            "decision": {"enum": ["accept", "reject"]},
            "reviewer": {"type": "string"},
            "note": {"type": "string"},
            "store": {"type": "string"},
            "by": {"type": "string"},
            "product": {"type": "string"},
            "region": {"type": "string"},
            "export_now": {"type": "boolean", "default": False},
        },
        "required": ["action", "study_dir"],
    },
})

TOOLS.append({
    "name": "askovo_proof_export",
    "description": ("Export a read-only Prove Anything Proof Bundle from a study. "
                    "P1 checks the brief projection; independent semantic review and external adoption stay UNCHECKED."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "study_dir": {"type": "string"},
            "out": {"type": "string", "description": "new output directory; never overwritten"},
            "by": {"type": "string", "description": "named artifact reviewer"},
            "task": {"type": "string", "description": "optional decide task id"},
            "classification": {"enum": ["private", "synthetic", "public-redacted"], "default": "private"},
        },
        "required": ["study_dir", "out", "by"],
    },
})

TOOLS.append({
    "name": "askovo_primary_research",
    "description": ("Run local survey/landing/prototype/diary and participant-screening operations, including private eligibility invitations and explicit source-bound deployment. "
                    "No blocking serve or candidate accept/reject: public recruitment and named human evidence review stay outside MCP."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"enum": ["survey_create", "survey_status", "survey_export_candidates",
                                 "landing_create", "landing_status", "landing_export", "landing_deploy",
                                 "screening_export", "screening_invitations",
                                 "prototype_create", "prototype_import", "prototype_status", "prototype_export",
                                 "diary_create", "diary_import", "diary_status", "diary_export"]},
            "spec": {"type": "string", "description": "survey/landing/prototype/diary registration JSON"},
            "dir": {"type": "string", "description": "existing local experiment directory"},
            "design": {"type": "string", "description": "landing shared-export design JSON"},
            "adapter": {"type": "string", "description": "landing deployment adapter JSON"},
            "plan": {"type": "string", "description": "participant capture plan JSON"},
            "experiment_id": {"type": "string", "description": "screening invitations experiment id"},
            "file": {"type": "string", "description": "prototype/diary local observation JSON/JSONL"},
            "by": {"type": "string", "description": "prototype/diary observation importer"},
            "out": {"type": "string", "description": "new output path; never overwritten"},
            "at": {"type": "string", "description": "diary status: current ISO timestamp for due cells"},
        },
        "required": ["action"],
    },
})

TOOLS.append({
    "name": "askovo_research_watch",
    "description": ("Create, inspect, pause, resume or explicitly tick persistent decision-review watches. Execute reuses a separately authorized research run before review. "
                    "External cron/host scheduling is required. No daemon, automatic plan authorization, evidence promotion or decision mutation."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {"enum": ["create", "status", "run", "execute", "pause", "resume", "resolution"]},
            "study_dir": {"type": "string", "description": "existing local study directory"},
            "question": {"type": "string", "description": "create: research question to keep reviewing"},
            "interval_hours": {"type": "number", "description": "create: positive review interval"},
            "by": {"type": "string", "description": "create: named research owner"},
            "delta_file": {"type": "string", "description": "create: authorized local issue export for due syncs"},
            "delta_authorized_by": {"type": "string", "description": "create: named export/data-rights authorizer"},
            "watch_id": {"type": "string", "description": "run/execute/pause/resume/resolution: optional or required watch id"},
            "max_steps": {"type": "integer", "description": "execute: bounded authorized research steps, 1..20"},
            "due": {"type": "boolean", "description": "status: show only due active watches"},
        },
        "required": ["action", "study_dir"],
    },
})

TOOL_BUILDERS = {
    "askovo_route": (askovo_cli.sure_engine.cli_route, _build_route),
    "askovo_do": (askovo_cli.sure_engine.cli_do, _build_do),
    "askovo_platforms": (askovo_cli.sure_engine.cli_platforms, _build_platforms),
    "askovo_collect": (askovo_cli.command_collect, _build_collect),
    "askovo_research": (askovo_cli.command_research, _build_research),
    "askovo_research_loop": (askovo_cli.command_loop, _build_loop),
    "askovo_decide_start": (askovo_cli.command_decide, _build_decide_start),
    "askovo_decide_status": (askovo_cli.command_decide, _build_decide_task_id("status")),
    "askovo_decide_result": (askovo_cli.command_decide, _build_decide_task_id("result")),
    "askovo_analyze": (askovo_cli.sure_engine.cli_analyze, _build_analyze),
    "askovo_instruments": (askovo_cli.sure_engine.cli_instruments, _build_instruments),
    "askovo_codebook": (askovo_cli.sure_engine.cli_codebook, _build_codebook),
    "askovo_chain": (askovo_cli.sure_engine.cli_chain, _build_codebook),
    "askovo_deliver": (askovo_cli.command_deliver, _build_deliver),
    "askovo_proof_export": (askovo_cli.command_proof, _build_proof_export),
    "askovo_primary_research": (_command_primary_research, _build_primary_research),
    "askovo_research_watch": (askovo_cli.command_watch, _build_research_watch),
    "askovo_observation": (_command_observation, _build_observation),
    "askovo_semantic": (_command_semantic, _build_semantic),
    "askovo_methods": (askovo_cli.sure_engine.cli_methods, _build_methods),
    "askovo_domains": (askovo_cli.sure_engine.cli_domains, _build_domains),
    "askovo_queue_add": (askovo_cli.sure_engine.cli_queue_add, _build_queue_add),
    "askovo_queue_run": (askovo_cli.command_queue_run, _build_queue_run),
    "askovo_queue_status": (askovo_cli.sure_engine.cli_queue_status, _build_queue_status),
    "askovo_plan": (askovo_cli.command_plan, _build_plan),
    "askovo_init": (askovo_cli.command_init, _build_init),
    "askovo_check": (askovo_cli.command_check, _build_check),
    "askovo_audit": (askovo_cli.command_audit, _build_audit),
    "askovo_review": (askovo_cli.command_review, _build_review),
    "askovo_decision": (askovo_cli.command_decision, _build_decision),
    "askovo_signals": (askovo_cli.command_signals, _build_signals),
    "askovo_lexicon": (askovo_cli.command_lexicon, _build_lexicon),
    "askovo_report": (askovo_cli.command_report, _build_report),
    "askovo_connectors": (askovo_cli.command_connectors, _build_connectors),
    "askovo_stage": (askovo_cli.command_stage, _build_stage),
    "askovo_economics": (askovo_cli.sure_engine.cli_economics, _build_economics),
    "askovo_psm": (askovo_cli.sure_engine.cli_psm, _build_psm),
    "askovo_boundary": (askovo_cli.sure_engine.cli_boundary, _build_boundary),
    "askovo_cost": (askovo_cli.sure_engine.cli_cost, _build_cost),
    "askovo_roles": (askovo_cli.role_catalog.command_roles, _build_roles),
}


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "askovo_document":
        from askovo.documents import ingest_document
        result = ingest_document(
            _string(arguments.get("source"), "source"),
            _string(arguments.get("output"), "output"),
            overwrite=_boolean(arguments, "force"),
        )
        return {"exit_code": 0, "result": result}
    if name == "askovo_platform_map":
        return _tool_platform_map(arguments)
    entry = TOOL_BUILDERS.get(name)
    if entry is None:
        raise ValueError(f"unknown tool: {name}")
    command, builder = entry
    namespace = builder(arguments if isinstance(arguments, dict) else {})
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        exit_code = int(command(namespace))
    stdout_text = stdout_buffer.getvalue().strip()
    stderr_text = stderr_buffer.getvalue().strip()
    try:
        payload: Any = json.loads(stdout_text) if stdout_text else None
    except json.JSONDecodeError:
        payload = stdout_text
    result: dict[str, Any] = {"exit_code": exit_code, "result": payload}
    if stderr_text:
        result["stderr"] = stderr_text
    return result


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False)


def _jsonrpc_error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


def _handle_request(message: dict[str, Any]) -> str:
    method = str(message.get("method", ""))
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        requested = str(params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION))
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _jsonrpc_result(request_id, {})
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            payload = _run_tool(name, arguments)
        except ValueError as exc:
            return _jsonrpc_error(request_id, -32602, str(exc))
        except Exception as exc:  # unexpected tool failure stays a tool error, not a crash
            return _jsonrpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"tool error: {exc}"}],
                    "isError": True,
                },
            )
        is_error = payload.get("exit_code") == 2
        content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]
        # Preserve the 2.8.0 machine-readable first item while also returning a
        # readable projection for chat clients that do not render JSON bodies.
        tool_result = payload.get("result")
        readable = None
        if isinstance(tool_result, dict):
            summary = tool_result.get("chat_summary")
            if isinstance(summary, dict) and isinstance(summary.get("text"), str):
                readable = summary["text"]
            elif isinstance(tool_result.get("markdown"), str):
                readable = tool_result["markdown"]
        if readable:
            content.append({"type": "text", "text": readable})
        return _jsonrpc_result(
            request_id,
            {
                "content": content,
                "isError": is_error,
            },
        )
    if method == "resources/list" or method == "resources/templates/list":
        return _jsonrpc_result(request_id, {"resources": []})
    if method == "prompts/list":
        return _jsonrpc_result(request_id, {"prompts": []})
    if method.startswith("notifications/"):
        return ""
    if request_id is None:
        return ""
    return _jsonrpc_error(request_id, -32601, f"method not found: {method}")


def serve(stream_in: Any, stream_out: Any) -> int:
    for raw_line in stream_in:
        line = raw_line.strip() if isinstance(raw_line, str) else raw_line.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            stream_out.write(_jsonrpc_error(None, -32700, "parse error") + "\n")
            stream_out.flush()
            continue
        if not isinstance(message, dict):
            stream_out.write(_jsonrpc_error(None, -32600, "invalid request") + "\n")
            stream_out.flush()
            continue
        response = _handle_request(message)
        if response:
            stream_out.write(response + "\n")
            stream_out.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="askovo-mcp",
        description="Askovo product research MCP server (stdio, standard library only).",
    )
    parser.add_argument(
        "--tools", action="store_true", help="print the tool list as JSON and exit"
    )
    args = parser.parse_args(argv)
    if args.tools:
        print(json.dumps({"tools": TOOLS}, ensure_ascii=False, indent=2))
        return 0
    return serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

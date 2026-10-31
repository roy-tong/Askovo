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
    "collection and analysis only support weak nodes and inferences. "
    "(1) askovo_do scaffolds the study and product-reasoning.json; (2) askovo_chain renders the "
    "reasoning canvas; (3) askovo_platforms and askovo_collect gather permitted supporting "
    "material; (4) askovo_analyze describes it; (5) askovo_audit checks product/business "
    "rationales, evidence gates and per-claim verdicts; (6) askovo_deliver assembles chain-led "
    "memo, MRD, PRD, BRD, ops or tracker. Legacy text/platform planning remains available as "
    "askovo_plan; askovo_check remains the low-level gate command. "
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
        need=_string(arguments.get("need"), "need"),
        domain=_optional_string(arguments, "domain"),
        stage=_optional_string(arguments, "stage"),
        intent=_optional_string(arguments, "intent"),
        json=True,
    )


def _build_do(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        need=_string(arguments.get("need"), "need"),
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
        need=_string(arguments.get("need"), "need"),
        domain=_optional_string(arguments, "domain"),
        claim_type=_string_list(arguments, "claim_type"),
        bulk=_boolean(arguments, "bulk"),
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


def _build_analyze(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(
        study_dir=_string(arguments.get("study_dir"), "study_dir"),
        question=_optional_string(arguments, "question"),
    )


def _build_instruments(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_codebook(arguments: dict[str, Any]) -> argparse.Namespace:
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"))


def _build_deliver(arguments: dict[str, Any]) -> argparse.Namespace:
    kind = arguments.get("kind", "memo")
    if kind not in ("memo", "report", "mrd", "prd", "brd", "ops", "tracker", "signoff"):
        raise ValueError("kind must be memo, report, mrd, prd, brd, ops, tracker or signoff")
    return _namespace(study_dir=_string(arguments.get("study_dir"), "study_dir"), kind=kind)


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
                "sample_size": {"type": "integer", "minimum": 1},
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
                "need": {"type": "string"},
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
                "need": {"type": "string"},
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
                "need": {"type": "string"},
                "domain": {"enum": ["software", "hardware", "consumer", "automotive", "mobile"]},
                "claim_type": {"type": "array", "items": {"enum": ["need", "acceptance", "usability", "performance", "commercial", "safety"]}},
                "bulk": {"type": "boolean", "default": False},
            },
            "required": ["need"],
        },
    },
    {
        "name": "askovo_collect",
        "description": (
            "Run a supported collector (github/reddit) or a local fixture/export, with quota, "
            "run manifest and dedup. Defaults to dry-run. Blocked platforms return exit 3."
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
            },
            "required": ["study_dir", "platform", "query"],
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
        "name": "askovo_deliver",
        "description": "Assemble a chain-led decision memo, product report, MRD, PRD, BRD, user-operations projection or post-launch tracker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "kind": {"enum": ["memo", "report", "mrd", "prd", "brd", "ops", "tracker", "signoff"], "default": "memo"},
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
        "name": "askovo_platform_map",
        "description": (
            "Show how regions (cn/overseas/global) and platform types resolve to platforms and "
            "registry decisions. Read this before promising a user any platform coverage."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_BUILDERS = {
    "askovo_route": (askovo_cli.sure_engine.cli_route, _build_route),
    "askovo_do": (askovo_cli.sure_engine.cli_do, _build_do),
    "askovo_platforms": (askovo_cli.sure_engine.cli_platforms, _build_platforms),
    "askovo_collect": (askovo_cli.command_collect, _build_collect),
    "askovo_analyze": (askovo_cli.sure_engine.cli_analyze, _build_analyze),
    "askovo_instruments": (askovo_cli.sure_engine.cli_instruments, _build_instruments),
    "askovo_codebook": (askovo_cli.sure_engine.cli_codebook, _build_codebook),
    "askovo_chain": (askovo_cli.sure_engine.cli_chain, _build_codebook),
    "askovo_deliver": (askovo_cli.sure_engine.cli_deliver, _build_deliver),
    "askovo_methods": (askovo_cli.sure_engine.cli_methods, _build_methods),
    "askovo_domains": (askovo_cli.sure_engine.cli_domains, _build_domains),
    "askovo_queue_add": (askovo_cli.sure_engine.cli_queue_add, _build_queue_add),
    "askovo_queue_run": (askovo_cli.command_queue_run, _build_queue_run),
    "askovo_queue_status": (askovo_cli.sure_engine.cli_queue_status, _build_queue_status),
    "askovo_plan": (askovo_cli.command_plan, _build_plan),
    "askovo_init": (askovo_cli.command_init, _build_init),
    "askovo_check": (askovo_cli.command_check, _build_check),
    "askovo_audit": (askovo_cli.command_audit, _build_audit),
    "askovo_signals": (askovo_cli.command_signals, _build_signals),
    "askovo_lexicon": (askovo_cli.command_lexicon, _build_lexicon),
    "askovo_report": (askovo_cli.command_report, _build_report),
    "askovo_connectors": (askovo_cli.command_connectors, _build_connectors),
    "askovo_stage": (askovo_cli.command_stage, _build_stage),
    "askovo_economics": (askovo_cli.sure_engine.cli_economics, _build_economics),
    "askovo_psm": (askovo_cli.sure_engine.cli_psm, _build_psm),
    "askovo_boundary": (askovo_cli.sure_engine.cli_boundary, _build_boundary),
    "askovo_cost": (askovo_cli.sure_engine.cli_cost, _build_cost),
}


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
        return _jsonrpc_result(
            request_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
                ],
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

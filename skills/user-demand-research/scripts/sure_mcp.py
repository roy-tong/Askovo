#!/usr/bin/env python3
"""SURE MCP server: expose the deterministic CLI surface as MCP tools over stdio.

This server speaks the Model Context Protocol stdio transport (newline-delimited
JSON-RPC 2.0) using only the Python standard library. It wraps the same command
functions used by sure.py, so the Skill, the CLI, and MCP share one behavior.
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
SURE_PATH = HERE / "sure.py"

_spec = importlib.util.spec_from_file_location("sure", SURE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load sure.py beside this server: {SURE_PATH}")
sure = importlib.util.module_from_spec(_spec)
sys.modules["sure"] = sure
_spec.loader.exec_module(sure)

SERVER_NAME = "user-demand-research"
SERVER_VERSION = sure.SURE_VERSION
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_INSTRUCTIONS = (
    "SURE user-demand research, deterministic surface. Workflow: "
    "(1) sure_plan with the user's goal, region (cn|overseas|global), sample size, and "
    "platform types — it resolves platforms against the connector registry, allocates "
    "quotas, and writes feasibility plus collection tasks; "
    "(2) complete the design contract (decision, hypotheses, falsifiers, adapter review "
    "fields) and pass sure_check stage=design before collecting; "
    "(3) collect only with registry-supported connectors, writing a run manifest per "
    "collection; (4) sure_signals computes deterministic corpus signals; "
    "(5) sure_report assembles the research-status report. "
    "Start with sure_audit when the user already has a study or corpus: it returns gates, "
    "signals, and per-claim verdicts. Tool results embed exit codes: 1 = failed gate, 3 = no feasible platform — both are "
    "research statuses to report, never reasons to retry or to substitute a commercial "
    "provider, merchant API, saved login, internal endpoint, or browser automation. "
    "Evidence is graded E0-E5; a validated demand judgment needs linked problem, solution, "
    "commercial/behavioral, and counter-evidence chains for the same role, scene, and task. "
    "Records are not users; convenience samples do not support prevalence or market-size "
    "claims. For judgment rules read the Skill, not just these tools."
)
PLATFORMS = ("reddit", "x", "youtube", "amazon", "jd", "taobao", "kickstarter")
STAGES = sure.STAGES

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
    if mode not in sure.PLAN_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sure.PLAN_MODES)}")
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
        write_report=bool(arguments.get("write_report", False)),
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
    return _namespace(platform=platform, include_blocked=bool(arguments.get("include_blocked", False)))


def _tool_platform_map(arguments: dict[str, Any]) -> dict[str, Any]:
    platform_map = sure._load_platform_map()
    registry = sure._connector_index()
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
        "name": "sure_plan",
        "description": (
            "Turn a research goal, region, sample size, and platform types into a SURE study "
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
        "name": "sure_init",
        "description": (
            "Create a SURE study workspace from the bundled template with selected platform "
            "route files. Use sure_plan instead when the region and platform types are the input."
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
        "name": "sure_check",
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
        "name": "sure_audit",
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
        "name": "sure_signals",
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
        "name": "sure_lexicon",
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
        "name": "sure_report",
        "description": (
            "Assemble the Chinese research-status report into 06-report/report.md from the study "
            "contract, source plan, manifests, signals, judgments, and blocked routes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "study_dir": {"type": "string"},
                "output": {"type": "string", "description": "report path; defaults to 06-report/report.md"},
            },
            "required": ["study_dir"],
        },
    },
    {
        "name": "sure_connectors",
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
        "name": "sure_platform_map",
        "description": (
            "Show how regions (cn/overseas/global) and platform types resolve to platforms and "
            "registry decisions. Read this before promising a user any platform coverage."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_BUILDERS = {
    "sure_plan": (sure.command_plan, _build_plan),
    "sure_init": (sure.command_init, _build_init),
    "sure_check": (sure.command_check, _build_check),
    "sure_audit": (sure.command_audit, _build_audit),
    "sure_signals": (sure.command_signals, _build_signals),
    "sure_lexicon": (sure.command_lexicon, _build_lexicon),
    "sure_report": (sure.command_report, _build_report),
    "sure_connectors": (sure.command_connectors, _build_connectors),
}


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "sure_platform_map":
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
        prog="sure-mcp",
        description="SURE user-demand research MCP server (stdio, standard library only).",
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

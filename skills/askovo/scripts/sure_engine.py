"""SURE research engine — the underlying logic behind askovo.

SURE = Structured User Research with Evidence. It owns domain/stage detection,
method selection, evidence rules, claim boundaries and safety gates. askovo is
the product surface (CLI/Skill/MCP) and calls this engine; do not install or
invoke the engine separately.

Standard library only. Python 3.9+.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import os
import socket
import struct
import json
import math
import re
import shlex
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
ASSETS = SKILL_ROOT / "assets"
CATALOG_PATH = ASSETS / "method-catalog.json"
PACKS_DIR = ASSETS / "domain-packs"

STAGES = (
    "discovery",
    "concept",
    "prototype",
    "validation",
    "pricing",
    "prelaunch",
    "postlaunch",
    "audit",
)
INTENTS = ("route", "plan", "instruments", "import", "sources", "collect", "analyze", "audit", "deliver")
CLAIM_TYPES = ("need", "acceptance", "usability", "performance", "commercial", "safety")
DELIVERY_AUDIENCES = (
    "product_manager",
    "user_researcher",
    "user_operations",
    "market_researcher",
    "market_analyst",
    "requirements_analyst",
    "business_analyst",
)
LEGACY_REASONING_NODES = ("scene", "user", "pain", "need", "feature", "product")
REASONING_NODES = (*LEGACY_REASONING_NODES, "business")
REASONING_NODE_LABELS = {
    "scene": "场景",
    "user": "用户",
    "pain": "痛点",
    "need": "需求",
    "feature": "特性",
    "product": "产品",
    "business": "商业",
}
REASONING_STAGE_FOCUS = {
    "discovery": ("scene", "user", "pain", "need"),
    "concept": ("need", "feature"),
    "prototype": ("feature", "product"),
    "validation": ("feature", "product"),
    "pricing": ("product", "business"),
    "prelaunch": ("product", "business"),
    "postlaunch": REASONING_NODES,
    "audit": REASONING_NODES,
}
HIGH_RISK_FLAGS = {
    "road_test",
    "food_ingest",
    "skin_contact",
    "minors",
    "sensitive_data",
    "destructive_test",
    "production_logs",
    "home_recording",
    "bystander_recording",
    "electrical_thermal",
}


def _read_version() -> str:
    for candidate in (
        Path(__file__).resolve().parents[3] / "VERSION",
        Path(__file__).resolve().parents[2] / "VERSION",
        Path(__file__).resolve().parents[1] / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "dev"


VERSION = _read_version()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def connector_review_expired(connector: dict[str, Any], today: Any = None) -> bool:
    watch = connector.get("policy_watch")
    if not isinstance(watch, dict) or not watch.get("recheck_by"):
        return False
    try:
        deadline = datetime.strptime(str(watch["recheck_by"]), "%Y-%m-%d").date()
    except ValueError:
        return True
    current = today or datetime.now(timezone.utc).date()
    return current > deadline


def platform_review_expired(platform: str) -> bool:
    registry = load_json(ASSETS / "open-source-connectors.json")
    connectors = registry.get("connectors", []) if isinstance(registry, dict) else []
    return any(
        isinstance(item, dict)
        and item.get("platform") == platform
        and item.get("decision") in {"supported", "historical_only"}
        and connector_review_expired(item)
        for item in connectors
    )


def method_catalog() -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("methods"), list):
        raise ValueError(f"invalid method catalog: {CATALOG_PATH}")
    return catalog


def methods() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in method_catalog()["methods"]:
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError(f"invalid method entry in {CATALOG_PATH}")
        result[str(item["id"])] = item
    return result


def domain_packs() -> dict[str, dict[str, Any]]:
    packs: dict[str, dict[str, Any]] = {}
    for path in sorted(PACKS_DIR.glob("*.json")):
        pack = load_json(path)
        if not isinstance(pack, dict) or not pack.get("domain"):
            raise ValueError(f"invalid domain pack: {path}")
        packs[str(pack["domain"])] = pack
    return packs


def load_pack(domain: str) -> dict[str, Any]:
    packs = domain_packs()
    if domain not in packs:
        raise ValueError(f"unknown domain {domain!r}; choose from: {', '.join(sorted(packs))}")
    return packs[domain]


def _keyword_score(text: str, keywords: Iterable[str]) -> int:
    low = text.casefold()
    score = 0
    for keyword in keywords:
        key = str(keyword).casefold()
        if key and key in low:
            score += 2 if len(key) >= 4 else 1
    return score


def detect_domain(text: str, explicit: str | None = None) -> dict[str, Any]:
    packs = domain_packs()
    if explicit:
        if explicit not in packs:
            raise ValueError(f"unknown domain {explicit!r}")
        return {
            "domain": explicit,
            "label": packs[explicit]["label"],
            "confidence": 1.0,
            "scores": {explicit: 1.0},
            "needs_domain": False,
        }
    scores = {name: _keyword_score(text, pack.get("keywords", [])) for name, pack in packs.items()}
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, best_score = ranked[0]
    total = sum(scores.values())
    if best_score == 0:
        return {
            "domain": None,
            "label": None,
            "confidence": 0.0,
            "scores": scores,
            "needs_domain": True,
            "options": [{"domain": name, "label": packs[name]["label"]} for name in sorted(packs)],
        }
    confidence = round(min(0.98, 0.45 + best_score / max(total, 1) * 0.5), 2)
    alternatives = [
        {"domain": name, "label": packs[name]["label"], "score": score}
        for name, score in ranked[1:]
        if score > 0
    ]
    return {
        "domain": best,
        "label": packs[best]["label"],
        "confidence": confidence,
        "scores": scores,
        "alternatives": alternatives,
        "needs_domain": False,
    }


STAGE_HINTS = (
    ("audit", ("审计", "评估报告", "证据够不够", "能不能支持", "看看这份", "review")),
    ("pricing", ("定价", "价格", "付费", "收费", "多少钱", "willingness to pay", "price")),
    ("postlaunch", ("上市后", "复购", "留存", "流失", "退货", "售后", "维修", "rma", "churn")),
    ("discovery", ("值不值得", "要不要做", "是否值得", "该不该做", "需求是什么", "机会在哪")),
    ("validation", ("验证", "测试", "试验", "beta", "试点", "发布门槛", "soak", "pilot")),
    ("prototype", ("原型", "样机", "可用性", "任务", "安装", "握持", "佩戴", "交互", "prototype")),
    ("concept", ("概念", "包装", "外观", "方案", "卖点", "配置", "concept")),
    ("discovery", ("发现", "需求", "值不值得", "机会", "访谈", "场景", "用户是谁", "discovery")),
)


def detect_stage(text: str, explicit: str | None = None) -> dict[str, Any]:
    if explicit:
        if explicit not in STAGES:
            raise ValueError(f"unknown stage {explicit!r}; choose from: {', '.join(STAGES)}")
        return {"stage": explicit, "confidence": 1.0, "source": "explicit"}
    low = text.casefold()
    for stage, keywords in STAGE_HINTS:
        hits = [keyword for keyword in keywords if keyword in low]
        if hits:
            return {"stage": stage, "confidence": min(0.95, 0.55 + 0.1 * len(hits)), "source": "keywords", "hits": hits}
    return {"stage": "discovery", "confidence": 0.3, "source": "default"}


def detect_intent(text: str, explicit: str | None = None) -> dict[str, Any]:
    if explicit:
        if explicit not in INTENTS:
            raise ValueError(f"unknown intent {explicit!r}; choose from: {', '.join(INTENTS)}")
        return {"intent": explicit, "source": "explicit"}
    low = text.casefold()
    rules = (
        ("audit", ("审计", "评估", "能不能支持", "证据够不够", "复核", "review")),
        ("deliver", ("memo", "报告", "prd", "交付物", "决策纪要", "写一份")),
        ("instruments", ("提纲", "问卷", "协议", "招募", "脚本", "consent")),
        ("sources", ("哪些平台", "在哪里找", "哪里有数据", "数据源", "平台有数据", "在哪找数据")),
        ("collect", ("爬取", "抓取", "采集", "批量获取", "大量数据", "collect", "scrape")),
        ("analyze", ("分析", "归纳", "聚类", "主题", "洞察", "整合", "analyze")),
        ("plan", ("计划", "怎么研究", "研究设计", "方案", "路线", "怎么验证")),
    )
    for intent, keywords in rules:
        if any(keyword in low for keyword in keywords):
            return {"intent": intent, "source": "keywords"}
    return {"intent": "route", "source": "default"}


RISK_RULES = (
    ("road_test", ("开放道路", "实车路测", "上路测试", "道路试验", "on-road", "road test", "road-test", "public road")),
    ("food_ingest", ("试吃", "试喝", "摄入", "食用测试", "吃下去", "food ingestion", "ingest", "taste test", "eating", "drinking")),
    ("skin_contact", ("皮肤接触", "涂抹", "上脸", "斑贴", "skin contact", "skin-contact", "topical", "patch test", "on-skin")),
    ("minors", ("儿童", "未成年", "小学生", "幼儿", "children", "child", "minor", "underage", "pediatric")),
    ("sensitive_data", ("健康数据", "生物特征", "位置轨迹", "家庭影像", "医疗记录", "health data", "biometric", "location history", "medical record")),
    ("destructive_test", ("跌落测试", "破坏性", "拆解测试", "针刺", "drop test", "destructive test", "teardown", "nail penetration")),
    ("production_logs", ("生产日志", "全量日志", "用户遥测", "生产环境数据", "production logs", "production data", "user telemetry")),
    ("home_recording", ("入户录像", "家庭录像", "家中拍摄", "home recording", "in-home video", "household recording")),
    ("bystander_recording", ("路人拍摄", "旁观者录像", "公共场所录像", "bystander recording", "public recording")),
    ("electrical_thermal", ("电池测试", "高温测试", "充电异常", "市电测试", "热失控", "battery test", "thermal runaway", "mains voltage", "high temperature test")),
)


def detect_risks(text: str) -> list[dict[str, str]]:
    low = text.casefold()
    found: list[dict[str, str]] = []
    for flag, keywords in RISK_RULES:
        hits = [keyword for keyword in keywords if keyword in low]
        if hits:
            found.append({"flag": flag, "hits": hits})
    return found


def _method_view(method: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": method["id"],
        "name": method["name"],
        "answers": method["answers"],
        "evidence_forms": method["evidence_forms"],
        "supports": method["supports"],
        "does_not_support": method["does_not_support"],
        "misreads": method["common_misreads"],
        "risk_flags": method.get("risk_flags", []),
        "source": method.get("source", ""),
    }


def product_reasoning_contract(stage: str) -> dict[str, Any]:
    """Declare the product-facing spine; methods and sources only support it."""
    return {
        "flow": list(REASONING_NODES),
        "flow_label": "场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业",
        "focus": list(REASONING_STAGE_FOCUS.get(stage, REASONING_NODES)),
        "primary_artifact": "04-findings/product-reasoning.json",
        "principle": "先显式写出每个节点及推导理由，再针对薄弱节点收集和分析证据。",
    }


def route_request(
    text: str,
    domain: str | None = None,
    stage: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    domain_info = detect_domain(text, domain)
    stage_info = detect_stage(text, stage)
    intent_info = detect_intent(text, intent)
    risks = detect_risks(text)
    if domain_info["needs_domain"]:
        return {
            "query": text,
            "status": "needs_domain",
            "domain": None,
            "domain_label": None,
            "confidence": 0.0,
            "domain_scores": domain_info.get("scores", {}),
            "domain_options": domain_info.get("options", []),
            "stage": stage_info["stage"],
            "intent": intent_info["intent"],
            "risk_flags": risks,
            "safety_gate": "review" if risks else "clear",
            "product_reasoning": product_reasoning_contract(stage_info["stage"]),
            "questions": ["你要研究的是软件、硬件、消费品、汽车还是手机/可穿戴产品？"],
            "next_commands": ['askovo route "<需求>" --domain software'],
        }

    pack = load_pack(str(domain_info["domain"]))
    stage_key = stage_info["stage"]
    stage_data = pack["stages"].get(stage_key) or pack["stages"][pack["default_stage"]]
    catalog = methods()
    selected = []
    for method_id in stage_data.get("methods", []):
        method = catalog.get(method_id)
        if method:
            selected.append(_method_view(method))
    selected_ids = {item["id"] for item in selected}
    alternatives: dict[str, dict[str, Any]] = {}
    for item in selected:
        method = catalog.get(item["id"], {})
        for alt_id in method.get("alternatives", []):
            alt = catalog.get(alt_id)
            if alt and alt_id not in selected_ids:
                alternatives[alt_id] = {
                    "id": alt_id,
                    "name": alt["name"],
                    "why_not": "当前阶段不是首选；当证据形式/约束不匹配时替代",
                }
    requires_ack = bool(risks)
    next_commands = []
    slug = f"./askovo-{domain_info['domain']}-{stage_key}"
    intent_name = intent_info["intent"]
    if intent_name == "audit":
        next_commands.append("askovo audit <study>")
    elif intent_name == "sources":
        next_commands.append(shlex.join(["askovo", "platforms", text, "--domain", domain_info["domain"], "--bulk"]))
    elif intent_name == "collect":
        next_commands.append(shlex.join(["askovo", "platforms", text, "--domain", domain_info["domain"], "--bulk"]))
        next_commands.append('askovo collect <study> --platform github --query "<query>" --limit 100')
    elif intent_name == "analyze":
        next_commands.append('askovo analyze <study> --question "<研究问题>"')
    else:
        next_commands.append(shlex.join([
            "askovo", "do", text, "--domain", domain_info["domain"],
            "--stage", stage_key, "--study", slug,
        ]))
    if requires_ack:
        next_commands.append("若确需执行，请由负责人完成安全/伦理审查后追加 --ack-risk")
    return {
        "query": text,
        "status": "routed",
        "domain": domain_info["domain"],
        "domain_label": domain_info["label"],
        "confidence": domain_info["confidence"],
        "domain_scores": domain_info["scores"],
        "domain_alternatives": domain_info.get("alternatives", []),
        "stage": stage_key,
        "stage_label": stage_data["label"],
        "stage_confidence": stage_info["confidence"],
        "intent": intent_info["intent"],
        "intent_source": intent_info["source"],
        "product_reasoning": product_reasoning_contract(stage_key),
        "risk_flags": risks,
        "safety_gate": "review" if requires_ack else "clear",
        "risk_notes": pack.get("risk_notes", []),
        "recommended_methods": selected,
        "alternatives": list(alternatives.values()),
        "decisions": stage_data.get("decisions", []),
        "deliverables": stage_data.get("deliverables", []),
        "questions": stage_data.get("decisions", []),
        "claim_boundaries": pack.get("claim_boundaries", []),
        "next_commands": next_commands,
        "catalog_version": method_catalog().get("schema_version", "1.0"),
        "platform_preview": platform_fit(
            text, str(domain_info["domain"]), intent_name == "collect"
        )["recommended"][:5],
    }


def _risk_markdown(risks: list[dict[str, str]]) -> str:
    if not risks:
        return "- 未检测到高风险标记。\n"
    lines = ["| 风险标记 | 命中词 | 进入执行前必须 |", "|---|---|---|"]
    for item in risks:
        lines.append(f"| `{item['flag']}` | {', '.join(item['hits'])} | 完成安全/伦理审查并记录批准人 |")
    return "\n".join(lines) + "\n"


def route_markdown(route: dict[str, Any]) -> str:
    if route.get("status") == "needs_domain":
        return "# Askovo 路由\n\n需要先确认产品类型：\n\n" + "\n".join(
            f"- `{item['domain']}` — {item['label']}" for item in route["domain_options"]
        ) + "\n"
    lines = [
        "# Askovo 路由结果",
        "",
        f"- 原始需求：{route['query']}",
        f"- 产品类型：**{route['domain_label']}**（`{route['domain']}`，置信度 {route['confidence']}）",
        f"- 阶段：**{route['stage_label']}**（`{route['stage']}`）",
        f"- 意图：`{route['intent']}`",
        f"- 安全门：`{route['safety_gate']}`",
        "",
        "## 产品推理主链",
        "",
        f"{route['product_reasoning']['flow_label']}",
        "",
        f"本阶段重点：{' → '.join(route['product_reasoning']['focus'])}。先写出节点、推导理由与假设，再选择补证方法。",
        "",
        "## 支撑方法",
        "",
        "| 方法 | 回答什么 | 证据形式 | 不能证明 |",
        "|---|---|---|---|",
    ]
    for item in route["recommended_methods"]:
        lines.append(
            f"| {item['name']} | {'；'.join(item['answers'])} | "
            f"{', '.join(item['evidence_forms'])} | {', '.join(item['does_not_support'])} |"
        )
    lines.extend(["", "## 本阶段要回答", ""])
    lines.extend(f"- {item}" for item in route.get("decisions", []))
    lines.extend(["", "## 风险", "", _risk_markdown(route.get("risk_flags", []))])
    lines.extend(["## 下一步", ""])
    lines.extend(f"- `{item}`" for item in route.get("next_commands", []))
    return "\n".join(lines) + "\n"


def _slug(text: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_part:
        return ascii_part[:40]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"study-{stamp}"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def product_reasoning_template(title: str = "") -> dict[str, Any]:
    """Create a hypothesis-first canvas; it never invents semantic product claims."""
    nodes: dict[str, Any] = {}
    previous = ""
    for node in REASONING_NODES:
        rationale = "待填写：这个场景为什么值得进入当前产品决策"
        if previous:
            rationale = f"待填写：为什么由{REASONING_NODE_LABELS[previous]}推出{REASONING_NODE_LABELS[node]}"
        nodes[node] = {
            "statement": "待填写",
            "rationale": rationale,
            "status": "hypothesis",
            "evidence_ids": [],
            "assumptions": [],
        }
        previous = node
    nodes["scene"].update({"trigger": "待填写", "environment": "待填写", "task_context": "待填写"})
    nodes["user"].update({"role": "待填写", "state": "待填写", "decision_role": "待填写"})
    nodes["pain"].update({"current_substitute": "待填写", "friction_cost": "待填写", "consequence": "待填写"})
    nodes["need"].update({"desired_outcome": "待填写", "constraints": [], "measure": "待填写"})
    nodes["feature"].update({"capability": "待填写", "acceptance_conditions": [], "alternatives_considered": []})
    nodes["product"].update({"form": "待填写", "scope": "待填写", "non_goals": [], "acceptance_criteria": []})
    nodes["business"].update(
        {
            "market_definition": "待填写",
            "geographies": [],
            "time_window": "待填写",
            "included_markets": [],
            "excluded_markets": [],
            "target_segment": "待填写",
            "segments": [],
            "payer": "待填写",
            "positioning": "待填写",
            "revenue_model": "待填写",
            "pricing_hypothesis": "待填写",
            "pricing": [],
            "channels": [],
            "competitive_alternatives": [],
            "cost_drivers": [],
            "market_estimates": [],
            "unit_economics_inputs": [],
            "success_metrics": [],
            "non_goals": [],
            "gate": {
                "stage": "G0",
                "decision": "hypothesis",
                "owner": "待填写",
                "resource_commitment": "待填写",
                "revisit_trigger": "待填写",
            },
        }
    )
    return {
        "schema_version": "2.0",
        "flow": list(REASONING_NODES),
        "chains": [
            {
                "id": "PR01",
                "title": title or "待填写",
                "context_key": "",
                "demand_judgment_id": "",
                "status": "hypothesis",
                "confidence": "low",
                "supporting_states": {
                    "delivery": {"status": "unplanned", "release_plan_ref": ""},
                    "outcome": {"status": "unmeasured", "metric_refs": []},
                    "causal": {"status": "not-claimed", "experiment_refs": []},
                },
                "nodes": nodes,
                "alternative_explanations": [],
                "counter_evidence_ids": [],
                "human_review": {"status": "pending", "reviewer": "", "notes": "", "risk_acceptance": ""},
                "prioritization": {"method": "", "factors": {}, "owner": "", "decided_at": "", "rationale": ""},
                "change_log": [],
                "gaps": ["待填写：当前最薄弱的推理节点或推导关系"],
                "next_test": "待填写：能最大幅度降低当前推理不确定性的最小验证",
            }
        ],
    }


def scaffold_product_reasoning(study_dir: Path) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    path = study_dir / "04-findings" / "product-reasoning.json"
    if path.exists():
        return {"status": "exists", "path": str(path)}
    title = ""
    study_path = study_dir / "study.json"
    if study_path.is_file():
        study = load_json(study_path)
        if isinstance(study, dict):
            title = str(study.get("title") or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(product_reasoning_template(title), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"status": "created", "path": str(path)}


def load_product_reasoning(study_dir: Path) -> dict[str, Any] | None:
    path = study_dir / "04-findings" / "product-reasoning.json"
    if not path.is_file():
        return None
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError("product-reasoning.json must contain an object")
    return value


def product_reasoning_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    chains = data.get("chains", []) if isinstance(data, dict) else []
    if not isinstance(chains, list):
        chains = []
    by_status: dict[str, int] = {}
    supporting_summary: dict[str, dict[str, int]] = {
        "delivery": {}, "outcome": {}, "causal": {}
    }
    node_summary = {
        node: {"total": 0, "validated": 0, "with_evidence": 0}
        for node in REASONING_NODES
    }
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        status = str(chain.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        states = chain.get("supporting_states", {})
        if isinstance(states, dict):
            for state_name in supporting_summary:
                state_value = states.get(state_name, {})
                if isinstance(state_value, dict) and state_value.get("status"):
                    state_status = str(state_value["status"])
                    supporting_summary[state_name][state_status] = supporting_summary[state_name].get(state_status, 0) + 1
        nodes = chain.get("nodes", {})
        if not isinstance(nodes, dict):
            continue
        for node in REASONING_NODES:
            value = nodes.get(node, {})
            if not isinstance(value, dict):
                continue
            node_summary[node]["total"] += 1
            if value.get("status") == "validated":
                node_summary[node]["validated"] += 1
            if value.get("evidence_ids"):
                node_summary[node]["with_evidence"] += 1
    return {
        "chains": len(chains),
        "decided": by_status.get("decided", 0),
        "by_status": by_status,
        "supporting_states": supporting_summary,
        "nodes": node_summary,
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _business_detail_lines(chain: dict[str, Any]) -> list[str]:
    nodes = chain.get("nodes", {})
    business = nodes.get("business", {}) if isinstance(nodes, dict) else {}
    if not isinstance(business, dict) or not business:
        return []
    lines: list[str] = []
    for field, label in (
        ("market_definition", "市场定义"),
        ("target_segment", "目标细分"),
        ("payer", "付费者"),
        ("positioning", "竞争定位"),
        ("revenue_model", "收入模式"),
        ("pricing_hypothesis", "价格假设"),
    ):
        if business.get(field):
            lines.append(f"- {label}：{business[field]}")
    for field, label in (
        ("channels", "进入渠道"),
        ("competitive_alternatives", "竞争与替代"),
        ("cost_drivers", "成本驱动"),
        ("market_estimates", "市场估计口径"),
        ("unit_economics_inputs", "单位经济输入"),
        ("success_metrics", "商业成功指标"),
        ("non_goals", "商业非目标"),
    ):
        value = business.get(field, [])
        if value:
            lines.append(f"- {label}：{json.dumps(value, ensure_ascii=False)}")
    gate = business.get("gate", {})
    if isinstance(gate, dict) and gate:
        lines.append(
            f"- 商业门：`{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}`；"
            f"负责人：{gate.get('owner') or '待确认'}；资源承诺：{gate.get('resource_commitment') or '待确认'}；"
            f"复审触发：{gate.get('revisit_trigger') or '待确认'}"
        )
    return lines


def _product_chain_lines(data: dict[str, Any]) -> list[str]:
    flow_value = data.get("flow")
    flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
    flow_label = " → ".join(REASONING_NODE_LABELS[node] for node in flow)
    lines = [
        f"> 主链：{flow_label}。证据支撑推理，不替代推理。",
        "",
    ]
    chains = data.get("chains", [])
    if not isinstance(chains, list) or not chains:
        lines.append("尚无产品推理链。")
        return lines
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        states = chain.get("supporting_states", {})
        state_labels = []
        if isinstance(states, dict):
            for key, label in (("delivery", "交付"), ("outcome", "结果"), ("causal", "因果")):
                value = states.get(key, {})
                if isinstance(value, dict) and value.get("status"):
                    state_labels.append(f"{label} `{value['status']}`")
        lines.extend(
            [
                f"### {chain.get('id', 'PR?')} · {chain.get('title', '未命名推理链')}",
                "",
                f"- 状态：`{chain.get('status', 'unknown')}`；置信度：`{chain.get('confidence', 'unknown')}`",
                f"- 独立支撑状态：{'；'.join(state_labels) if state_labels else '未记录'}",
                f"- 需求判断：`{chain.get('demand_judgment_id') or '未关联'}`；上下文：`{chain.get('context_key') or '未设置'}`",
                "",
                "| 节点 | 判断 | 为什么到这一步 | 状态 | 证据 |",
                "|---|---|---|---|---|",
            ]
        )
        nodes = chain.get("nodes", {})
        for node in flow:
            value = nodes.get(node, {}) if isinstance(nodes, dict) else {}
            if not isinstance(value, dict):
                value = {}
            evidence = ", ".join(f"`{item}`" for item in value.get("evidence_ids", []))
            lines.append(
                f"| **{REASONING_NODE_LABELS[node]}** | {_markdown_cell(value.get('statement'))} | "
                f"{_markdown_cell(value.get('rationale'))} | `{value.get('status', 'unknown')}` | "
                f"{_markdown_cell(evidence)} |"
            )
        for node in flow:
            value = nodes.get(node, {}) if isinstance(nodes, dict) else {}
            if not isinstance(value, dict):
                continue
            assumptions = value.get("assumptions", [])
            if assumptions:
                lines.append(f"- {REASONING_NODE_LABELS[node]}假设：{'；'.join(str(item) for item in assumptions)}")
        product = nodes.get("product", {}) if isinstance(nodes, dict) else {}
        if isinstance(product, dict):
            non_goals = product.get("non_goals", [])
            acceptance = product.get("acceptance_criteria", [])
            if non_goals:
                lines.append(f"- 产品非目标：{'；'.join(str(item) for item in non_goals)}")
            if acceptance:
                lines.append(f"- 产品验收：{'；'.join(str(item) for item in acceptance)}")
        lines.extend(_business_detail_lines(chain))
        counter = chain.get("counter_evidence_ids", [])
        alternatives = chain.get("alternative_explanations", [])
        review = chain.get("human_review", {})
        gaps = chain.get("gaps", [])
        lines.append(f"- 替代解释：{'；'.join(str(item) for item in alternatives) if alternatives else '未记录'}")
        lines.append(f"- 反证：{', '.join(f'`{item}`' for item in counter) if counter else '未记录'}")
        if isinstance(review, dict) and review:
            lines.append(f"- 人工复核：`{review.get('status', 'pending')}`；{review.get('notes') or '尚无复核说明'}")
            if review.get("risk_acceptance"):
                lines.append(f"- 风险接受：{review['risk_acceptance']}")
        prioritization = chain.get("prioritization", {})
        if isinstance(prioritization, dict) and any(prioritization.values()):
            lines.append(
                f"- 优先级：方法 {prioritization.get('method') or '待确认'}；负责人 {prioritization.get('owner') or '待确认'}；"
                f"理由 {prioritization.get('rationale') or '待确认'}；因素 "
                f"{json.dumps(prioritization.get('factors', {}), ensure_ascii=False)}"
            )
        change_log = chain.get("change_log", [])
        if isinstance(change_log, list) and change_log:
            latest = change_log[-1] if isinstance(change_log[-1], dict) else {}
            lines.append(
                f"- 变更：{len(change_log)} 条；最近 {latest.get('id', '未编号')} "
                f"{latest.get('base_version', '?')}→{latest.get('new_version', '?')}；"
                f"投影同步 `{latest.get('projection_sync', 'pending')}`"
            )
        lines.append(f"- 缺口：{'；'.join(str(item) for item in gaps) if gaps else '未记录'}")
        lines.append(f"- 下一验证：{chain.get('next_test') or '未记录'}")
        lines.append("")
    return lines


def product_reasoning_markdown(data: dict[str, Any], title: str = "产品推理链") -> str:
    return "\n".join([f"# {title}", ""] + _product_chain_lines(data)) + "\n"


def _write_route(study_dir: Path, route: dict[str, Any]) -> None:
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "route.json").write_text(
        json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (study_dir / "route.md").write_text(route_markdown(route), encoding="utf-8")


def create_study(
    study_dir: Path,
    route: dict[str, Any],
    force: bool = False,
    acknowledge: bool = False,
) -> dict[str, Any]:
    if study_dir.exists() and not force:
        blocking = [
            item for item in study_dir.iterdir()
            if item.name not in {"route.json", "route.md"}
        ]
        if blocking:
            raise ValueError(f"refusing to overwrite non-empty directory: {study_dir}")
    study_dir.mkdir(parents=True, exist_ok=True)
    pack = load_pack(route["domain"])
    selected = route["recommended_methods"]
    study_id = _slug(route["query"])
    method_ids = [item["id"] for item in selected]
    study = {
        "study_id": study_id,
        "title": route["query"][:120],
        "method_version": VERSION,
        "product_domain": route["domain"],
        "lifecycle_stage": route["stage"],
        "product_reasoning_version": "2.0",
        "product_reasoning": product_reasoning_contract(route["stage"]),
        "delivery": {"audiences": list(DELIVERY_AUDIENCES)},
        "decision": {
            "question": route["query"],
            "owner": "待确认",
            "deadline": "待确认",
            "options": [],
            "minimum_evidence": [],
        },
        "scope": {
            "target_users": [],
            "markets": [],
            "languages": [],
            "source_time_window": {"start": "待确认", "end": "待确认"},
            "unit_of_observation": "feedback_record",
            "allowed_sources": [],
            "prohibited_inferences": [
                "Do not infer population prevalence from convenience samples",
                "Do not treat records as unique people without lawful identity resolution",
                "Do not substitute usability, performance, or safety evidence for demand evidence",
            ],
        },
        "hypotheses": [{"id": "H1", "statement": "待确认", "falsified_if": "待确认"}],
        "quality_gates": {
            "min_evidence_records": 8,
            "required_corpus_roles": [
                "direct_solution",
                "open_scene",
                "substitute_rejector",
                "post_purchase_support",
                "control",
            ],
            "max_source_family_share": 0.65,
            "max_normalized_duplicate_rate": 0.02,
            "require_counter_evidence_for_validated": True,
        },
        "stopping_rules": [],
        "restart_rules": [],
        "route": route,
        "selected_methods": method_ids,
        "risk_flags": route.get("risk_flags", []),
        "safety_acknowledged": bool(acknowledge),
        "claim_types": list(CLAIM_TYPES),
    }
    (study_dir / "study.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_route(study_dir, route)
    for sub in ("01-sources/instruments", "01-sources/manifests", "02-data/raw", "03-codebook", "04-findings", "05-audit", "06-report"):
        (study_dir / sub).mkdir(parents=True, exist_ok=True)
    reasoning_scaffold = scaffold_product_reasoning(study_dir)
    _write_if_missing(study_dir / "04-findings" / "demand-judgments.json", "[]\n")

    rows = [
        ["direct_solution", "prototype_test", "待设计：验证特性/产品节点及方案接受", 2, 0.40, "planned", "自选择/活跃用户偏差", "feature;product"],
        ["open_scene", "field_observation", "待设计：验证场景/用户/痛点/需求节点", 2, 0.40, "planned", "场景覆盖偏差", "scene;user;pain;need"],
        ["substitute_rejector", "interview", "待设计：验证替代、反证与需求成立条件", 2, 0.40, "planned", "难触达/回忆偏差", "pain;need;feature"],
        ["post_purchase_support", "support_ticket", "待设计：验证特性组合与真实产品行为", 1, 0.40, "planned", "沉默用户缺失", "feature;product"],
        ["control", "control_survey", "待设计：验证场景边界、非用户与反例", 1, 0.40, "planned", "相关性低", "scene;user;pain"],
    ]
    with (study_dir / "01-sources" / "source-plan.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["corpus_role", "source_family", "route_or_query", "target_records", "cap_share", "access_status", "known_bias", "reasoning_nodes"])
        writer.writerows(rows)

    (study_dir / "01-sources" / "evidence-plan.json").write_text(
        json.dumps(
            {
                "domain": route["domain"],
                "stage": route["stage"],
                "methods": method_ids,
                "evidence_plan": pack.get("evidence_plan", []),
                "claim_boundaries": pack.get("claim_boundaries", []),
                "risk_flags": route.get("risk_flags", []),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    platform_plan = platform_fit(route["query"], route["domain"])
    (study_dir / "01-sources" / "platform-plan.json").write_text(
        json.dumps(platform_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (study_dir / "method-choice.json").write_text(
        json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (study_dir / "01-sources" / "research-plan.md").write_text(
        research_plan_markdown(study, route), encoding="utf-8"
    )
    instruments = generate_instruments(study_dir)
    (study_dir / "README.md").write_text(
        f"""# {study['title']}

- 产品类型：{route['domain_label']} (`{route['domain']}`)
- 阶段：{route['stage_label']} (`{route['stage']}`)
- 方法：{', '.join(item['name'] for item in selected)}
- 安全门：`{route['safety_gate']}`

## 产品推理主链

场景 → 用户 → 痛点 → 需求 → 特性 → 产品

先填写 `04-findings/product-reasoning.json`：每个节点都要有判断、推导理由、状态和假设；再针对最薄弱的节点设计采集与分析。

## 下一步

```bash
askovo chain .
# 填写 product-reasoning.json 与 study.json 后检查设计门
askovo check . --stage design
askovo instruments .
askovo import . <材料文件> --source-family interview
askovo deliver . --kind prd
```

先补全 `study.json` 的决策、假设、证伪条件、样本理由与停止规则。没有通过设计门前，不启动真实采集。
""",
        encoding="utf-8",
    )
    return {
        "status": "created",
        "study_dir": str(study_dir),
        "study_id": study_id,
        "domain": route["domain"],
        "stage": route["stage"],
        "risk_flags": route.get("risk_flags", []),
        "safety_gate": route["safety_gate"],
        "methods": method_ids,
        "product_reasoning": reasoning_scaffold["path"],
        "instruments": instruments,
    }


def research_plan_markdown(study: dict[str, Any], route: dict[str, Any]) -> str:
    lines = [
        f"# 研究计划：{study['title']}",
        "",
        "## 1. 决策",
        "",
        f"- 决策问题：{study['decision']['question']}",
        "- 选项：待确认（至少两个，含“不做”）",
        "- 负责人 / 截止日：待确认",
        "- 最低证据：待确认（什么情况下敢拍板）",
        "",
        "## 2. 产品推理主链",
        "",
        "场景 → 用户 → 痛点 → 需求 → 特性 → 产品",
        "",
        "在 `04-findings/product-reasoning.json` 中逐节点填写：判断、为什么由上一步推出、状态、证据、假设。",
        "产品推理是主干；下面的方法、来源和采集只负责修补最薄弱的节点或推导关系。",
        "",
        "| 节点 | 必须回答的推理问题 |",
        "|---|---|",
        "| 场景 | 什么触发、环境和任务边界构成了这个决策场景？ |",
        "| 用户 | 为什么是这个角色/用户状态，而不是泛泛的人口画像？ |",
        "| 痛点 | 当前替代方案在哪里失效，造成什么可观察后果？ |",
        "| 需求 | 为什么这些痛点构成值得满足的任务/结果，而非功能愿望？ |",
        "| 特性 | 为什么这个特性能满足需求？与替代特性相比，关键假设是什么？ |",
        "| 产品 | 为什么这些特性应组合成这个产品/MVP？边界、非目标和验收是什么？ |",
        "",
        "## 3. 产品与研究阶段",
        "",
        f"- 产品类型：{route['domain_label']} (`{route['domain']}`)",
        f"- 阶段：{route['stage_label']} (`{route['stage']}`)",
        f"- 支撑方法：{', '.join(item['name'] for item in route['recommended_methods'])}",
        "",
        "## 4. 推理假设与证伪",
        "",
        "- H1：待确认（必须落到具体节点或推导关系）",
        "- 证伪条件：待确认",
        "",
        "## 5. 证据计划（服务主链）",
        "",
    ]
    for item in route["recommended_methods"]:
        lines.append(
            f"- **{item['name']}**：{ '；'.join(item['answers']) }；"
            f"证据形式 `{', '.join(item['evidence_forms'])}`；"
            f"不能证明 `{', '.join(item['does_not_support'])}`"
        )
    lines.extend(["", "## 6. 本阶段要回答", ""])
    lines.extend(f"- {item}" for item in route.get("decisions", []))
    lines.extend(["", "## 7. 风险与停止规则", "", _risk_markdown(route.get("risk_flags", []))])
    lines.extend(
        [
            "- 采集前检查授权、隐私与参与者保护；高风险研究必须完成 S0。",
            "- 证据不足时输出研究状态与补证计划，不下结论。",
            "",
            "## 8. 交付物",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in route.get("deliverables", []))
    preview = route.get("platform_preview") or []
    if preview:
        lines.extend(["", "## 9. 数据来源预判", "", "| 平台 | 适配分 | 可用性 | 批量 |", "|---|---|---|---|"])
        for item in preview:
            lines.append(f"| {item['name']} | {item['score']} | {item['decision']} | {item['bulk']} |")
        lines.append("")
        lines.append("采集前先跑 `askovo platforms` 并记录访问依据、样本偏差与保留规则。")
    return "\n".join(lines) + "\n"


INSTRUMENT_RULES = {
    "interview-guide.md": ("discovery-interview", "contextual-inquiry", "diary-study", "survey-ua"),
    "observation-sheet.csv": ("contextual-inquiry", "prototype-usability", "clinic-static", "clinic-dynamic", "naturalistic-driving"),
    "task-script.md": ("prototype-usability", "task-analysis", "accessibility-eval"),
    "concept-test.md": ("concept-test", "packaging-test", "clinic-static"),
    "sensory-protocol.md": ("clt", "hut"),
    "pricing-questionnaire.md": ("pricing-vw", "pricing-gg", "conjoint", "maxdiff"),
    "beta-protocol.md": ("beta-soak", "telemetry-monitoring", "ab-test"),
    "field-protocol.md": ("driving-simulator", "closed-course", "on-road", "naturalistic-driving"),
    "test-matrix.csv": ("lab-bench",),
    "rma-review.csv": ("rma-review",),
    "shelf-test.md": ("shelf-test", "price-promo-test"),
    "accessibility-checklist.md": ("accessibility-eval",),
    "expert-review.md": ("expert-review",),
}


def _instrument_content(name: str, study: dict[str, Any], route: dict[str, Any]) -> str:
    title = study.get("title", "")
    domain = route.get("domain_label", "")
    stage = route.get("stage_label", "")
    if name.endswith(".csv"):
        if name == "observation-sheet.csv":
            return (
                "session_id,participant_role,scene,task,step,observation,quote,artifact,friction,timestamp,consent\n"
            )
        if name == "test-matrix.csv":
            return "test_id,protocol,variant,metric,threshold,lab_or_bench,report_ref,status\n"
        if name == "rma-review.csv":
            return "case_id,sku,batch,channel,use_days,reason_code,repair_action,nff,evidence_ref\n"
    if name == "interview-guide.md":
        return f"""# 访谈提纲：{title}

- 产品：{domain}；阶段：{stage}
- 决策问题：{study['decision']['question']}
- 目标角色：待确认（覆盖使用者、购买者/决策者、流失/替代者）

## 开场
- 目的、录音/记录授权、可随时退出、无对错。

## 最近一次真实事件
1. 请回忆最近一次 [场景]，当时发生了什么？
2. 你原本想完成什么？做到哪一步？
3. 你用了什么替代方案？为什么？
4. 最麻烦/最花时间/最担心的点是什么？后果是什么？
5. 如果问题不解决，会发生什么？

## 方案反应（如适用）
6. 你如何理解这个方案？哪里不清楚？
7. 它和现有做法相比，你会保留/放弃什么？
8. 什么条件下你会尝试？什么条件下不会？

## 收尾
- 反例：有没有人/场景不适用？
- 下一步：最便宜的验证是什么？
"""
    if name == "task-script.md":
        return f"""# 任务脚本：{title}

## 任务（按真实顺序，不提示操作）
- T1：
- T2：
- T3：

## 观察
- 是否独立完成；耗时；错误；求助；恢复；情绪/负担
- 出声思维；不引导；主持人只复述问题

## 成功规则
- 成功：
- 部分成功：
- 失败：

## 事后
- 逐任务 SEQ（1–7）
- 最卡的一步与原因
"""
    if name == "concept-test.md":
        return f"""# 概念/包装测试：{title}

- 刺激物版本：
- 随机/平衡顺序：
- 先理解后偏好：理解 → 相关性 → 独特性 → 取舍 → 购买意愿（标注“自述”）
- 与替代方案比较：
- 开放问题：哪里不可信/不清楚？
- 边界：概念胜出不等于实物喜好，购买意愿不换算销量。
"""
    if name == "sensory-protocol.md":
        return f"""# 感官/使用测试协议：{title}

## 样品与设计
- 样品编码、批次、制备、温度、份量
- 盲法/品牌信息、随机/平衡顺序、清洗/间隔
- 单一样品 / 成对 / 序列单一：

## 消费者喜好
- 9 点喜好量表；偏好排序；理由
- 不能证明性能、功效或安全

## HUT 日记
- 使用频率、用量、场景、弃用原因、不良体验
- 免费样品继续使用不等于复购
"""
    if name == "pricing-questionnaire.md":
        return f"""# 价格研究问卷：{title}

## 说明
- 明确产品/规格/竞品/渠道；随机价格；不诱导。
- 声明性价格不等于真实支付。

## Van Westendorp（如使用）
1. 多少钱算太便宜，以至于你怀疑质量？
2. 多少钱算便宜？
3. 多少钱算贵，但仍会考虑？
4. 多少钱算太贵，不会考虑？

## Gabor-Granger（如使用）
- 随机展示价格 P1/P2/P3；购买可能性 1–5。

## 联合分析（如使用）
- 属性与水平：
- 竞争集与“不选”：
- 模型假设与样本理由：
"""
    if name == "beta-protocol.md":
        return f"""# Beta / 遥测协议：{title}

- 版本/固件/OS/App：
- 参与者与招募偏差：
- 数据清单、授权、去标识、保留期：
- 事件与暴露分母：
- 崩溃/功耗/兼容/回归门槛：
- 退出、回滚、紧急停测：
- 边界：志愿者不等于全量；无报告不等于无问题。
"""
    if name == "field-protocol.md":
        return f"""# 现场/驾驶研究协议：{title}

- 环境：模拟器 / 封闭场地 / 实际道路 / 自然驾驶
- 车辆/设备与版本：
- 任务与场景：
- 安全审批、保险、路线、天气、限速、安全员、中止规则：
- 数据：位置/音视频/乘客/路人最小化与保留期：
- 边界：本协议不构成安全认证；零事件不等于安全。
"""
    if name == "shelf-test.md":
        return f"""# 货架/价格促销测试：{title}

- 真实/仿真货架；价格、库存、陈列一致
- 随机位置/陈列图；门店或人随机
- 指标：发现率、查找时间、选择份额、增量销量/毛利
- 混杂：缺货、店周聚类、促销、季节性
- 边界：模拟选择不等于实销；销量同增不等于增量。
"""
    if name == "accessibility-checklist.md":
        return f"""# 无障碍检查：{title}

- 覆盖：视觉、听觉、运动、认知、老年、临时障碍
- 辅助技术：屏幕阅读、放大、语音、开关、键盘
- 任务：核心任务能否独立完成；拒绝权限后的路径
- 人工检查 + 真实用户 + 标准对照（WCAG 等）
- 边界：自动扫描/合规不等于整机可用。
"""
    if name == "expert-review.md":
        return f"""# 专家红队审阅：{title}

- 每条结论：证据 id、证据类型、样本、版本、适用边界
- 反例：谁不适用？什么情况下结论相反？
- 跨层推断：需求/体验/性能/商业/安全是否混用？
- 会被问的 8 个问题与回答边界
- 输出：可说 / 不可说 / 补证 / 阻断项
"""
    return f"""# 授权与记录说明：{title}

- 研究目的与用途：
- 记录方式（笔记/录音/录像/日志）与范围：
- 自愿参与、可随时退出、不提供无关敏感信息：
- 数据访问、保留期、删除方式：
- 联系人：
"""


def generate_instruments(study_dir: Path) -> list[str]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    route = study.get("route") or {}
    selected = set(study.get("selected_methods", []))
    out_dir = study_dir / "01-sources" / "instruments"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, methods_for_file in INSTRUMENT_RULES.items():
        if selected.intersection(methods_for_file):
            if _write_if_missing(out_dir / name, _instrument_content(name, study, route)):
                written.append(name)
    if _write_if_missing(out_dir / "consent.md", _instrument_content("consent.md", study, route)):
        written.append("consent.md")
    return written


def _normalize_record(raw: dict[str, Any], index: int, defaults: dict[str, str]) -> dict[str, Any]:
    text = str(raw.get("text") or raw.get("内容") or raw.get("quote") or "")
    record_id = str(raw.get("record_id") or raw.get("id") or f"{defaults['source_family']}-{index:04d}")
    record = {
        "record_id": record_id,
        "context_key": str(raw.get("context_key") or ""),
        "user_role": str(raw.get("user_role") or raw.get("角色") or "unknown"),
        "scene_trigger": str(raw.get("scene_trigger") or raw.get("scene") or "unknown"),
        "task_outcome": str(raw.get("task_outcome") or raw.get("task") or "unknown"),
        "current_substitute": str(raw.get("current_substitute") or "unknown"),
        "friction_cost": str(raw.get("friction_cost") or raw.get("friction") or "unknown"),
        "consequence": str(raw.get("consequence") or "unknown"),
        "evidence_level": str(raw.get("evidence_level") or "unclassified"),
        "evidence_basis": str(raw.get("evidence_basis") or "imported; grade before use"),
        "corpus_role": str(raw.get("corpus_role") or "open_scene"),
        "source_family": str(raw.get("source_family") or defaults["source_family"]),
        "source_ref": str(raw.get("source_ref") or defaults["source_ref"]),
        "normalized_text_hash": str(raw.get("normalized_text_hash") or ""),
        "text": text,
        "claim_type": str(raw.get("claim_type") or defaults["claim_type"]),
        "evidence_form": str(raw.get("evidence_form") or defaults["evidence_form"]),
        "method_id": str(raw.get("method_id") or defaults["method_id"]),
        "product_domain": str(raw.get("product_domain") or defaults["product_domain"]),
        "validation_context": str(raw.get("validation_context") or "unknown"),
        "artifact_version": str(raw.get("artifact_version") or "unknown"),
        "imported_at": now(),
    }
    if not record["normalized_text_hash"]:
        seed = (text or record_id).encode("utf-8")
        record["normalized_text_hash"] = "sha256:" + hashlib.sha256(seed).hexdigest()
    return record


def import_material(
    study_dir: Path,
    file_path: Path,
    source_family: str = "imported",
    evidence_form: str = "self_report",
    claim_type: str = "need",
    method_id: str = "imported",
) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    raw_dir = study_dir / "02-data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    raw_copy = raw_dir / f"{stamp}-{file_path.name}"
    shutil.copy2(file_path, raw_copy)
    defaults = {
        "source_family": source_family,
        "source_ref": str(raw_copy),
        "claim_type": claim_type,
        "evidence_form": evidence_form,
        "method_id": method_id,
        "product_domain": str(study.get("product_domain") or "unknown"),
    }
    records: list[dict[str, Any]] = []
    suffix = file_path.suffix.lower()
    if suffix == ".jsonl":
        for index, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"JSONL line {index} is not an object")
            records.append(_normalize_record(raw, index, defaults))
    elif suffix == ".csv":
        with file_path.open(encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=1):
                records.append(_normalize_record(dict(row), index, defaults))
    else:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        records.append(_normalize_record({"text": text, "record_id": file_path.stem}, 1, defaults))

    evidence_path = study_dir / "02-data" / "evidence.jsonl"
    existing_ids: set[str] = set()
    if evidence_path.is_file():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    existing_ids.add(str(json.loads(line).get("record_id")))
                except json.JSONDecodeError:
                    continue
    added = 0
    with evidence_path.open("a", encoding="utf-8") as handle:
        for record in records:
            if record["record_id"] in existing_ids:
                continue
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing_ids.add(record["record_id"])
            added += 1
    return {
        "status": "imported",
        "file": str(file_path),
        "raw_copy": str(raw_copy),
        "parsed": len(records),
        "added": added,
        "skipped_duplicates": len(records) - added,
        "evidence_file": str(evidence_path),
    }


CODEBOOK_ROWS = (
    ("N1", "need", "用户任务、场景、替代与摩擦", "有真实事件与后果", "只有功能请求/偏好", "现有做法是 Excel + 微信群，因来回确认延误"),
    ("A1", "acceptance", "概念/方案的接受与拒绝", "理解后选择/拒绝并说明条件", "只表达喜欢", "愿意在试点中使用，但要求数据不出内网"),
    ("U1", "usability", "任务完成、错误、学习与恢复", "任务观察+成功率/错误/耗时", "满意度或主观偏好", "首次任务 5/8 成功，主要卡在权限设置"),
    ("P1", "performance", "明确协议下的工程性能", "校准仪器/协议/版本/报告", "跑分或均值", "同版本 200 次循环后延迟仍 <100ms"),
    ("C1", "commercial", "购买、付费、留存、复购、退换", "交易/续费/复购/RMA 分母", "口头意愿/点击", "30 个首购用户 60 天内 9 人再次付费"),
    ("S1", "safety", "使用风险、误用与合规缺口", "风险分析/专业试验/认证流程", "用户评分/无投诉", "高风险操作缺防护，需工程 V&V，不由用户研究认证"),
)


def scaffold_codebook(study_dir: Path) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    path = study_dir / "03-codebook" / "codebook.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return {"status": "exists", "path": str(path)}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "claim_type", "definition", "positive_criteria", "negative_criteria", "example", "version"])
        for row in CODEBOOK_ROWS:
            writer.writerow([*row, VERSION])
    return {"status": "created", "path": str(path), "rows": len(CODEBOOK_ROWS)}


def _evidence_summary(study_dir: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in ("02-data/evidence.jsonl", "02-data/normalized.jsonl"):
        path = study_dir / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(record.get("record_id") or record.get("normalized_text_hash") or "")
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    by_form: dict[str, int] = {}
    by_claim: dict[str, int] = {}
    for record in records:
        form = str(record.get("evidence_form") or "unknown")
        claim = str(record.get("claim_type") or "unknown")
        by_form[form] = by_form.get(form, 0) + 1
        by_claim[claim] = by_claim.get(claim, 0) + 1
    return {"count": len(records), "by_form": by_form, "by_claim": by_claim, "records": records}


def _delivery_records(reasoning: dict[str, Any] | None, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep all chain-cited positive/negative records, then add context up to 20."""
    records = evidence.get("records", [])
    by_id = {str(record.get("record_id")): record for record in records}
    ordered_ids: list[str] = []
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        for node_name in REASONING_NODES:
            node = nodes.get(node_name, {}) if isinstance(nodes, dict) else {}
            if isinstance(node, dict):
                ordered_ids.extend(str(value) for value in node.get("evidence_ids", []))
        ordered_ids.extend(str(value) for value in chain.get("counter_evidence_ids", []))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record_id in ordered_ids:
        if record_id in by_id and record_id not in seen:
            selected.append(by_id[record_id])
            seen.add(record_id)
    for record in records:
        record_id = str(record.get("record_id"))
        if len(selected) >= 20:
            break
        if record_id not in seen:
            selected.append(record)
            seen.add(record_id)
    return selected


def _brd_decision_lines(data: dict[str, Any]) -> list[str]:
    lines = ["## 2. BRD 商业决策", ""]
    chains = data.get("chains", [])
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        business = nodes.get("business", {}) if isinstance(nodes, dict) else {}
        if not isinstance(business, dict) or not business:
            lines.append("商业节点尚未建立；先完成市场研究、需求分析和商业验证。")
            continue
        gate = business.get("gate", {}) if isinstance(business.get("gate"), dict) else {}
        lines.extend(
            [
                f"### {chain.get('id', 'PR?')} · {business.get('statement', '待填写')}",
                "",
                f"- 产品→商业的推导：{business.get('rationale', '待填写')}",
                f"- 商业门：`{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}`",
                f"- 决策人：{gate.get('owner') or '待确认'}；资源承诺：{gate.get('resource_commitment') or '待确认'}",
                f"- 复审触发：{gate.get('revisit_trigger') or '待确认'}",
                f"- 商业证据：{', '.join(f'`{item}`' for item in business.get('evidence_ids', [])) or '未记录'}",
                f"- 需求判断：`{chain.get('demand_judgment_id') or '未关联'}`",
                f"- 下一项商业/产品验证：{chain.get('next_test') or '待确认'}",
                "",
            ]
        )
    lines.extend(
        [
            "BRD 的 Go/Kill/Hold/Recycle 或试点选择必须同时考虑用户价值、交付约束、市场证据、成本、资源和反证。",
            "市场规模必须有独立抽样框与估计方法；竞品报价、讨论热度、付费意愿和合成样例都不能单独证明商业成立。",
            "",
        ]
    )
    return lines


def _mrd_lines(data: dict[str, Any]) -> list[str]:
    lines = ["## 2. MRD 市场研究与分析", ""]
    chains = data.get("chains", [])
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        business = nodes.get("business", {}) if isinstance(nodes, dict) else {}
        if not isinstance(business, dict) or not business:
            lines.append("商业节点尚未建立；先完成市场研究、市场分析和 MRD 候选基线。")
            continue
        lines.extend(
            [
                f"### {chain.get('id', 'PR?')} 的市场边界与选择",
                "",
                f"- 市场定义：{business.get('market_definition') or '待填写'}",
                f"- 地理范围：{json.dumps(business.get('geographies', []), ensure_ascii=False)}",
                f"- 时间窗：{business.get('time_window') or '待填写'}",
                f"- 纳入市场：{json.dumps(business.get('included_markets', []), ensure_ascii=False)}",
                f"- 排除市场：{json.dumps(business.get('excluded_markets', []), ensure_ascii=False)}",
                f"- 目标细分：{business.get('target_segment') or '待填写'}",
                f"- 细分定义：{json.dumps(business.get('segments', []), ensure_ascii=False)}",
                f"- 付费者：{business.get('payer') or '待填写'}",
                f"- 竞争定位：{business.get('positioning') or '待填写'}",
                f"- 竞争与替代：{json.dumps(business.get('competitive_alternatives', []), ensure_ascii=False)}",
                f"- 渠道：{json.dumps(business.get('channels', []), ensure_ascii=False)}",
                f"- 价格假设：{business.get('pricing_hypothesis') or '待填写'}",
                f"- 价格口径：{json.dumps(business.get('pricing', []), ensure_ascii=False)}",
                f"- 市场估计口径：{json.dumps(business.get('market_estimates', []), ensure_ascii=False)}",
                "",
            ]
        )
    lines.extend(
        [
            "MRD 是商业节点中市场部分的候选基线与选择视图；它不证明用户需求、产品成功或精确市场规模。",
            "所有数字必须带总体、抽样框、时间窗、单位、公式、来源和推断范围；未知保留为未知，不用 0 或假精确值补齐。",
            "",
        ]
    )
    return lines


def _user_ops_lines(data: dict[str, Any]) -> list[str]:
    """Project the same chain for lifecycle operations; never infer audience size."""
    lines = [
        "## 2. 用户运营投影",
        "",
        "| 推理链 | 场景/触发 | 用户与状态 | 痛点/替代语言 | 特性与产品 | 商业接口 |",
        "|---|---|---|---|---|---|",
    ]
    chains = data.get("chains", [])
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        if not isinstance(nodes, dict):
            continue
        scene = nodes.get("scene", {})
        user = nodes.get("user", {})
        pain = nodes.get("pain", {})
        feature = nodes.get("feature", {})
        product = nodes.get("product", {})
        business = nodes.get("business", {})
        business_bits = []
        if isinstance(business, dict):
            if business.get("payer"):
                business_bits.append(f"付费者：{business['payer']}")
            if business.get("pricing_hypothesis"):
                business_bits.append(f"价格：{business['pricing_hypothesis']}")
            if business.get("channels"):
                business_bits.append(f"渠道：{json.dumps(business['channels'], ensure_ascii=False)}")
        lines.append(
            f"| {chain.get('id', '')} | {_markdown_cell(scene.get('trigger') or scene.get('statement'))} | "
            f"{_markdown_cell(str(user.get('role') or user.get('statement') or '') + ' / ' + str(user.get('state') or ''))} | "
            f"{_markdown_cell(str(pain.get('statement') or '') + '；替代：' + str(pain.get('current_substitute') or ''))} | "
            f"{_markdown_cell(str(feature.get('statement') or '') + ' / ' + str(product.get('statement') or ''))} | "
            f"{_markdown_cell('；'.join(business_bits))} |"
        )
    lines.extend(
        [
            "",
            "## 3. 生命周期干预与回流",
            "",
            "| 环节 | 行为分群/分母 | 干预假设 | 成功与护栏 | 回流节点 |",
            "|---|---|---|---|---|",
            "| 激活/采用/留存/流失/召回（按项目选择） | 待填：真实行为队列，不能用评论记录数代替 | 待填：改变哪个场景或痛点 | 待填：成功指标、分母、投诉/退订/隐私护栏 | 待填：scene/user/pain/need/feature/product/business |",
            "",
            "- 反馈进入同一 `product-reasoning.json` 的节点、假设或反证；不另建运营结论真值。",
            "- 卖点是主链的下游表达，不能反向替代用户需求和特性推导。",
            "- 分群规模、转化和留存必须来自有分母的一方行为数据；公开反馈只提供语言和假设。",
            "",
        ]
    )
    return lines


COST_NAME_PATTERN = re.compile(r"cost|费用|成本", re.IGNORECASE)


def _numeric_business_value(value: Any) -> float | None:
    """Return a float when the value is a real number; null/text stay unknown, never zero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def _chain_economics_section(chain: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Deterministic arithmetic projection of one chain's business node.

    Aggregation rules stay explicit: computation happens only for numeric
    pricing amounts and unit-matched numeric inputs with a source reference;
    "cost-like" grouping is name-based and labeled as indicative. null means
    unknown, never zero; no causal or commercial proof is claimed.
    """
    business = (chain.get("nodes") or {}).get("business") or {}
    lines: list[str] = []
    stats = {
        "id": str(chain.get("id") or "chain"),
        "title": str(chain.get("title") or ""),
        "prices": 0,
        "unit_matched_inputs": 0,
        "unknown_inputs": 0,
        "provenance_warnings": 0,
        "computed": False,
    }
    lines.append(f"## {stats['id']} — {stats['title'] or '（未命名）'}")
    lines.append("")
    lines.append(f"- 收入模型：{business.get('revenue_model') or '未填写'}")
    lines.append(f"- 定价假设：{business.get('pricing_hypothesis') or '未填写'}")
    lines.append("")

    prices = []
    for entry in business.get("pricing") or []:
        if not isinstance(entry, dict):
            continue
        amount = _numeric_business_value(entry.get("amount"))
        ev = ", ".join(str(x) for x in entry.get("evidence_ids") or [])
        lines.append(
            f"- 定价：{entry.get('model') or '未命名'} = "
            f"{entry.get('amount') if entry.get('amount') is not None else '未知'} "
            f"{entry.get('currency') or ''}/{entry.get('unit') or '单位未注明'}"
            f"（{entry.get('term') or '期限未注明'}；证据：{ev or '无'}）"
        )
        if amount is not None and amount > 0:
            prices.append((entry, amount))
    stats["prices"] = len(prices)
    lines.append("")

    inputs = [item for item in business.get("unit_economics_inputs") or [] if isinstance(item, dict)]
    known: list[tuple[dict[str, Any], float]] = []
    unknown: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in inputs:
        value = _numeric_business_value(item.get("value"))
        has_source = bool(str(item.get("source_ref") or "").strip())
        if value is None:
            unknown.append(item)
            continue
        if not has_source:
            warnings.append(f"{item.get('metric') or '未命名'}：数值 {value} 缺少 source_ref，不进入计算")
            unknown.append(item)
            continue
        known.append((item, value))
    stats["unknown_inputs"] = len(unknown)
    stats["provenance_warnings"] = len(warnings)

    lines.append("### 单位经济输入（带来源的数值才可计算）")
    lines.append("")
    lines.append("| 输入 | 数值 | 单位 | 来源 |")
    lines.append("|---|---|---|---|")
    for item, value in known:
        lines.append(
            f"| {item.get('metric') or '未命名'} | {value:g} | {item.get('unit') or '未注明'} | "
            f"{item.get('source_ref') or ''} |"
        )
    for item in unknown:
        shown = item.get("value") if item.get("value") is not None else "未知（null 不是 0）"
        lines.append(f"| {item.get('metric') or '未命名'} | {shown} | {item.get('unit') or '未注明'} | 未知/缺来源 |")
    lines.append("")

    for entry, amount in prices:
        unit = str(entry.get("unit") or "").strip()
        matched = [(item, value) for item, value in known if str(item.get("unit") or "").strip() == unit]
        stats["unit_matched_inputs"] += len(matched)
        model = entry.get("model") or "定价"
        lines.append(f"### 计算：{model}（{amount:g} / {unit or '单位未注明'}）")
        lines.append("")
        if not matched:
            lines.append(f"- 没有单位匹配（unit = “{unit or '未注明'}”）且带来源的数值输入；无法进行任何算术。")
            lines.append("")
            continue
        cost_like = [
            (item, value)
            for item, value in matched
            if COST_NAME_PATTERN.search(str(item.get("metric") or "")) or COST_NAME_PATTERN.search(str(item.get("status") or ""))
        ]
        for item, value in matched:
            delta = amount - value
            multiple = amount / value if value else None
            multiple_text = f"；{multiple:.2f}×" if multiple is not None else ""
            lines.append(
                f"- {item.get('metric') or '未命名'}：{amount:g} − {value:g} = {delta:g}（单位 {unit or '未注明'}）{multiple_text}"
            )
        if cost_like:
            cost_sum = sum(value for _, value in cost_like)
            margin = (amount - cost_sum) / amount * 100 if amount else None
            names = "、".join(str(item.get("metric")) for item, _ in cost_like)
            lines.append("")
            lines.append(f"- 指示性成本类合计（仅按名称匹配“cost/成本/费用”：{names}）：{cost_sum:g}")
            if margin is not None:
                lines.append(f"- 指示性毛利：{amount:g} − {cost_sum:g} = {amount - cost_sum:g}（{margin:.1f}%）")
            lines.append("- 上述合计依赖输入命名与单位一致，不构成成本口径核验；财务评审独立进行。")
            stats["computed"] = True
        lines.append("")

    if warnings:
        lines.append("### 来源缺口")
        lines.append("")
        lines.extend(f"- {text}" for text in warnings)
        lines.append("")
    lines.append("---")
    lines.append("")
    return lines, stats


def unit_economics_report(reasoning: dict[str, Any], title: str) -> tuple[str, dict[str, Any]]:
    """Render the unit-economics projection for every chain with a business node."""
    chains = [c for c in reasoning.get("chains", []) if isinstance(c, dict)]
    sections: list[str] = []
    stats: list[dict[str, Any]] = []
    for chain in chains:
        if not isinstance(chain.get("nodes") or {}, dict):
            continue
        if "business" not in (chain.get("nodes") or {}):
            continue
        section, chain_stats = _chain_economics_section(chain)
        sections.extend(section)
        stats.append(chain_stats)
    lines = [
        "# 单位经济投影（Unit Economics Projection）",
        "",
        f"> 来自产品与商业推理主链「{title}」的确定性算术投影。",
        "> 只对 business 节点中带来源引用、单位匹配的数值输入做计算；null 表示未知，不是零。",
        "> 本投影不构成商业证明、发布就绪或因果结论；E4/E5 商业证据、财务评审与人工决策保持独立。",
        "",
    ]
    if not sections:
        lines.append("（当前没有包含商业节点的 chain；`askovo chain` 脚手架后填写 business 节点。）")
        lines.append("")
    lines.extend(sections)
    return "\n".join(lines), {"chains": stats}


PSM_COLUMN_ALIASES: dict[str, str] = {
    "too_cheap": "too_cheap", "toocheap": "too_cheap", "太便宜": "too_cheap",
    "cheap": "cheap", "便宜": "cheap",
    "expensive": "expensive", "贵": "expensive",
    "too_expensive": "too_expensive", "tooexpensive": "too_expensive", "太贵": "too_expensive",
}


def _parse_psm_rows(csv_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse a van Westendorp CSV into valid rows and rejected rows."""
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        raw_fields = [(str(f or "").strip()) for f in (reader.fieldnames or [])]
        mapping = {PSM_COLUMN_ALIASES.get(f.lower(), f.lower()): f for f in raw_fields}
        missing = [key for key in ("too_cheap", "cheap", "expensive", "too_expensive") if key not in mapping]
        if missing:
            raise ValueError(f"PSM CSV 缺少列：{', '.join(missing)}（需要 too_cheap/cheap/expensive/too_expensive）")
        for index, row in enumerate(reader, start=2):
            respondent = str(row.get(mapping.get("respondent_id") or mapping.get("id") or "") or f"row{index}").strip()
            values: dict[str, float] = {}
            broken = False
            for key in ("too_cheap", "cheap", "expensive", "too_expensive"):
                number = _numeric_business_value(row.get(mapping[key]))
                if number is None or number < 0:
                    rejected.append({"respondent": respondent, "reason": f"{key} 非数值"})
                    broken = True
                    break
                values[key] = number
            if broken:
                continue
            if not (values["too_cheap"] <= values["cheap"] <= values["expensive"] <= values["too_expensive"]):
                rejected.append({"respondent": respondent, "reason": "四价排序不满足 太便宜≤便宜≤贵≤太贵"})
                continue
            values["respondent"] = respondent
            valid.append(values)
    return valid, rejected


def _psm_intersections(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute van Westendorp curve intersections on the observed price grid."""
    count = len(rows)
    grid = sorted({row[key] for row in rows for key in ("too_cheap", "cheap", "expensive", "too_expensive")})

    def share_at_or_above(key: str, price: float) -> float:
        return sum(1 for row in rows if row[key] >= price) / count

    def share_at_or_below(key: str, price: float) -> float:
        return sum(1 for row in rows if row[key] <= price) / count

    curves = {
        "too_cheap": lambda p: share_at_or_above("too_cheap", p),
        "cheap": lambda p: share_at_or_above("cheap", p),
        "expensive": lambda p: share_at_or_below("expensive", p),
        "too_expensive": lambda p: share_at_or_below("too_expensive", p),
    }

    def crossing(first: str, second: str) -> float | None:
        """Interpolate across the sign change, spanning any zero plateau in between."""
        last_positive: tuple[float, float] | None = None
        last_negative: tuple[float, float] | None = None
        for price in grid:
            difference = curves[first](price) - curves[second](price)
            if difference > 0:
                if last_negative is not None:
                    base, base_diff = last_negative
                    return base + (price - base) * (base_diff / (base_diff - difference))
                last_positive = (price, difference)
            elif difference < 0:
                if last_positive is not None:
                    base, base_diff = last_positive
                    return base + (price - base) * (base_diff / (base_diff - difference))
                last_negative = (price, difference)
        return None

    return {
        "n": count,
        "pmc": crossing("too_cheap", "expensive"),
        "opp": crossing("too_cheap", "too_expensive"),
        "idp": crossing("cheap", "expensive"),
        "pme": crossing("cheap", "too_expensive"),
    }


def psm_report(csv_path: Path, currency: str, study_ref: str = "") -> tuple[str, dict[str, Any]]:
    """Van Westendorp price-sensitivity projection with explicit intent boundaries."""
    valid, rejected = _parse_psm_rows(csv_path)
    result: dict[str, Any] = {"valid_rows": len(valid), "rejected_rows": len(rejected)}
    lines = [
        "# 价格敏感度（van Westendorp PSM）投影",
        "",
        "> 四问口径：太便宜 / 便宜 / 贵 / 太贵。交点由样本累积分布线性插值得出。",
        "> PSM 是陈述意向，不是付费行为：结果不能直接作为商业节点 validated 证据（E4/E5 需一方付费证据），",
        "> 竞品标价也不是自有定价证据。样本代表性、购买意向偏差与货币口径需人工评审。",
        "> 交点结论如需计入商业节点：回写 business.pricing 并引用一条注册的 E4-（陈述意向）证据，",
        "> 否则 `askovo check` 会提示 pricing-psm.md 是游离报告。",
        "",
        f"- 输入：{csv_path.name}；有效 {len(valid)} 行，剔除 {len(rejected)} 行",
        f"- 币种标注：{currency}",
        f"- 归属 study：{study_ref or '未注明（未在 study 目录内运行，不关联 study 契约）'}",
        "",
    ]
    if rejected:
        lines.append("### 剔除行（最多列 10 条）")
        lines.append("")
        lines.extend(f"- {item['respondent']}：{item['reason']}" for item in rejected[:10])
        lines.append("")
    if valid:
        points = _psm_intersections(valid)
        result["intersections"] = points
        labels = {
            "pmc": "PMC 边际廉价点（too_cheap × expensive）",
            "opp": "OPP 最优价格点（too_cheap × too_expensive）",
            "idp": "IDP 无差异价格点（cheap × expensive）",
            "pme": "PME 边际昂贵点（cheap × too_expensive）",
        }
        lines.append("### 交点")
        lines.append("")
        for key, label in labels.items():
            value = points[key]
            lines.append(f"- {label}：{value:.2f} {currency}" if value is not None else f"- {label}：无交点")
        if points["pmc"] is not None and points["pme"] is not None and points["pmc"] < points["pme"]:
            lines.append(f"- 可接受价格区间（PMC, PME）：{points['pmc']:.2f} – {points['pme']:.2f} {currency}")
        lines.append("")
    else:
        result["intersections"] = None
        lines.append("（没有有效行，无法计算交点。）")
        lines.append("")
    return "\n".join(lines), result


def _decision_package_lines(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any],
    audit_status: str = "not_run",
) -> list[str]:
    """Decision Package：同一条推理链/需求判断的五个决策侧视图。

    机会地图 / 证据图 / 选项与权衡 / 决策备忘 / 验证清单——全部字段来自
    04-findings 的链与判定，本函数不产生新事实、不合成数字；决策边界与
    支撑证据表由 deliver() 统一追加。MRD/PRD/BRD 是本包的市场/需求/商业
    投影，不是独立结论来源。
    """
    route = study.get("route") or {}
    decision = study.get("decision") or {}
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [chain for chain in chains if isinstance(chain, dict)]
    levels = {
        str(record.get("record_id")): str(record.get("evidence_level") or "unclassified")
        for record in evidence.get("records", [])
    }
    lines: list[str] = [
        f"# 决策包 Decision Package：{study.get('title', '')}",
        "",
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label', study.get('product_domain', ''))}；"
        f"阶段：{route.get('stage_label', study.get('lifecycle_stage', ''))}。",
        "",
        f"- 决策问题：{decision.get('question') or study.get('decision_question') or study.get('title', '待确认')}",
        f"- 决策负责人：{decision.get('owner') or '待确认'}；截止：{decision.get('deadline') or '未设置'}",
        f"- 审计状态：`{audit_status}`（full audit）",
        "",
        "> 本包是研究投影：所有判断、证据与缺口以 `04-findings/` 为准；证据强度不等于商业或发布证明。",
        "",
    ]
    if audit_status != "pass":
        lines.extend([
            "> **审计未通过：本决策包不是可签收推荐。** 已决链仅作为待修正草案；"
            "请先修复 `askovo check --stage full` 的失败项。",
            "",
        ])

    # ── 1. 机会地图 ────────────────────────────────────────────
    lines.extend(["## 1. 机会地图（Opportunity Map）", ""])
    if not chains:
        lines.extend(
            [
                "尚无产品推理链。机会地图需要至少一条 `scene → … → business` 主链："
                "先运行 `askovo do` 建立研究工作区并补齐推理链，再生成决策包。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "| 主链 | 机会（场景×用户×痛点） | 状态 | 节点就绪 | 需求判断 | 优先级结论 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for chain in chains:
            nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
            flow_value = (reasoning or {}).get("flow")
            flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
            validated = sum(
                1 for name in flow
                if isinstance(nodes.get(name), dict) and nodes.get(name, {}).get("status") == "validated"
            )
            scene = nodes.get("scene", {}) if isinstance(nodes.get("scene"), dict) else {}
            user = nodes.get("user", {}) if isinstance(nodes.get("user"), dict) else {}
            pain = nodes.get("pain", {}) if isinstance(nodes.get("pain"), dict) else {}
            opportunity = "／".join(
                str(part) for part in (
                    scene.get("statement"), user.get("role"), pain.get("statement"),
                ) if part
            ) or chain.get("title", "未命名")
            prioritization = chain.get("prioritization", {})
            priority_bit = ""
            if isinstance(prioritization, dict) and prioritization.get("rationale"):
                priority_bit = str(prioritization.get("rationale"))
            lines.append(
                f"| `{chain.get('id', 'PR?')}` | {_markdown_cell(opportunity)} | "
                f"`{chain.get('status', 'unknown')}` | {validated}/{len(flow)} validated | "
                f"`{chain.get('demand_judgment_id') or '未关联'}` | {_markdown_cell(priority_bit or '未记录')} |"
            )
        lines.extend(
            [
                "",
                "节点就绪 = 已验证节点数 / 主链节点总数；`decided` 才进入第 4 节决策备忘。",
                "",
            ]
        )

    # ── 2. 证据图 ──────────────────────────────────────────────
    lines.extend(["## 2. 证据图（Evidence Graph）", ""])
    if not chains:
        lines.append("无链可引用；证据图随推理链建立生成。")
        lines.append("")
    for chain in chains:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        flow_value = (reasoning or {}).get("flow")
        flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
        lines.extend(
            [
                f"### {chain.get('id', 'PR?')} 的证据支撑",
                "",
                "| 节点 | 状态 | 引用证据（等级） |",
                "|---|---|---|",
            ]
        )
        level_counter: dict[str, int] = {}
        for name in flow:
            node = nodes.get(name, {})
            if not isinstance(node, dict):
                node = {}
            ids = [str(item) for item in node.get("evidence_ids", [])]
            rendered = ", ".join(f"`{item}`（{levels.get(item, '?')}）" for item in ids)
            for item in ids:
                level_counter[levels.get(item, "?")] = level_counter.get(levels.get(item, "?"), 0) + 1
            lines.append(
                f"| {REASONING_NODE_LABELS[name]} | `{node.get('status', 'unknown')}` | "
                f"{_markdown_cell(rendered) or '—'} |"
            )
        counter_ids = [str(item) for item in chain.get("counter_evidence_ids", [])]
        for item in counter_ids:
            level_counter[levels.get(item, "?")] = level_counter.get(levels.get(item, "?"), 0) + 1
        counter_rendered = ", ".join(
            "`%s`（%s）" % (item, levels.get(item, "?")) for item in counter_ids
        )
        lines.append(f"- 反证：{counter_rendered or '未记录'}")
        lines.append(
            f"- 证据等级分布（本链引用）：{json.dumps(level_counter, ensure_ascii=False) if level_counter else '无引用'}"
        )
        lines.append(
            f"- 需求判断链接：`{chain.get('demand_judgment_id') or '未关联'}`；"
            f"context_key `{chain.get('context_key') or '未设置'}`（链/判定/证据三方一致才有效，"
            "以 `askovo audit` 判定为准）"
        )
        lines.append("")

    # ── 3. 选项与权衡 ─────────────────────────────────────────
    lines.extend(["## 3. 选项与权衡（Options & Trade-offs）", ""])
    if len(chains) >= 2:
        lines.extend(
            [
                "同一组字段横向比较，不计算综合分，也不把字段齐全当成方案更优：",
                "",
                "| 选项（主链） | 状态 | 节点就绪 | 证据数 | 反证数 | 商业门 | 资源承诺 | 优先级方法与因素 | 关键缺口 | 下一验证 |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ]
        )
        flow_value = (reasoning or {}).get("flow")
        flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
        for chain in chains:
            nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
            validated = sum(
                1 for name in flow
                if isinstance(nodes.get(name), dict) and nodes.get(name, {}).get("status") == "validated"
            )
            evidence_count = sum(
                len(nodes.get(name, {}).get("evidence_ids", []))
                for name in flow if isinstance(nodes.get(name), dict)
                and isinstance(nodes.get(name, {}).get("evidence_ids"), list)
            )
            business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
            gate = business.get("gate", {}) if isinstance(business.get("gate"), dict) else {}
            prioritization = chain.get("prioritization", {})
            if not isinstance(prioritization, dict):
                prioritization = {}
            factors = prioritization.get("factors")
            factors_text = json.dumps(factors, ensure_ascii=False) if factors else "未记录"
            method = prioritization.get("method") or "未记录"
            counter_count = len(chain.get("counter_evidence_ids") or [])
            lines.append(
                f"| `{chain.get('id', 'PR?')}` {_markdown_cell(chain.get('title', ''))} | "
                f"`{chain.get('status', 'unknown')}` | {validated}/{len(flow)} | {evidence_count} | "
                f"{counter_count} | `{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}` | "
                f"{_markdown_cell(gate.get('resource_commitment') or '未记录')} | "
                f"{_markdown_cell(method + '；' + factors_text)} | "
                f"{_markdown_cell('；'.join(str(g) for g in chain.get('gaps', [])) or '未记录')} | "
                f"{_markdown_cell(chain.get('next_test') or '未记录')} |"
            )
        lines.extend([
            "",
            "证据数只表示引用数量，不表示证据质量；反证数只表示记录数量，不表示严重性。"
            "方案取舍仍需逐条阅读证据等级、适用条件和未验证假设。",
            "",
        ])
    elif len(chains) == 1:
        chain = chains[0]
        alternatives = chain.get("alternative_explanations", [])
        lines.append(
            f"当前只有单一主链 `{chain.get('id', 'PR?')}`，尚未形成多方案对比——这不代表它是最优解，"
            "只代表尚未构造竞争选项。该链自身的替代解释："
        )
        lines.append("")
        if alternatives:
            for item in alternatives:
                lines.append(f"- {item}")
        else:
            lines.append("- 未记录替代解释（决策前必须补齐，见产品推理协议）。")
        lines.append("")
    else:
        lines.append("无选项可比。")
        lines.append("")

    # ── 4. 决策备忘 ────────────────────────────────────────────
    lines.extend(["## 4. 决策备忘（Decision Memo）", ""])
    decided = [chain for chain in chains if chain.get("status") == "decided"] \
        if audit_status == "pass" else []
    rejected = [chain for chain in chains if chain.get("status") in ("rejected", "deprioritized")]
    if not decided:
        if audit_status != "pass":
            lines.append("**当前审计未通过，不能形成已决推荐。** 以下为已决链的待修正缺口：")
        else:
            lines.append("**尚无可决策主链**（没有 `decided` 状态的链）。决策备忘降级为缺口清单：")
        lines.append("")
        for chain in chains:
            nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
            flow_value = (reasoning or {}).get("flow")
            flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
            unvalidated = [
                REASONING_NODE_LABELS[name]
                for name in flow
                if not (isinstance(nodes.get(name), dict) and nodes.get(name, {}).get("status") == "validated")
            ]
            lines.append(
                f"- `{chain.get('id', 'PR?')}`（`{chain.get('status', 'unknown')}`）："
                f"未达标节点 {'、'.join(unvalidated) or '无'}；"
                f"`decided` 需全部节点 validated + 已验证判定 + 替代解释 + 反证 + 优先级记录。"
            )
        if not chains:
            lines.append("- 无推理链：先 `askovo do` 与 `askovo chain`。")
        lines.append("")
    else:
        for chain in decided:
            nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
            business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
            gate = business.get("gate", {}) if isinstance(business.get("gate"), dict) else {}
            prioritization = chain.get("prioritization", {})
            states = chain.get("supporting_states", {}) if isinstance(chain.get("supporting_states"), dict) else {}
            state_bits = []
            for key, label in (("delivery", "交付"), ("outcome", "结果"), ("causal", "因果")):
                value = states.get(key, {}) if isinstance(states.get(key), dict) else {}
                if value.get("status"):
                    state_bits.append(f"{label} `{value['status']}`")
            lines.extend(
                [
                    f"### {chain.get('id', 'PR?')} · {chain.get('title', '')}",
                    "",
                    f"- 推荐读法：`decided` 是**产品/商业选择记录**，不是发布或商业成功证明。",
                    f"- 优先级：方法 {prioritization.get('method') or '待确认'}；"
                    f"负责人 {prioritization.get('owner') or '待确认'}；"
                    f"理由 {prioritization.get('rationale') or '待确认'}",
                    f"- 商业门：`{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}`；"
                    f"资源承诺 {gate.get('resource_commitment') or '待确认'}",
                    f"- 置信边界：反证 {', '.join(f'`{i}`' for i in chain.get('counter_evidence_ids', [])) or '未记录'}；"
                    f"缺口 {'；'.join(str(g) for g in chain.get('gaps', [])) or '未记录'}",
                    f"- 交付/结果/因果三态（互相独立，不得互推）：{'；'.join(state_bits) or '未记录'}",
                    "",
                ]
            )
        if rejected:
            lines.append("未选择的方向及原因：")
            lines.append("")
            for chain in rejected:
                prioritization = chain.get("prioritization", {})
                rationale = (prioritization or {}).get("rationale") if isinstance(prioritization, dict) else ""
                lines.append(
                    f"- `{chain.get('id', 'PR?')}`（`{chain.get('status')}`）："
                    f"{_markdown_cell(str(rationale or '未记录放弃理由'))}"
                )
            lines.append("")

    # ── 5. 验证清单 ────────────────────────────────────────────
    lines.extend(["## 5. 验证清单（Validation Backlog）", ""])
    if not chains:
        lines.append("无链可验证。")
        lines.append("")
    for chain in chains:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        flow_value = (reasoning or {}).get("flow")
        flow = tuple(flow_value) if isinstance(flow_value, list) and flow_value else REASONING_NODES
        pending = [
            REASONING_NODE_LABELS[name]
            for name in flow
            if (isinstance(nodes.get(name), dict)
                and nodes.get(name, {}).get("status") in ("hypothesis", "needs-validation"))
        ]
        marker = "（已决，交付后回看）" if chain.get("status") == "decided" else ""
        lines.append(
            f"- `{chain.get('id', 'PR?')}`{marker}：待验证节点 "
            f"{'、'.join(pending) or '无'}；缺口 {'；'.join(str(g) for g in chain.get('gaps', [])) or '未记录'}；"
            f"最便宜且能改变决策的下一验证：{chain.get('next_test') or '未记录'}"
        )
    lines.append("")
    lines.append(
        "排序原则：优先做**最便宜且能改变决策**的验证；validated 的等级门槛"
        "（scene/user 任意非 E4−、pain/need E1/E2、feature/product E3、business E4+/E5）"
        "以 `askovo audit` 判定为准，本清单不重算。"
    )
    lines.append("")
    lines.extend(
        [
            "## 边界",
            "",
            "决策包是产品与商业推理链的决策侧投影，不构成发布就绪、市场体量、因果或商业成功的证明；"
            "MRD/PRD/BRD/运营视图均由同一条链投影生成，不产生独立结论；最终产品/商业决定由负责人做出并留痕。",
            "",
        ]
    )
    return lines


def deliver(study_dir: Path, kind: str = "memo", audit: Any | None = None) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    route = study.get("route") or {}
    evidence = _evidence_summary(study_dir)
    reasoning = load_product_reasoning(study_dir)
    if audit is not None and hasattr(audit, "as_dict"):
        audit_info = audit.as_dict()
    elif isinstance(audit, dict):
        audit_info = audit
    else:
        # Direct library callers do not get a fresh pass silently: absence of an
        # audit is reported as not_run, not as a successful audit.
        audit_info = {"status": "not_run", "generated_at": "", "checks": []}
    audit_status = str(audit_info.get("status") or "not_run")
    audit_failed = audit_status != "pass"
    out_dir = study_dir / "06-report"
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "tracker":
        path = out_dir / "postlaunch-tracker.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["version", "metric", "numerator", "denominator", "window", "guardrail", "owner", "status", "note", "chain_id", "node_id", "intervention_id", "learning", "next_action", "delivery_status", "outcome_status", "causal_status"])
            owner = str((study.get("decision") or {}).get("owner") or "待确认")
            chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
            for chain in chains if isinstance(chains, list) else []:
                if not isinstance(chain, dict):
                    continue
                states = chain.get("supporting_states", {})
                delivery_status = str(states.get("delivery", {}).get("status", "unplanned")) if isinstance(states, dict) else "unplanned"
                outcome_status = str(states.get("outcome", {}).get("status", "unmeasured")) if isinstance(states, dict) else "unmeasured"
                causal_status = str(states.get("causal", {}).get("status", "not-claimed")) if isinstance(states, dict) else "not-claimed"
                nodes = chain.get("nodes", {})
                if not isinstance(nodes, dict):
                    continue
                for node_name, field_name in (("feature", "acceptance_conditions"), ("product", "acceptance_criteria"), ("business", "success_metrics")):
                    node = nodes.get(node_name, {})
                    if not isinstance(node, dict):
                        continue
                    for criterion in node.get(field_name, []):
                        numerator = ""
                        denominator = ""
                        window = ""
                        guardrail = "反证：" + ",".join(str(item) for item in chain.get("counter_evidence_ids", []))
                        note = node.get("statement", "")
                        if node_name == "business" and isinstance(criterion, dict):
                            numerator = str(criterion.get("numerator") or "")
                            denominator = str(criterion.get("denominator") or "")
                            window = str(criterion.get("window") or "")
                            guardrail = str(criterion.get("guardrail") or guardrail)
                            note = f"{criterion.get('definition', note)}；目标：{criterion.get('target', '待确认')}"
                            criterion = str(criterion.get("metric_id") or criterion.get("definition") or "business_metric")
                        writer.writerow([
                            "planned", criterion, numerator, denominator, window,
                            guardrail, owner, chain.get("status", "planned"), note,
                            chain.get("id", ""), node_name, "", "", chain.get("next_test", ""),
                            delivery_status, outcome_status, causal_status,
                        ])
        return {"status": "written", "path": str(path), "kind": kind}

    titles = {"memo": "决策备忘", "report": "产品推理报告", "mrd": "MRD 市场需求文档", "prd": "PRD 产品需求文档", "brd": "BRD 商业需求文档", "ops": "用户运营交付", "decision": "决策包 Decision Package", "signoff": "干系人签收页"}
    title = titles.get(kind, "交付物")
    if kind == "decision":
        path = out_dir / "decision-package.md"
        path.write_text(
            "\n".join(_decision_package_lines(study, reasoning, evidence, audit_status)) + "\n",
            encoding="utf-8",
        )
        return {
            "status": "written",
            "path": str(path),
            "kind": kind,
            "audit_status": audit_status,
            "audit_generated_at": audit_info.get("generated_at", ""),
            "evidence_count": evidence["count"],
            "product_reasoning": product_reasoning_summary(reasoning),
        }
    if kind == "signoff":
        if reasoning is not None and audit_failed:
            return {
                "status": "blocked",
                "kind": kind,
                "audit_status": audit_status,
                "reason": "full audit failed or was not run; a sign-off page cannot be issued",
                "checks": [c for c in audit_info.get("checks", []) if c.get("status") == "fail"],
            }
        if reasoning is None:
            return {
                "status": "blocked",
                "kind": kind,
                "audit_status": audit_status,
                "reason": "no product-reasoning chain exists; run askovo chain before sign-off",
            }
        path = out_dir / "signoff.md"
        path.write_text(
            _signoff_page(study, reasoning, study_dir, audit_status=audit_status),
            encoding="utf-8",
        )
        return {
            "status": "written",
            "path": str(path),
            "kind": kind,
            "audit_status": audit_status,
            "audit_generated_at": audit_info.get("generated_at", ""),
            "evidence_count": evidence["count"],
            "product_reasoning": product_reasoning_summary(reasoning),
        }
    lines = [
        f"# {title}：{study.get('title', '')}",
        "",
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label', study.get('product_domain', ''))}；"
        f"阶段：{route.get('stage_label', study.get('lifecycle_stage', ''))}。",
        f"> 审计状态：`{audit_status}`（生成时间：{audit_info.get('generated_at') or '未运行'}）。",
        "",
    ]
    if audit_failed:
        lines.extend([
            "> **审计未通过：本文件不能作为已审核结论或签收依据。** "
            "请先运行 `askovo check --stage full` 并修复失败项。",
            "",
        ])
    if kind == "report":
        lines.extend(
            [
                "## 研究方法与样本（支撑层）",
                "",
                f"- 方法：{', '.join(study.get('selected_methods', []))}",
                "- 样本与流失：待补",
                "",
            ]
        )
    lines.extend(["## 1. 产品与商业推理主链", ""])
    if reasoning is not None:
        lines.extend(_product_chain_lines(reasoning))
    else:
        lines.extend(
            [
                "尚未建立 `04-findings/product-reasoning.json`。先补齐“场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业”，再交付产品与商业结论。",
                "",
            ]
        )
    if kind == "brd" and reasoning is not None:
        lines.extend(_brd_decision_lines(reasoning))
    elif kind == "mrd" and reasoning is not None:
        lines.extend(_mrd_lines(reasoning))
    elif kind == "ops" and reasoning is not None:
        lines.extend(_user_ops_lines(reasoning))
    else:
        lines.extend(
            [
                "## 2. 产品决策",
                "",
                "- 建议（做/不做/调整哪个节点，必须对应上方推理链）：",
                "- 适用条件与代价：",
                "- 优先级依据（后果、替代成本、证据强度、战略匹配分别说明）：",
                "",
            ]
        )
    lines.extend(
        [
            "## 支撑证据",
            "",
            "| 证据 | 类型 | 证据形式 | 说明 |",
            "|---|---|---|---|",
        ]
    )
    for record in _delivery_records(reasoning, evidence):
        basis = str(
            record.get("evidence_basis")
            or record.get("title")
            or record.get("text")
            or ""
        )[:120].replace("|", "\\|")
        lines.append(
            f"| `{record.get('record_id')}` | {record.get('claim_type')} | "
            f"{record.get('evidence_form')} | {basis} |"
        )
    if not evidence["records"]:
        lines.append("| — | — | — | 尚无导入证据 |")
    lines.extend(
        [
            "",
            "## 反证、缺口与下一步",
            "",
            "- 缺口（按推理节点和推导关系列）：",
            "- 反证与替代解释：",
            "- 最便宜且能改变决策的下一验证：",
            "",
            "## 附录：证据概况",
            "",
            f"- 记录数：{evidence['count']}",
            f"- 按证据形式：{json.dumps(evidence['by_form'], ensure_ascii=False)}",
            f"- 按结论类型：{json.dumps(evidence['by_claim'], ensure_ascii=False)}",
            f"- 审计：{'已运行' if audit else '未运行'}",
            "",
            "## 边界",
            "",
            "本交付物不证明总体比例、市场规模或因果；证据强度不替代需求到特性、特性到产品的推导理由；可用性、工程性能、商业与安全结论分别有各自证据要求。",
        ]
    )
    filename = "user-ops" if kind == "ops" else kind
    path = out_dir / f"{filename}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "status": "written",
        "path": str(path),
        "kind": kind,
        "evidence_count": evidence["count"],
        "product_reasoning": product_reasoning_summary(reasoning),
    }


def doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        catalog = method_catalog()
        checks.append(("method-catalog", True, f"{len(catalog['methods'])} methods"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("method-catalog", False, str(exc)))
        catalog = {"methods": []}
    try:
        packs = domain_packs()
        checks.append(("domain-packs", len(packs) == 5, f"{len(packs)} domains"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("domain-packs", False, str(exc)))
        packs = {}
    try:
        platform_data = platform_catalog()
        platform_ids = {str(item.get("id")) for item in platform_data.get("platforms", [])}
        required = {"github", "reddit", "instagram", "amazon"}
        checks.append(
            (
                "platform-catalog",
                required.issubset(platform_ids),
                f"{len(platform_ids)} sources; missing {sorted(required - platform_ids) or 'none'}",
            )
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("platform-catalog", False, str(exc)))
    ids = {str(item.get("id")) for item in catalog.get("methods", []) if isinstance(item, dict)}
    missing: list[str] = []
    for name, pack in packs.items():
        for stage_name, stage in (pack.get("stages") or {}).items():
            for method_id in stage.get("methods", []):
                if method_id not in ids:
                    missing.append(f"{name}.{stage_name}:{method_id}")
    checks.append(("pack-method-refs", not missing, "; ".join(missing[:5]) or "all resolve"))
    try:
        registry = load_json(ASSETS / "open-source-connectors.json")
        expired = [
            str(item.get("id")) for item in registry.get("connectors", [])
            if isinstance(item, dict) and connector_review_expired(item)
        ]
        checks.append(("connector-policy-review", not expired, ", ".join(expired) or "all current"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("connector-policy-review", False, str(exc)))
    checks.append(("version", bool(VERSION and VERSION != "dev"), VERSION))
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}".rstrip())
    return 0 if all(ok for _, ok, _ in checks) else 1


# ---------------------------------------------------------------------------
# Platform radar, collection runtime, normalized analysis


def platform_catalog() -> dict[str, Any]:
    path = ASSETS / "platform-catalog.json"
    data = load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("platforms"), list):
        raise ValueError(f"invalid platform catalog: {path}")
    return data


def platform_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in platform_catalog()["platforms"] if isinstance(item, dict) and item.get("id")}


CLAIM_HINTS = {
    "need": ("需求", "痛点", "问题", "场景", "替代", "workaround", "为什么"),
    "acceptance": ("接受", "喜欢", "偏好", "概念", "方案", "包装", "外观"),
    "usability": ("可用性", "任务", "易用", "学习", "错误", "安装", "操作"),
    "performance": ("性能", "跑分", "续航", "信号", "发热", "耐久", "测试"),
    "commercial": ("购买", "付费", "价格", "定价", "复购", "留存", "退货", "销量"),
    "safety": ("安全", "风险", "误用", "认证", "合规", "事故"),
}


def infer_claim_types(text: str) -> list[str]:
    low = text.casefold()
    found = [claim for claim, keys in CLAIM_HINTS.items() if any(key in low for key in keys)]
    return found or ["need"]


def platform_fit(
    text: str,
    domain: str | None = None,
    claim_types: list[str] | None = None,
    require_bulk: bool = False,
) -> dict[str, Any]:
    claims = claim_types or infer_claim_types(text)
    ranked: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for platform in platform_index().values():
        domains = platform.get("domains", [])
        if domain and domain not in domains:
            continue
        claim_hits = [claim for claim in claims if claim in platform.get("claim_fit", [])]
        score = 1.0
        why: list[str] = []
        if domain in domains:
            score += 3
            why.append(f"覆盖 {domain}")
        if claim_hits:
            score += 2 * len(claim_hits)
            why.append("可支持 " + "/".join(claim_hits))
        low = text.casefold()
        platform_id = str(platform["id"])
        platform_name = str(platform.get("name", "")).casefold()
        if (len(platform_id) >= 3 and platform_id in low) or (len(platform_name) >= 3 and platform_name in low):
            score += 5
            why.append("需求直接点名")
        data_types = {str(item) for item in platform.get("data_types", [])}
        if any(word in low for word in ("评论", "抱怨", "吐槽", "评价")) and data_types.intersection(
            {"posts", "comments", "reviews", "answers", "notes", "stories", "tickets"}
        ):
            score += 2
            why.append("含评论/帖子类数据")
        if any(word in low for word in ("价格", "购买", "付费", "复购", "销量")) and data_types.intersection(
            {"reviews", "ratings", "sales_rank", "creator_insights"}
        ):
            score += 1
            why.append("含价格/交易信号")
        if "访谈" in low and platform["id"] in {"interviews", "support_tickets"}:
            score += 2
            why.append("第一方访谈/工单")
        if "问卷" in low and platform["id"] in {"surveys", "interviews"}:
            score += 2
            why.append("第一方问卷")
        bulk = platform.get("bulk", "no")
        if require_bulk:
            if bulk == "yes":
                score += 3
                why.append("支持批量")
            elif bulk == "limited":
                score += 1
                why.append("批量受限")
            else:
                score -= 2
                why.append("不适合批量")
        elif bulk == "yes":
            score += 1
        decision = platform.get("decision", "limited")
        if decision == "blocked":
            score -= 8
            why.append("无合规批量通道")
        elif decision == "limited":
            score -= 1
            why.append("需授权/受限")
        else:
            score += 1
        entry = {
            "id": platform["id"],
            "name": platform["name"],
            "decision": decision,
            "score": round(score, 1),
            "why": why,
            "access_modes": platform.get("access_modes", []),
            "auth": platform.get("auth", "none"),
            "bulk": bulk,
            "freshness": platform.get("freshness", "medium"),
            "limits": platform.get("limits", []),
            "bias": platform.get("bias", []),
            "adapter": platform.get("adapter", "none"),
            "cdp": bool(platform.get("cdp")),
            "notes": platform.get("notes", ""),
        }
        if decision == "blocked":
            blocked.append(entry)
        else:
            ranked.append(entry)
    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    if not ranked:
        blocked.sort(key=lambda item: item["name"])
    return {
        "query": text,
        "domain": domain,
        "claim_types": claims,
        "require_bulk": require_bulk,
        "recommended": ranked[:8],
        "blocked": blocked,
        "access_steps": [
            "优先官方 API / 授权导出 / 合规历史数据集；不做未授权抓取",
            "为每个平台记录访问依据、账号/应用、速率限制、保留与删除规则",
            "先跑小样与 pilot，确认字段、去重、偏差与边际新主题产出后再放量",
        ],
        "boundary": "平台可用不等于样本代表总体；平台选择必须记录选择偏差与覆盖缺口。",
    }


def platform_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Askovo 平台雷达",
        "",
        f"- 需求：{plan['query']}",
        f"- 领域：`{plan.get('domain') or '未限定'}`；结论类型：{', '.join(plan['claim_types'])}",
        f"- 批量要求：{'是' if plan['require_bulk'] else '否'}",
        "",
        "## 推荐平台",
        "",
        "| 平台 | 适配分 | 可用性 | 批量 | 适配原因 | 主要限制 |",
        "|---|---|---|---|---|---|",
    ]
    for item in plan["recommended"]:
        lines.append(
            f"| {item['name']} (`{item['id']}`) | {item['score']} | {item['decision']} | "
            f"{item['bulk']} | {'；'.join(item['why'])} | {'；'.join(item['limits'][:2])} |"
        )
    if plan.get("blocked"):
        lines.extend(["", "## 不可直接批量采集", ""])
        for item in plan["blocked"]:
            lines.append(f"- {item['name']}：{item['notes']}")
    lines.extend(["", "## 采集前", ""])
    lines.extend(f"- {item}" for item in plan.get("access_steps", []))
    lines.extend(["", "## 边界", "", plan.get("boundary", "")])
    return "\n".join(lines) + "\n"


def _run_id(platform: str, token: str | None = None) -> str:
    suffix = token or uuid.uuid4().hex[:6]
    return f"{platform}-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{suffix}"


def _hash_author(value: str) -> str:
    salt = os.environ.get("ASKOVO_AUTHOR_SALT")
    if not value or not salt:
        return ""
    digest = hmac.new(salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return "hmac-sha256:" + digest


def _normalize_platform_record(raw: dict[str, Any], platform: str, run_id: str, query: str) -> dict[str, Any]:
    text = str(raw.get("text") or raw.get("body") or raw.get("selftext") or raw.get("content") or "")
    title = str(raw.get("title") or "")
    if title and text and title not in text:
        text = title + "\n\n" + text
    record_id = str(raw.get("record_id") or raw.get("id") or hashlib.sha256(text.encode()).hexdigest()[:12])
    if not record_id.startswith(platform + ":"):
        record_id = f"{platform}:{record_id}"
    return {
        "record_id": record_id,
        "platform": platform,
        "source_url": str(raw.get("source_url") or raw.get("url") or raw.get("html_url") or ""),
        "author_hash": str(raw.get("author_hash") or _hash_author(str(raw.get("author") or ""))),
        "created_at": str(raw.get("created_at") or ""),
        "title": title,
        "text": text,
        "rating": raw.get("rating"),
        "context": str(raw.get("context") or ""),
        "query": query,
        "run_id": run_id,
        "collected_at": now(),
        "source_family": platform,
        "evidence_form": str(raw.get("evidence_form") or "self_report"),
        "claim_type": str(raw.get("claim_type") or "need"),
        "language": str(raw.get("language") or "unknown"),
        "normalized_text_hash": "sha256:" + hashlib.sha256((text or record_id).encode("utf-8")).hexdigest(),
    }


@contextmanager
def _locked_file(lock_path: Path):
    """Cross-process lock for append-only normalized/evidence files."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _write_run(
    study_dir: Path,
    platform: str,
    run_id: str,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    raw_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest = dict(manifest)
    source_rows = list(raw_records) if raw_records is not None else list(records)
    try:
        study = load_json(study_dir / "study.json")
    except (OSError, json.JSONDecodeError):
        study = {}
    manifest["study_id"] = str(manifest.get("study_id") or (study.get("study_id") if isinstance(study, dict) else "") or "")
    adapters = study.get("source_adapters", {}) if isinstance(study, dict) else {}
    adapter = adapters.get(platform, {}) if isinstance(adapters, dict) else {}
    if not isinstance(adapter, dict):
        adapter = {}
    for field_name in (
        "connector_id", "connector_repo", "connector_revision", "connector_license",
        "terms_reviewed_at", "data_rights_reviewed_at", "data_rights_basis", "retention_rule",
    ):
        manifest.setdefault(field_name, adapter.get(field_name) or "")
    if not manifest.get("data_rights_basis"):
        manifest["data_rights_basis"] = "See the approved study design; CLI does not verify platform terms"
    connector_id = str(manifest.get("connector_id") or "unknown")
    connector_revision = str(manifest.get("connector_revision") or "unknown")

    raw_dir = study_dir / "02-data" / "raw" / platform
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{run_id}.jsonl"
    manifest_path = study_dir / "01-sources" / "manifests" / f"{run_id}.json"
    if raw_path.exists() or manifest_path.exists():
        raise FileExistsError(f"collection run already exists: {run_id}")
    with raw_path.open("x", encoding="utf-8") as handle:
        for index, raw in enumerate(source_rows):
            normalized = records[index] if index < len(records) else {}
            text = str(raw.get("text") or raw.get("body") or raw.get("selftext") or raw.get("content") or normalized.get("text") or "")
            envelope = {
                "collection_run_id": run_id,
                "connector_id": connector_id,
                "connector_revision": connector_revision,
                "source_platform": platform,
                "source_record_id": str(raw.get("record_id") or raw.get("id") or normalized.get("record_id") or ""),
                "source_parent_id": raw.get("parent_id"),
                "source_url": str(raw.get("source_url") or raw.get("url") or raw.get("html_url") or normalized.get("source_url") or ""),
                "source_channel": str(raw.get("source_channel") or raw.get("subreddit") or ""),
                "source_content_type": str(raw.get("source_content_type") or raw.get("content_type") or "unknown"),
                "created_at": str(raw.get("created_at") or normalized.get("created_at") or ""),
                "collected_at": str(raw.get("collected_at") or now()),
                "content_status": str(raw.get("content_status") or "present"),
                "text": text,
                "source_fields": raw,
            }
            handle.write(json.dumps(envelope, ensure_ascii=False) + "\n")

    normalized_path = study_dir / "02-data" / "normalized.jsonl"
    added = 0
    dropped = {"duplicate_id": 0, "duplicate_text": 0, "id_conflicts": 0}
    conflicts: list[str] = []
    with _locked_file(normalized_path.with_suffix(".lock")):
        existing_ids: dict[str, str] = {}
        existing_hashes: set[str] = set()
        if normalized_path.is_file():
            for line in normalized_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict):
                    continue
                item_platform = str(item.get("platform") or item.get("source_family") or "unknown")
                item_id = str(item.get("record_id") or "")
                item_hash = str(item.get("normalized_text_hash") or "")
                if item_id:
                    existing_ids[f"{item_platform}:{item_id}"] = item_hash
                if item_hash:
                    existing_hashes.add(f"{item_platform}:{item_hash}")
        with normalized_path.open("a", encoding="utf-8") as handle:
            for record in records:
                record_id = str(record["record_id"])
                text_hash = str(record.get("normalized_text_hash") or "")
                id_key = f"{platform}:{record_id}"
                hash_key = f"{platform}:{text_hash}"
                if id_key in existing_ids:
                    if existing_ids[id_key] != text_hash:
                        dropped["id_conflicts"] += 1
                        conflicts.append(record_id)
                    else:
                        dropped["duplicate_id"] += 1
                    continue
                if text_hash and hash_key in existing_hashes:
                    dropped["duplicate_text"] += 1
                    continue
                record["collection_run_id"] = run_id
                record["connector_id"] = connector_id
                record["connector_revision"] = connector_revision
                record["source_ref"] = str(record.get("source_ref") or record.get("source_url") or "")
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing_ids[id_key] = text_hash
                if text_hash:
                    existing_hashes.add(hash_key)
                added += 1

    requested = manifest.get("requested_records", manifest.get("requested", 0))
    for legacy_name in ("requested", "reached", "written"):
        manifest.pop(legacy_name, None)
    previous_dropped = manifest.get("blocked_or_dropped", {})
    blocked_or_dropped = dict(previous_dropped) if isinstance(previous_dropped, dict) else {}
    blocked_or_dropped.update(dropped)
    warnings = list(manifest.get("warnings") or [])
    if conflicts:
        warnings.append("same platform record id with different content: " + ", ".join(conflicts[:20]))
    manifest.update({
        "collection_run_id": run_id,
        "run_id": run_id,
        "requested_records": requested,
        "reached_records": len(source_rows),
        "written_records": added,
        "blocked_or_dropped": blocked_or_dropped,
        "warnings": warnings,
        "stop_reason": manifest.get("stop_reason") or "completed",
        "requested_at": manifest.get("requested_at") or manifest.get("started_at") or now(),
        "completed_at": now(),
        "raw_file": str(raw_path),
    })
    manifest_dir = study_dir / "01-sources" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {
        "run_id": run_id,
        "raw_file": str(raw_path),
        "normalized_added": added,
        "id_conflicts": dropped["id_conflicts"],
        "manifest": str(manifest_path),
    }


def _collect_github(query: str, limit: int, kind: str = "issues") -> list[dict[str, Any]]:
    token = __import__("os").environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "askovo/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = "issues" if kind == "issues" else "repositories"
    records: list[dict[str, Any]] = []
    page = 1
    while len(records) < limit and page <= 10:
        per_page = min(100, limit - len(records))
        params = urllib.parse.urlencode({"q": query, "per_page": per_page, "page": page, "sort": "created", "order": "desc"})
        url = f"https://api.github.com/search/{endpoint}?{params}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise RuntimeError("GitHub rate limit or permission denied; set GITHUB_TOKEN or reduce request volume") from exc
            raise
        items = payload.get("items", [])
        if not items:
            break
        for item in items:
            records.append(
                {
                    "id": f"github:{item.get('id')}",
                    "title": item.get("title") or item.get("full_name") or "",
                    "text": item.get("body") or item.get("description") or "",
                    "url": item.get("html_url") or "",
                    "author": (item.get("user") or {}).get("login") or (item.get("owner") or {}).get("login") or "",
                    "created_at": item.get("created_at") or "",
                    "context": item.get("repository_url") or item.get("full_name") or "",
                    "claim_type": "need",
                    "evidence_form": "self_report",
                }
            )
            if len(records) >= limit:
                break
        page += 1
    return records


def _collect_reddit(query: str, limit: int) -> list[dict[str, Any]]:
    import base64
    import os

    client_id = os.environ.get("ASKOVO_REDDIT_CLIENT_ID")
    client_secret = os.environ.get("ASKOVO_REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("ASKOVO_REDDIT_USER_AGENT", "askovo/2.0")
    if not client_id or not client_secret:
        raise RuntimeError("Reddit requires ASKOVO_REDDIT_CLIENT_ID and ASKOVO_REDDIT_CLIENT_SECRET (approved Data API app)")
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_request = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {auth}", "User-Agent": user_agent},
    )
    with urllib.request.urlopen(token_request, timeout=30) as response:
        token = json.loads(response.read().decode()).get("access_token")
    if not token:
        raise RuntimeError("Reddit token request returned no access_token")
    records: list[dict[str, Any]] = []
    after = ""
    while len(records) < limit:
        params = {"q": query, "limit": min(100, limit - len(records)), "sort": "relevance", "t": "year", "raw_json": 1}
        if after:
            params["after"] = after
        request = urllib.request.Request(
            "https://oauth.reddit.com/search?" + urllib.parse.urlencode(params),
            headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
        children = (payload.get("data") or {}).get("children") or []
        if not children:
            break
        for child in children:
            item = child.get("data") or {}
            records.append(
                {
                    "id": f"reddit:{item.get('id')}",
                    "title": item.get("title") or "",
                    "text": item.get("selftext") or "",
                    "url": "https://www.reddit.com" + str(item.get("permalink") or ""),
                    "author": item.get("author") or "",
                    "created_at": datetime.fromtimestamp(float(item.get("created_utc") or 0), tz=timezone.utc).isoformat() if item.get("created_utc") else "",
                    "context": item.get("subreddit") or "",
                    "claim_type": "need",
                    "evidence_form": "self_report",
                }
            )
            if len(records) >= limit:
                break
        after = (payload.get("data") or {}).get("after") or ""
        if not after:
            break
    return records


# ---------------------------------------------------------------------------
# CDP transport: authorized visible pages only. No challenge bypass.


CDP_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
CDP_TARGET_HOSTS = {
    "amazon": ("amazon.com", "amazon.ca", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.co.jp"),
    "instagram": ("instagram.com",),
    "bilibili": ("bilibili.com",),
    "weibo": ("weibo.com", "weibo.cn"),
}
MAX_CDP_HANDSHAKE_BYTES = 64 * 1024
MAX_CDP_MESSAGE_BYTES = 16 * 1024 * 1024


def _validate_cdp_base(cdp_base: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(cdp_base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in CDP_LOOPBACK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("CDP endpoint must be a plain http:// loopback URL")
    return parsed.hostname or "127.0.0.1", parsed.port or 80


def _validate_cdp_target(platform: str, url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = CDP_TARGET_HOSTS.get(platform, ())
    host_matches = any(host == domain or host.endswith("." + domain) for domain in allowed)
    default_port = 443 if parsed.scheme == "https" else 80
    if (
        parsed.scheme not in {"http", "https"}
        or not host_matches
        or parsed.username
        or parsed.password
        or parsed.port not in (None, default_port)
    ):
        raise ValueError(f"CDP target must be a default-port HTTP(S) URL on an approved {platform} host")


def _validate_cdp_ws_url(url: str, expected_port: int | None = None) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "ws" or parsed.hostname not in CDP_LOOPBACK_HOSTS or parsed.username or parsed.password:
        raise ValueError("CDP websocket must be a ws:// loopback URL")
    if expected_port is not None and (parsed.port or 80) != expected_port:
        raise ValueError("CDP websocket must stay on the approved loopback port")


class _WebSocket:
    """Minimal RFC6455 client for Chrome DevTools Protocol (ws:// only)."""

    def __init__(self, url: str, timeout: float = 30):
        _validate_cdp_ws_url(url)
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP websocket handshake closed")
            response += chunk
            if len(response) > MAX_CDP_HANDSHAKE_BYTES:
                raise ConnectionError("CDP websocket handshake is too large")
        header_block = response.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
        lines = header_block.split("\r\n")
        if " 101 " not in lines[0]:
            raise ConnectionError(f"CDP websocket handshake failed: {lines[0]}")
        headers = {}
        for line in lines[1:]:
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise ConnectionError("CDP websocket handshake has an invalid accept signature")

    def _read_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("CDP websocket closed")
            data += chunk
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        buffer = bytearray()
        while True:
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > MAX_CDP_MESSAGE_BYTES or len(buffer) + length > MAX_CDP_MESSAGE_BYTES:
                raise ConnectionError("CDP websocket message is too large")
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("CDP websocket closed by peer")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode in (0x1, 0x2):
                buffer = bytearray(payload)
            elif opcode == 0x0:
                buffer.extend(payload)
            else:
                continue
            if fin:
                return bytes(buffer).decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        finally:
            try:
                self.sock.close()
            except OSError:
                pass


class CDPClient:
    def __init__(self, ws: _WebSocket):
        self.ws = ws
        self.next_id = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        self.ws.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv_text())
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result") or {}

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return (result.get("result") or {}).get("value")

    def close(self) -> None:
        self.ws.close()


def _read_limited_json(response: Any) -> Any:
    payload = response.read(MAX_CDP_MESSAGE_BYTES + 1)
    if len(payload) > MAX_CDP_MESSAGE_BYTES:
        raise RuntimeError("CDP response is too large")
    return json.loads(payload.decode("utf-8"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_CDP_OPENER = urllib.request.build_opener(_NoRedirect)


def cdp_new_page(cdp_base: str, url: str) -> str:
    _, expected_port = _validate_cdp_base(cdp_base)
    base = cdp_base.rstrip("/")
    target = f"{base}/json/new?{urllib.parse.quote(url, safe='')}"
    request = urllib.request.Request(target, method="PUT")
    try:
        with _CDP_OPENER.open(request, timeout=15) as response:
            payload = _read_limited_json(response)
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 405):
            exc.close()
            raise
        exc.close()
        with _CDP_OPENER.open(target, timeout=15) as response:
            payload = _read_limited_json(response)
    ws_url = payload.get("webSocketDebuggerUrl") if isinstance(payload, dict) else None
    if not ws_url:
        raise RuntimeError("CDP did not return a page websocket URL")
    _validate_cdp_ws_url(str(ws_url), expected_port)
    return str(ws_url)


CDP_EXTRACTOR = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const bodyText = clean(document.body ? document.body.innerText : "");
  if (/Robot Check|Enter the characters|验证码|异常流量|not a robot/i.test(bodyText)) {
    return {error: "challenge_page"};
  }
  const reviews = Array.from(document.querySelectorAll('[data-hook="review"], article, [role="article"], .review'));
  const rows = [];
  for (const node of reviews) {
    const pick = (sel) => clean((node.querySelector(sel) || {}).innerText || "");
    const title = pick('[data-hook="review-title"]') || pick("h2, h3") || "";
    const body = pick('[data-hook="review-body"]') || pick("p") || "";
    const text = clean([title, body].filter(Boolean).join("\n"));
    if (text.length < 35) continue;
    const rating = pick('[data-hook="review-star-rating"]') || pick('[class*="a-icon-alt"]') || "";
    const date = pick('[data-hook="review-date"]') || pick("time") || "";
    const author = pick('.a-profile-name') || pick('[data-hook="review-author"]') || "";
    const link = node.querySelector('a[href*="/review"], a[href*="/product-reviews"], a[href]');
    rows.push({
      title: title,
      text: text,
      rating: rating,
      created_at: date,
      author: author,
      source_url: link ? new URL(link.getAttribute("href"), location.href).href : location.href,
      page_url: location.href
    });
  }
  if (!rows.length && bodyText.length > 80) {
    rows.push({title: document.title, text: bodyText.slice(0, 8000), rating: "", created_at: "", author: "", source_url: location.href, page_url: location.href});
  }
  return {rows: rows, page_title: document.title};
})()
"""


def collect_cdp(
    study_dir: Path,
    platform: str,
    query: str,
    url: str,
    cdp_base: str,
    ack_terms: bool,
    limit: int = 50,
    scrolls: int = 5,
    wait_seconds: float = 2.5,
    run_id: str | None = None,
    lease_valid: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if not ack_terms:
        return {
            "status": "terms_required",
            "platform": platform,
            "reason": "CDP visible-page collection needs explicit --ack-terms and an authorized session",
        }
    entry = platform_index().get(platform)
    if not entry or not entry.get("cdp"):
        return {
            "status": "cdp_not_allowed",
            "platform": platform,
            "reason": "CDP is only enabled for authorized visible pages on amazon/instagram/bilibili/weibo",
        }
    if not url:
        return {"status": "error", "platform": platform, "reason": "CDP requires --url"}
    _validate_cdp_target(platform, url)
    if lease_valid is not None and not lease_valid():
        return {"status": "lease_lost", "platform": platform, "reason": "queue lease is no longer owned by this worker"}
    ws_url = cdp_new_page(cdp_base, url)
    client = CDPClient(_WebSocket(ws_url))
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    try:
        client.call("Runtime.enable")
        time.sleep(max(0.5, wait_seconds))
        for _ in range(max(0, scrolls) + 1):
            value = client.evaluate(CDP_EXTRACTOR)
            if isinstance(value, dict) and value.get("error") == "challenge_page":
                return {
                    "status": "challenge",
                    "platform": platform,
                    "reason": "page shows a challenge/robot check; stop and use an authorized export instead",
                }
            if isinstance(value, dict) and isinstance(value.get("rows"), list):
                for row in value["rows"]:
                    key = hashlib.sha256(
                        (str(row.get("source_url", "")) + str(row.get("text", ""))[:500]).encode()
                    ).hexdigest()
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    rows.append(row)
                    if len(rows) >= limit:
                        break
            if len(rows) >= limit:
                break
            client.evaluate("window.scrollBy(0, Math.max(700, Math.floor(window.innerHeight * 0.85)))")
            time.sleep(max(0.4, wait_seconds / 2))
    finally:
        client.close()
    raw_records = [
        {
            "id": f"{platform}:{hashlib.sha256((row.get('source_url','') + row.get('text','')[:500]).encode()).hexdigest()[:16]}",
            "title": row.get("title") or "",
            "text": row.get("text") or "",
            "url": row.get("source_url") or url,
            "author": row.get("author") or "",
            "created_at": row.get("created_at") or "",
            "context": "cdp_visible_page",
            "rating": row.get("rating") or "",
            "claim_type": "need",
            "evidence_form": "self_report",
        }
        for row in rows[:limit]
    ]
    if lease_valid is not None and not lease_valid():
        return {"status": "lease_lost", "platform": platform, "reason": "queue lease is no longer owned by this worker"}
    run_id = run_id or _run_id(platform)
    normalized = [_normalize_platform_record(raw, platform, run_id, query) for raw in raw_records]
    manifest = {
        "platform": platform,
        "query": query,
        "route_id": query,
        "limit": limit,
        "adapter": "cdp",
        "connector_id": "cdp-authorized-visible-page",
        "connector_revision": VERSION,
        "connector_license": "MIT",
        "access_basis": "cdp_authorized_visible_page",
        "auth": "user_browser_session",
        "started_at": now(),
        "finished_at": now(),
        "requested": limit,
        "source_url": url,
        "cdp_base": cdp_base,
        "limits": entry.get("limits", []),
        "bias": entry.get("bias", []),
        "terms_note": "visible page text only; no challenge bypass; platform terms may still restrict collection",
    }
    written = _write_run(study_dir, platform, run_id, normalized, manifest, raw_records)
    return {"status": "collected", "platform": platform, "transport": "cdp", "records": len(normalized), **written}


def collect_platform(
    study_dir: Path,
    platform: str,
    query: str,
    limit: int = 100,
    dry_run: bool = False,
    fixture: Path | None = None,
    run_id: str | None = None,
    cdp_url: str | None = None,
    url: str | None = None,
    ack_terms: bool = False,
    lease_valid: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    study_dir = study_dir.resolve()
    if not (study_dir / "study.json").is_file():
        raise ValueError(f"missing study.json under {study_dir}; run `askovo do` first")
    platforms = platform_index()
    if platform not in platforms:
        raise ValueError(f"unknown platform {platform!r}; choose from: {', '.join(sorted(platforms))}")
    entry = platforms[platform]
    if entry.get("decision") == "blocked" and not fixture:
        return {
            "status": "blocked",
            "platform": platform,
            "reason": entry.get("notes", "blocked by platform policy"),
            "alternatives": [item["id"] for item in platform_index().values() if item.get("decision") == "supported"][:5],
        }
    run_id = run_id or _run_id(platform)
    plan = {
        "platform": platform,
        "query": query,
        "limit": limit,
        "adapter": entry.get("adapter", "none"),
        "access_modes": entry.get("access_modes", []),
        "auth": entry.get("auth", "none"),
        "decision": entry.get("decision"),
        "run_id": run_id,
        "dry_run": dry_run,
    }
    if cdp_url:
        plan["transport"] = "cdp"
        plan["adapter"] = "cdp"
        plan["url"] = url
        plan["ack_terms"] = ack_terms
    if dry_run:
        return {"status": "planned", **plan, "next": f"askovo collect {study_dir} --platform {platform} --query {query!r} --limit {limit}"}
    if platform_review_expired(platform):
        return {
            "status": "review_expired",
            "platform": platform,
            "reason": "connector policy review is expired; re-review the registry before collection",
        }
    study = load_json(study_dir / "study.json")
    scope = study.get("scope", {}) if isinstance(study, dict) else {}
    allowed_sources = scope.get("allowed_sources", []) if isinstance(scope, dict) else []
    if not isinstance(allowed_sources, list) or platform not in allowed_sources:
        return {
            "status": "scope_blocked",
            "platform": platform,
            "reason": "platform is not listed in study.scope.allowed_sources",
        }
    adapters = study.get("source_adapters", {}) if isinstance(study, dict) else {}
    adapter = adapters.get(platform) if isinstance(adapters, dict) else None
    adapter_disabled = not isinstance(adapter, dict) or not adapter.get("enabled", False)
    if adapter_disabled and (fixture is None or adapter is not None):
        return {
            "status": "adapter_disabled",
            "platform": platform,
            "reason": "live collection requires an enabled platform adapter in study.json",
        }
    if lease_valid is not None and not lease_valid():
        return {"status": "lease_lost", "platform": platform, "reason": "queue lease is no longer owned by this worker"}
    if cdp_url:
        return collect_cdp(
            study_dir, platform, query, url or "", cdp_url, ack_terms, limit,
            run_id=run_id, lease_valid=lease_valid,
        )
    if fixture:
        raw_records: list[dict[str, Any]] = []
        suffix = fixture.suffix.lower()
        if suffix == ".jsonl":
            for line in fixture.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    raw_records.append(json.loads(line))
        elif suffix == ".csv":
            with fixture.open(encoding="utf-8-sig", newline="") as handle:
                raw_records.extend(dict(row) for row in csv.DictReader(handle))
        else:
            raw_records.append({"text": fixture.read_text(encoding="utf-8", errors="ignore")})
    elif entry.get("adapter") == "github":
        try:
            raw_records = _collect_github(query, limit)
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "platform": platform, "reason": str(exc)}
    elif entry.get("adapter") == "reddit":
        try:
            raw_records = _collect_reddit(query, limit)
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "platform": platform, "reason": str(exc)}
    else:
        return {
            "status": "adapter_unavailable",
            "platform": platform,
            "reason": f"{entry.get('name')} has no bundled collector; use an authorized export/local dataset",
            "access_modes": entry.get("access_modes", []),
            "next": f"askovo import {study_dir} <export.jsonl> --source-family {platform}",
        }
    for index, raw in enumerate(raw_records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"fixture record {index} must be a JSON object")
    if lease_valid is not None and not lease_valid():
        return {"status": "lease_lost", "platform": platform, "reason": "queue lease is no longer owned by this worker"}
    normalized = [_normalize_platform_record(raw, platform, run_id, query) for raw in raw_records[:limit]]
    adapter_config = adapter if isinstance(adapter, dict) else {}
    manifest = {
        "platform": platform,
        "query": query,
        "route_id": query,
        "limit": limit,
        "adapter": entry.get("adapter"),
        "connector_id": "authorized-export" if fixture else adapter_config.get("connector_id") or entry.get("adapter"),
        "connector_revision": "local" if fixture else adapter_config.get("connector_revision") or VERSION,
        "connector_license": "" if fixture else adapter_config.get("connector_license") or "MIT",
        "access_basis": "authorized_export" if fixture else ", ".join(entry.get("access_modes", [])),
        "auth": entry.get("auth"),
        "started_at": now(),
        "finished_at": now(),
        "requested": limit,
        "limits": entry.get("limits", []),
        "bias": entry.get("bias", []),
    }
    written = _write_run(study_dir, platform, run_id, normalized, manifest, raw_records[:limit])
    return {"status": "collected", "platform": platform, "records": len(normalized), **written}


def analyze_study(study_dir: Path, question: str | None = None) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    records: list[dict[str, Any]] = []
    invalid_records = 0
    for name in ("02-data/normalized.jsonl", "02-data/evidence.jsonl"):
        path = study_dir / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                invalid_records += 1
                continue
            if isinstance(item, dict):
                records.append(item)
            else:
                invalid_records += 1
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        platform = str(record.get("platform") or record.get("source_family") or "unknown")
        record_id = str(record.get("record_id") or "")
        text_hash = str(record.get("normalized_text_hash") or record.get("text_hash") or "")
        id_key = f"{platform}:{record_id}"
        hash_key = f"{platform}:{text_hash}"
        if (record_id and id_key in seen_ids) or (text_hash and hash_key in seen_hashes):
            continue
        if record_id:
            seen_ids.add(id_key)
        if text_hash:
            seen_hashes.add(hash_key)
        unique.append(record)
    by_platform: dict[str, int] = {}
    by_claim: dict[str, int] = {}
    by_month: dict[str, int] = {}
    by_form: dict[str, int] = {}
    lengths: list[int] = []
    text_blob: list[str] = []
    for record in unique:
        platform = str(record.get("platform") or record.get("source_family") or "unknown")
        claim = str(record.get("claim_type") or "unknown")
        form = str(record.get("evidence_form") or "unknown")
        by_platform[platform] = by_platform.get(platform, 0) + 1
        by_claim[claim] = by_claim.get(claim, 0) + 1
        by_form[form] = by_form.get(form, 0) + 1
        created = str(record.get("created_at") or "")
        if len(created) >= 7:
            month = created[:7]
            by_month[month] = by_month.get(month, 0) + 1
        text = str(record.get("text") or "")
        lengths.append(len(text))
        text_blob.append(text)
    stop = set("the and for with that this from are was were you your our not but have has had will can could should about into over under more most some such than then them they their there here what when where which who whom why how all any both each few other own same so too very just also".split())
    tokens: dict[str, int] = {}
    for text in text_blob:
        for token in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", text.lower()):
            if token in stop:
                continue
            tokens[token] = tokens.get(token, 0) + 1
    top_terms = sorted(tokens.items(), key=lambda item: (-item[1], item[0]))[:30]
    matches = []
    if question:
        q_terms = [t for t in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", question.lower()) if t not in stop]
        for record in unique:
            text = str(record.get("text") or "").lower()
            hit = [term for term in q_terms if term in text]
            if hit:
                matches.append({"record_id": record.get("record_id"), "platform": record.get("platform"), "hits": hit, "excerpt": str(record.get("text") or "")[:300]})
        matches.sort(key=lambda item: (-len(item["hits"]), str(item["record_id"])))
    analysis = {
        "generated_at": now(),
        "question": question,
        "records": len(unique),
        "invalid_records": invalid_records,
        "by_platform": by_platform,
        "by_claim_type": by_claim,
        "by_evidence_form": by_form,
        "by_month": dict(sorted(by_month.items())),
        "avg_text_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "top_terms": [{"term": term, "count": count} for term, count in top_terms],
        "question_matches": matches[:50],
        "boundary": "描述性统计，不证明总体比例、因果或需求强度；跨平台去重与抽样偏差需人工复核。",
    }
    out_dir = study_dir / "04-findings"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 跨平台分析",
        "",
        f"- 记录数：{analysis['records']}",
        f"- 平台分布：{json.dumps(by_platform, ensure_ascii=False)}",
        f"- 结论类型：{json.dumps(by_claim, ensure_ascii=False)}",
        f"- 证据形式：{json.dumps(by_form, ensure_ascii=False)}",
        f"- 平均文本长度：{analysis['avg_text_length']}",
        "",
        "## 高频词（候选主题，不是结论）",
        "",
    ]
    lines.extend(f"- {item['term']}：{item['count']}" for item in analysis["top_terms"][:20])
    if question:
        lines.extend(["", "## 与问题的匹配片段", ""])
        for item in matches[:10]:
            lines.append(f"- `{item['record_id']}`（{item['platform']}）：{item['excerpt']}")
    lines.extend(["", "## 边界", "", analysis["boundary"]])
    (out_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "analyzed", "analysis": str(out_dir / "analysis.json"), "markdown": str(out_dir / "analysis.md"), "records": len(unique)}


def cli_platforms(args: Any) -> int:
    domain = args.domain
    inferred = None
    if not domain:
        info = detect_domain(args.need)
        if info.get("domain"):
            domain = info["domain"]
            inferred = {"domain": domain, "label": info.get("label"), "confidence": info.get("confidence")}
    plan = platform_fit(args.need, domain, getattr(args, "claim_type", None), getattr(args, "bulk", False))
    if inferred:
        plan["inferred_domain"] = inferred
    if getattr(args, "json", False):
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(platform_markdown(plan))
    return 0


def cli_collect(args: Any) -> int:
    try:
        result = collect_platform(
            Path(args.study_dir),
            args.platform,
            args.query,
            limit=args.limit,
            dry_run=args.dry_run,
            fixture=Path(args.fixture) if args.fixture else None,
            cdp_url=args.cdp_url,
            url=args.url,
            ack_terms=args.ack_terms,
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError, ConnectionError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result.get("status")
    if status == "terms_required":
        return 4
    if status == "cdp_not_allowed":
        return 4
    if status in ("blocked", "adapter_unavailable", "adapter_disabled", "scope_blocked", "review_expired", "lease_lost", "error", "challenge"):
        return 3
    return 0


def cli_analyze(args: Any) -> int:
    try:
        result = analyze_study(Path(args.study_dir), args.question)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Durable collection queue: SQLite leases, workers, retry, rate limits


QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    query TEXT NOT NULL,
    limit_n INTEGER NOT NULL DEFAULT 100,
    fixture TEXT,
    cdp_url TEXT,
    url TEXT,
    ack_terms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_at REAL NOT NULL DEFAULT 0,
    lease_until REAL NOT NULL DEFAULT 0,
    worker_id TEXT,
    last_error TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status_next ON jobs(status, next_at);
CREATE TABLE IF NOT EXISTS rate_state (
    platform TEXT PRIMARY KEY,
    next_at REAL NOT NULL DEFAULT 0
);
"""


class QueueStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(QUEUE_SCHEMA)

    def add(
        self,
        platform: str,
        query: str,
        limit: int = 100,
        fixture: Path | None = None,
        cdp_url: str | None = None,
        url: str | None = None,
        ack_terms: bool = False,
        max_attempts: int = 3,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        stamp = now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, platform, query, limit_n, fixture, cdp_url, url, ack_terms, max_attempts, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id, platform, query, limit,
                    str(fixture) if fixture else None,
                    cdp_url, url, 1 if ack_terms else 0, max_attempts, stamp, stamp,
                ),
            )
        return job_id

    def lease(self, worker_id: str, lease_seconds: float = 300) -> dict[str, Any] | None:
        now_ts = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE "
                    "(status IN ('pending','retry') AND next_at <= ?) "
                    "OR (status = 'running' AND lease_until < ?) "
                    "ORDER BY created_at LIMIT 1",
                    (now_ts, now_ts),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                conn.execute(
                    "UPDATE jobs SET status='running', worker_id=?, lease_until=?, attempts=attempts+1, updated_at=? WHERE id=?",
                    (worker_id, now_ts + lease_seconds, now(), row["id"]),
                )
                conn.execute("COMMIT")
                result = dict(row)
                result["attempts"] = int(result["attempts"]) + 1
                return result
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def renew(self, job_id: str, worker_id: str, lease_seconds: float) -> bool:
        now_ts = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_until=?, updated_at=? "
                "WHERE id=? AND status='running' AND worker_id=? AND lease_until>?",
                (now_ts + lease_seconds, now(), job_id, worker_id, now_ts),
            )
            return cursor.rowcount == 1

    def complete(self, job_id: str, records: int, worker_id: str) -> bool:
        now_ts = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='done', record_count=?, lease_until=0, worker_id=NULL, updated_at=? "
                "WHERE id=? AND status='running' AND worker_id=? AND lease_until>?",
                (records, now(), job_id, worker_id, now_ts),
            )
            return cursor.rowcount == 1

    def fail(self, job_id: str, error: str, attempts: int, worker_id: str, max_attempts: int = 3) -> bool:
        stamp = now()
        now_ts = time.time()
        with self._connect() as conn:
            if attempts >= max_attempts:
                cursor = conn.execute(
                    "UPDATE jobs SET status='failed', last_error=?, lease_until=0, worker_id=NULL, updated_at=? "
                    "WHERE id=? AND status='running' AND worker_id=? AND lease_until>?",
                    (error[:2000], stamp, job_id, worker_id, now_ts),
                )
            else:
                delay = min(300, 5 * (2 ** max(0, attempts - 1)))
                cursor = conn.execute(
                    "UPDATE jobs SET status='retry', last_error=?, next_at=?, lease_until=0, worker_id=NULL, updated_at=? "
                    "WHERE id=? AND status='running' AND worker_id=? AND lease_until>?",
                    (error[:2000], now_ts + delay, stamp, job_id, worker_id, now_ts),
                )
            return cursor.rowcount == 1

    def retry_failed(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='pending', attempts=0, next_at=0, last_error=NULL, updated_at=? WHERE status='failed'",
                (now(),),
            )
            return int(cursor.rowcount or 0)

    def acquire_rate(self, platform: str, min_interval: float) -> float:
        if min_interval <= 0:
            return 0.0
        now_ts = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT next_at FROM rate_state WHERE platform=?", (platform,)).fetchone()
                slot = now_ts if row is None else max(now_ts, float(row["next_at"]))
                wait = slot - now_ts
                if row is None:
                    conn.execute(
                        "INSERT INTO rate_state (platform, next_at) VALUES (?, ?)",
                        (platform, slot + min_interval),
                    )
                else:
                    conn.execute(
                        "UPDATE rate_state SET next_at=? WHERE platform=?",
                        (slot + min_interval, platform),
                    )
                conn.execute("COMMIT")
                return wait
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def has_work(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('pending','retry','running')"
            ).fetchone()
            return bool(row and row["n"])

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, platform, COUNT(*) AS n, SUM(record_count) AS records FROM jobs GROUP BY status, platform ORDER BY status, platform"
            ).fetchall()
            recent = conn.execute(
                "SELECT id, platform, status, attempts, last_error, updated_at FROM jobs WHERE last_error IS NOT NULL ORDER BY updated_at DESC LIMIT 5"
            ).fetchall()
        return {
            "db": str(self.db_path),
            "counts": [dict(row) for row in rows],
            "recent_errors": [dict(row) for row in recent],
            "has_work": self.has_work(),
        }


DEFAULT_RATE_SECONDS = {"github": 6.0, "reddit": 2.0}


def _rate_for(platform: str, override: float | None) -> float:
    if override is not None:
        return override
    return DEFAULT_RATE_SECONDS.get(platform, 5.0)


def run_queue(
    study_dir: Path,
    workers: int = 2,
    min_interval: float | None = None,
    lease_seconds: float = 300,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if not math.isfinite(lease_seconds) or lease_seconds <= 0:
        raise ValueError("lease_seconds must be a positive finite number")
    if min_interval is not None and (not math.isfinite(min_interval) or min_interval < 0):
        raise ValueError("min_interval must be a non-negative finite number")
    study_dir = study_dir.resolve()
    store = QueueStore(study_dir / "01-sources" / "queue.db")
    store.init()
    summary = {"workers": workers, "leased": 0, "done": 0, "failed": 0, "records": 0}
    lock = threading.Lock()

    def worker(worker_id: str) -> None:
        while True:
            job = store.lease(worker_id, lease_seconds)
            if job is None:
                if not store.has_work():
                    return
                time.sleep(0.5)
                continue
            with lock:
                summary["leased"] += 1
            stop_heartbeat = threading.Event()
            lease_lost = threading.Event()

            def heartbeat() -> None:
                while not stop_heartbeat.wait(max(0.1, lease_seconds / 3)):
                    try:
                        if not store.renew(job["id"], worker_id, lease_seconds):
                            lease_lost.set()
                            return
                    except sqlite3.Error:
                        lease_lost.set()
                        return

            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            heartbeat_thread.start()
            try:
                wait = store.acquire_rate(job["platform"], _rate_for(job["platform"], min_interval))
                if wait > 0:
                    time.sleep(wait)
                if lease_lost.is_set():
                    return
                result = collect_platform(
                    study_dir,
                    job["platform"],
                    job["query"],
                    limit=int(job["limit_n"]),
                    fixture=Path(job["fixture"]) if job["fixture"] else None,
                    run_id=f"job-{job['id']}-attempt-{job['attempts']}",
                    cdp_url=job["cdp_url"],
                    url=job["url"],
                    ack_terms=bool(job["ack_terms"]),
                    lease_valid=lambda: not lease_lost.is_set(),
                )
                status = result.get("status")
                if status == "lease_lost":
                    return
                if status == "collected":
                    records = int(result.get("records", 0))
                    if store.complete(job["id"], records, worker_id):
                        with lock:
                            summary["done"] += 1
                            summary["records"] += records
                else:
                    recorded = store.fail(
                        job["id"], json.dumps(result, ensure_ascii=False), int(job["attempts"]),
                        worker_id, int(job["max_attempts"]),
                    )
                    if recorded:
                        with lock:
                            summary["failed"] += 1
            except Exception as exc:  # keep the queue alive; record the failure
                recorded = store.fail(
                    job["id"], f"{type(exc).__name__}: {exc}", int(job["attempts"]),
                    worker_id, int(job["max_attempts"]),
                )
                if recorded:
                    with lock:
                        summary["failed"] += 1
            finally:
                stop_heartbeat.set()
                heartbeat_thread.join(timeout=1)

    run_id = uuid.uuid4().hex[:12]
    threads = [
        threading.Thread(target=worker, args=(f"{run_id}-worker-{index+1}",), daemon=False)
        for index in range(max(1, workers))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    summary["status"] = store.status()
    return summary


def queue_add(
    study_dir: Path,
    platform: str,
    query: str,
    limit: int = 100,
    fixture: Path | None = None,
    cdp_url: str | None = None,
    url: str | None = None,
    ack_terms: bool = False,
    max_attempts: int = 3,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    store = QueueStore(study_dir.resolve() / "01-sources" / "queue.db")
    store.init()
    job_id = store.add(platform, query, limit, fixture, cdp_url, url, ack_terms, max_attempts)
    return {"status": "queued", "job_id": job_id, "db": str(store.db_path)}


def cli_queue_init(args: Any) -> int:
    store = QueueStore(Path(args.study_dir).resolve() / "01-sources" / "queue.db")
    store.init()
    print(json.dumps({"status": "initialized", "db": str(store.db_path)}, ensure_ascii=False, indent=2))
    return 0


def cli_queue_add(args: Any) -> int:
    try:
        result = queue_add(
            Path(args.study_dir),
            args.platform,
            args.query,
            limit=args.limit,
            fixture=Path(args.fixture) if args.fixture else None,
            cdp_url=args.cdp_url,
            url=args.url,
            ack_terms=args.ack_terms,
            max_attempts=args.max_attempts,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_queue_run(args: Any) -> int:
    try:
        summary = run_queue(
            Path(args.study_dir),
            workers=args.workers,
            min_interval=args.min_interval,
            lease_seconds=args.lease_seconds,
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


def cli_queue_status(args: Any) -> int:
    store = QueueStore(Path(args.study_dir).resolve() / "01-sources" / "queue.db")
    if not store.db_path.is_file():
        print(f"queue not found: {store.db_path}; run `askovo queue init` first", file=sys.stderr)
        return 2
    store.init()
    print(json.dumps(store.status(), ensure_ascii=False, indent=2))
    return 0


def cli_queue_retry(args: Any) -> int:
    store = QueueStore(Path(args.study_dir).resolve() / "01-sources" / "queue.db")
    if not store.db_path.is_file():
        print(f"queue not found: {store.db_path}", file=sys.stderr)
        return 2
    store.init()
    count = store.retry_failed()
    print(json.dumps({"status": "retried", "count": count}, ensure_ascii=False, indent=2))
    return 0


def cli_route(args: Any) -> int:
    try:
        route = route_request(args.need, args.domain, args.stage, args.intent)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(route, ensure_ascii=False, indent=2))
    else:
        print(route_markdown(route))
    return 2 if route.get("status") == "needs_domain" else 0


def cli_do(args: Any) -> int:
    try:
        route = route_request(args.need, args.domain, args.stage, args.intent)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if route.get("status") == "needs_domain":
        if getattr(args, "json", False):
            print(json.dumps(route, ensure_ascii=False, indent=2))
        else:
            print(route_markdown(route))
        return 2
    if getattr(args, "dry_run", False):
        if getattr(args, "json", False):
            print(json.dumps(route, ensure_ascii=False, indent=2))
        else:
            print(route_markdown(route))
        return 0
    study_dir = Path(args.study or f"./askovo-{route['domain']}-{route['stage']}").resolve()
    if route.get("safety_gate") == "review" and not getattr(args, "ack_risk", False):
        if study_dir.exists() and any(
            item.name not in {"route.json", "route.md"} for item in study_dir.iterdir()
        ):
            print(f"refusing to write safety route into non-empty directory: {study_dir}", file=sys.stderr)
            return 2
        _write_route(study_dir, route)
        print(
            f"安全/伦理门未通过：检测到 {', '.join(item['flag'] for item in route['risk_flags'])}\n"
            f"已写出路由到 {study_dir / 'route.md'}；完成审查后再加 --ack-risk 生成研究计划。",
            file=sys.stderr,
        )
        return 4
    try:
        result = create_study(
            study_dir,
            route,
            force=getattr(args, "force", False),
            acknowledge=getattr(args, "ack_risk", False),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"已创建研究：{result['study_dir']}")
        print(f"- 产品：{route['domain_label']} / {route['stage_label']}")
        print(f"- 方法：{', '.join(item['name'] for item in route['recommended_methods'])}")
        if result["instruments"]:
            print(f"- 工具包：{', '.join(result['instruments'])}")
        print(f"- 产品推理链：{result['product_reasoning']}")
        print(f"- 下一步：先补全产品推理链与 study.json，再运行 askovo check {result['study_dir']} --stage design")
    return 0


def cli_methods(args: Any) -> int:
    try:
        pack = load_pack(args.domain)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    stage = args.stage or pack.get("default_stage", "discovery")
    if stage not in pack["stages"]:
        print(f"unknown stage {stage!r}", file=sys.stderr)
        return 2
    catalog = methods()
    rows = []
    for method_id in pack["stages"][stage].get("methods", []):
        method = catalog.get(method_id)
        if method:
            rows.append(_method_view(method))
    if getattr(args, "json", False):
        print(json.dumps({"domain": args.domain, "stage": stage, "methods": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{pack['label']} / {pack['stages'][stage]['label']}")
        for item in rows:
            print(f"- {item['name']}（{item['id']}）：{'；'.join(item['answers'])}")
    return 0


def cli_catalog(args: Any) -> int:
    catalog = method_catalog()
    rows = catalog["methods"]
    if getattr(args, "domain", None):
        rows = [item for item in rows if args.domain in item.get("applicable_domains", [])]
    if getattr(args, "stage", None):
        rows = [item for item in rows if args.stage in item.get("lifecycle", [])]
    if getattr(args, "json", False):
        print(json.dumps({"schema_version": catalog.get("schema_version"), "methods": rows}, ensure_ascii=False, indent=2))
    else:
        for item in rows:
            print(f"- {item['id']}: {item['name']}")
    return 0


def cli_domains(args: Any) -> int:
    packs = domain_packs()
    rows = [
        {"domain": name, "label": pack["label"], "stages": list(pack.get("stages", {}))}
        for name, pack in packs.items()
    ]
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"- {row['domain']}: {row['label']}（{len(row['stages'])} 个阶段）")
    return 0


def cli_instruments(args: Any) -> int:
    try:
        written = generate_instruments(Path(args.study_dir))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", "written": written}, ensure_ascii=False, indent=2))
    return 0


def cli_import(args: Any) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    try:
        result = import_material(
            Path(args.study_dir),
            path,
            source_family=args.source_family,
            evidence_form=args.evidence_form,
            claim_type=args.claim_type,
            method_id=args.method_id,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_codebook(args: Any) -> int:
    try:
        result = scaffold_codebook(Path(args.study_dir))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_economics(args: Any) -> int:
    """Project the business node's unit economics; arithmetic only, never proof."""
    try:
        study_dir = Path(args.study_dir).resolve()
        reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            raise ValueError(
                f"missing {study_dir / '04-findings/product-reasoning.json'}; run askovo chain first"
            )
        study = load_json(study_dir / "study.json") if (study_dir / "study.json").is_file() else {}
        title = str(study.get("title") or "产品推理链") if isinstance(study, dict) else "产品推理链"
        markdown, stats = unit_economics_report(reasoning, title)
        report = study_dir / "06-report" / "unit-economics.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(markdown, encoding="utf-8")
        result = {
            "status": "rendered",
            "chain_file": str(study_dir / "04-findings/product-reasoning.json"),
            "report": str(report),
            "chains": stats["chains"],
            "boundary": "算术投影，不构成商业证明；null 表示未知；来源缺口需补证后重算",
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_psm(args: Any) -> int:
    """Van Westendorp PSM projection from a four-question CSV export."""
    csv_path = Path(args.input)
    if not csv_path.is_file():
        print(f"PSM input not found: {csv_path}", file=sys.stderr)
        return 2
    try:
        study_dir = Path(args.study_dir).resolve()
        try:
            study_meta = load_json(study_dir / "study.json")
        except (OSError, json.JSONDecodeError):
            study_meta = None
        study_ref = str(study_meta.get("study_id") or "") if isinstance(study_meta, dict) else ""
        currency = str(getattr(args, "currency", "") or "未注明币种")
        markdown, stats = psm_report(csv_path, currency, study_ref)
        report = study_dir / "06-report" / "pricing-psm.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(markdown, encoding="utf-8")
        result = {
            "status": "rendered",
            "report": str(report),
            "valid_rows": stats["valid_rows"],
            "rejected_rows": stats["rejected_rows"],
            "intersections": stats.get("intersections"),
            "boundary": "陈述意向投影，不是付费行为证据；不能直接 validated 商业节点",
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    points = result.get("intersections") or {}
    computable = [key for key in ("pmc", "opp", "idp", "pme") if points.get(key) is not None]
    if result["valid_rows"] < 2 or not computable:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("insufficient valid rows or no computable intersection; check the CSV and sample design", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_chain(args: Any) -> int:
    try:
        study_dir = Path(args.study_dir).resolve()
        scaffold = scaffold_product_reasoning(study_dir)
        reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            raise ValueError("cannot create product-reasoning.json")
        study = load_json(study_dir / "study.json") if (study_dir / "study.json").is_file() else {}
        title = str(study.get("title") or "产品推理链") if isinstance(study, dict) else "产品推理链"
        report = study_dir / "06-report" / "product-reasoning.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(product_reasoning_markdown(reasoning, title), encoding="utf-8")
        result = {
            "status": scaffold["status"],
            "chain_file": scaffold["path"],
            "report": str(report),
            "flow": list(REASONING_NODES),
            "summary": product_reasoning_summary(reasoning),
            "next_step": "填写各节点的 statement/rationale/status/evidence_ids，再运行 askovo check STUDY --stage design 或 --stage full",
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_deliver(args: Any) -> int:
    try:
        result = deliver(Path(args.study_dir), args.kind)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_doctor(args: Any) -> int:
    return doctor()


def _signoff_page(study: dict[str, Any], reasoning: dict[str, Any],
                  study_dir: Path, audit_status: str = "not_run") -> str:
    """F3 stakeholder sign-off one-pager: conclusion, levels, boundaries, blanks to sign."""
    evidence_levels: dict[str, str] = {}
    reviewed = unreviewed = 0
    evidence_path = Path(study_dir) / "02-data" / "evidence.jsonl"
    if evidence_path.is_file():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue  # 模板注释行等非 JSON 行
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            evidence_levels[str(rec.get("record_id"))] = str(rec.get("evidence_level") or "")
            if rec.get("human_review_status") == "reviewed":
                reviewed += 1
            else:
                unreviewed += 1
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    lines = [
        "# 干系人签收页",
        "",
        f"> 研究：{study.get('title', '')}（{study.get('study_id', '')}）",
        f"> 决策问题：{(study.get('decision') or {}).get('question', '')}",
        f"> 责任人：{(study.get('decision') or {}).get('owner', '')} · 截止：{(study.get('decision') or {}).get('deadline', '')}",
        f"> full audit：`{audit_status}`（仅 pass 才可进入签收；签收不替代专业复核）",
        "",
    ]
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        lines += [
            f"## {chain.get('id', '')} · {chain.get('title', '')}",
            "",
            f"- 链状态：`{chain.get('status', '')}`（置信度 {chain.get('confidence', '')}）——**不是需求或商业已证明**",
            f"- 反证 {len(chain.get('counter_evidence_ids') or [])} 条在案；替代解释 {len(chain.get('alternative_explanations') or [])} 条在案",
            "",
            "| 节点 | 判断（摘要） | 状态 | 证据等级 |",
            "| --- | --- | --- | --- |",
        ]
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for node_name, node in nodes.items():
            if not isinstance(node, dict):
                continue
            ids = [str(v) for v in node.get("evidence_ids", [])] if isinstance(node.get("evidence_ids"), list) else []
            levels = [evidence_levels.get(i, "?") for i in ids]
            level_summary = ", ".join(f"{lv}×{levels.count(lv)}" for lv in sorted(set(levels)) if lv) or "无"
            statement = str(node.get("statement", ""))[:60]
            lines.append(f"| {node_name} | {statement} | `{node.get('status', '')}` | {level_summary} |")
        assumptions = [a for a in (chain.get("gaps") or []) if isinstance(a, str)][:5]
        lines += ["", "**未验证假设（签收前必读）**："]
        lines += [f"- {a}" for a in assumptions] or ["- （无记录）"]
        lines.append("")
    lines += [
        "## 边界声明",
        "",
        "- 本页只汇总研究链现状，不证明总体比例、市场规模、因果或产品成功；",
        f"- 证据复核状态：已复核 {reviewed} 条 / 待复核 {unreviewed} 条——待复核证据不因出现在本页而生效；",
        "- 超出证据等级的表述应被 `askovo check` 拦截；如发现本页与 04-findings 主链不一致，以主链为准。",
        "",
        "## 签收",
        "",
        "| 角色 | 姓名 | 意见（采纳/修改/退回） | 日期 |",
        "| --- | --- | --- | --- |",
        "| 决策人 |  |  |  |",
        "| 复核人 |  |  |  |",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# F2 boundary audit: Added / Missing / Inflated between requirements and an AI doc


BOUNDARY_STOPWORDS = set(
    "the a an and or of to for in on with by is are be as at from that this it its "
    "we you they i our your their will shall should can may need needs want wants "
    "的 了 和 与 或 在 对 从 被 把 是 有 要 会 能 并 等 以及 一个 我们 你们".split()
)


def _boundary_items(path: Path) -> list[tuple[str, str]]:
    """Parse a doc into traceable items: (ref 'file:line', text)."""
    items: list[tuple[str, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            items.append((f"{path.name}:{lineno}", line.lstrip("# ").strip()))
            continue
        if len(line) > 2 and line[0] in "-*•" or (line[:2].rstrip(".").isdigit() and "." in line[:4]):
            items.append((f"{path.name}:{lineno}", line.lstrip("-*•0123456789. ").strip()))
            continue
        # prose: split sentences (zh + en)
        buf = ""
        for char in line:
            buf += char
            if char in "。．.!?；;":
                sentence = buf.strip()
                if len(sentence) >= 12:
                    items.append((f"{path.name}:{lineno}", sentence))
                buf = ""
        tail = buf.strip()
        if len(tail) >= 12:
            items.append((f"{path.name}:{lineno}", tail))
    return items


def _boundary_tokens(text: str) -> set[str]:
    """Normalized content tokens; zh chars pass through, en words lowercased."""
    tokens: set[str] = set()
    current = ""
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if current:
                word = current.lower()
                if len(word) > 1 and word not in BOUNDARY_STOPWORDS:
                    tokens.add(word)
                current = ""
            tokens.add(char)
        elif char.isalnum():
            current += char
        else:
            if current:
                word = current.lower()
                if len(word) > 1 and word not in BOUNDARY_STOPWORDS:
                    tokens.add(word)
                current = ""
    if current:
        word = current.lower()
        if len(word) > 1 and word not in BOUNDARY_STOPWORDS:
            tokens.add(word)
    return tokens


def boundary_audit(
    requirements_path: Path,
    output_path: Path,
    match_threshold: float = 0.30,
    inflate_ratio: float = 3.0,
    inflate_new_tokens: int = 12,
) -> dict[str, Any]:
    """Deterministic lexical boundary audit: Added / Missing / Inflated.

    Heuristic by design: it flags candidate deviations for human review; it does
    not understand semantics and never claims a deviation is an error.
    """
    req_items = _boundary_items(Path(requirements_path))
    out_items = _boundary_items(Path(output_path))
    req_tokens = [(ref, text, _boundary_tokens(text)) for ref, text in req_items]
    out_tokens = [(ref, text, _boundary_tokens(text)) for ref, text in out_items]

    def best_match(item: tuple[str, str, set], others: list[tuple[str, str, set]]):
        best = (0.0, None)
        for other in others:
            union = item[2] | other[2]
            score = (len(item[2] & other[2]) / len(union)) if union else 0.0
            if score > best[0]:
                best = (score, other)
        return best

    added, missing, inflated = [], [], []
    matched_out_refs = set()
    for ref, text, tokens in out_tokens:
        score, match = best_match((ref, text, tokens), req_tokens)
        if score < match_threshold and len(tokens) >= 3:
            added.append({"ref": ref, "excerpt": text[:120], "closest": (match[0] if match else ""), "score": round(score, 2)})
        elif match is not None:
            matched_out_refs.add(ref)
            req_len = max(1, len(match[2]))
            ratio = len(tokens) / req_len
            new_tokens = len(tokens - match[2])
            if ratio >= inflate_ratio and new_tokens >= inflate_new_tokens:
                inflated.append({
                    "ref": ref, "excerpt": text[:120], "against": match[0],
                    "against_excerpt": match[1][:80], "ratio": round(ratio, 1), "new_tokens": new_tokens,
                })
    matched_req_refs = set()
    for ref, text, tokens in req_tokens:
        score, match = best_match((ref, text, tokens), out_tokens)
        if score < match_threshold and len(tokens) >= 3:
            missing.append({"ref": ref, "excerpt": text[:120], "closest": (match[0] if match else ""), "score": round(score, 2)})
        elif match is not None:
            matched_req_refs.add(match[0])

    return {
        "requirements": {"path": str(requirements_path), "items": len(req_items)},
        "output": {"path": str(output_path), "items": len(out_items)},
        "added": added,
        "missing": missing,
        "inflated": inflated,
        "matched": len(matched_out_refs & matched_req_refs),
        "thresholds": {"match": match_threshold, "inflate_ratio": inflate_ratio, "inflate_new_tokens": inflate_new_tokens},
        "boundary": ("词法启发式对照：三条清单是候选偏差，不是错误判定；语义判断（是否真属未讨论添加/缺失/膨胀）"
                     "由人工复核负责。阈值可在命令行覆盖。"),
    }


def boundary_report(result: dict[str, Any]) -> str:
    lines = [
        "# 边界审计：需求 ↔ AI 产出对照（候选清单）",
        "",
        f"> 需求侧 {result['requirements']['items']} 项 / 产出侧 {result['output']['items']} 项，词法匹配 {result['matched']} 对。",
        f"> {result['boundary']}",
        "",
    ]
    for key, label in (("added", "Added｜产出有、需求未讨论（候选越界添加）"),
                       ("missing", "Missing｜需求有、产出未见（候选遗漏）"),
                       ("inflated", "Inflated｜有对应但显著膨胀（候选范围膨胀）")):
        rows = result[key]
        lines += [f"## {label}（{len(rows)}）", ""]
        if not rows:
            lines += ["（无）", ""]
            continue
        if key == "inflated":
            for row in rows:
                lines.append(f"- `{row['ref']}` {row['excerpt']}")
                lines.append(f"  - 对照 `{row['against']}`（{row['against_excerpt']}…）：{row['ratio']}×，新增实词 {row['new_tokens']} 个")
        else:
            for row in rows:
                hint = f"（最近对照 `{row['closest']}`，重合 {row['score']}）" if row["closest"] else ""
                lines.append(f"- `{row['ref']}` {row['excerpt']} {hint}")
        lines.append("")
    return "\n".join(lines)


def cli_boundary(args: Any) -> int:
    req = Path(args.requirements)
    out = Path(args.output)
    for path, label in ((req, "--requirements"), (out, "--output")):
        if not path.is_file():
            print(f"{label} file not found: {path}", file=sys.stderr)
            return 2
    result = boundary_audit(req, out, match_threshold=args.match_threshold, inflate_ratio=args.inflate_ratio)
    if args.study_dir:
        report_path = Path(args.study_dir) / "06-report" / "boundary-audit.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(boundary_report(result), encoding="utf-8")
        result["report"] = str(report_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# F4 verification cost log: manual minutes with optional no-tool baseline


def cost_log(study_dir: Path, *, task: str, minutes: int, baseline_minutes, note: str = "") -> dict[str, Any]:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("minutes must be a positive integer")
    if baseline_minutes is not None and (isinstance(baseline_minutes, bool) or not isinstance(baseline_minutes, int) or baseline_minutes <= 0):
        raise ValueError("baseline_minutes must be a positive integer when provided")
    if not str(task or "").strip():
        raise ValueError("task cannot be empty")
    path = Path(study_dir) / "02-data" / "verify-log.jsonl"
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "task": task,
        "minutes": minutes,
        "baseline_minutes": baseline_minutes,
        "note": note or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def cost_report(study_dir: Path) -> dict[str, Any]:
    path = Path(study_dir) / "02-data" / "verify-log.jsonl"
    rows = []
    if path.is_file():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    total = sum(r["minutes"] for r in rows)
    baseline_rows = [r for r in rows if r.get("baseline_minutes")]
    baseline_total = sum(r["baseline_minutes"] for r in baseline_rows)
    actual_of_baseline = sum(r["minutes"] for r in baseline_rows)
    ratio = round(baseline_total / actual_of_baseline, 2) if actual_of_baseline else None
    return {
        "tasks": len(rows),
        "total_minutes": total,
        "tasks_with_baseline": len(baseline_rows),
        "baseline_minutes": baseline_total,
        "actual_minutes_on_baseline_tasks": actual_of_baseline,
        "baseline_to_actual_ratio": ratio,
        "rows": rows,
        "boundary": ("算术汇总，不是效率证明：基线是同任务自报的无工具口径，样本量与可比性由人工判断；"
                     "ratio 只在提供基线的任务上计算。"),
    }


def cli_cost(args: Any) -> int:
    study_dir = Path(args.study_dir)
    if not (study_dir / "study.json").is_file():
        print(f"missing study.json under {study_dir}", file=sys.stderr)
        return 2
    if args.action == "log":
        try:
            rec = cost_log(study_dir, task=args.task, minutes=args.minutes,
                           baseline_minutes=args.baseline_minutes, note=args.note or "")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(rec, ensure_ascii=False))
        return 0
    print(json.dumps(cost_report(study_dir), ensure_ascii=False, indent=2))
    return 0

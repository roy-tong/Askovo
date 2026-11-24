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
import importlib.util
import os
import socket
import struct
import json
import math
import re
import shlex
import subprocess
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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.append(str(_SCRIPT_DIR))

import study_context
import external_bridge
import delivery_projection
import needs_delivery
import role_catalog
import web_surface

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
REPO_ROOT = SKILL_ROOT.parent.parent
ASSETS = SKILL_ROOT / "assets"
CATALOG_PATH = ASSETS / "method-catalog.json"
PACKS_DIR = ASSETS / "domain-packs"
CHINESE_LEXICON_PATH = ASSETS / "chinese-lexicon.txt"

_cdp_strategy_module: Any = None


def _cdp_strategy() -> Any:
    """Load the connectors' CDP strategy module (policy, triage, session guard).

    Loaded by path so the engine does not depend on the connectors directory
    being importable; the module itself resolves its registry and `common.py`
    fallbacks. Cached after the first call.
    """
    global _cdp_strategy_module
    if _cdp_strategy_module is None:
        path = HERE / "connectors" / "cdp_strategy.py"
        spec = importlib.util.spec_from_file_location("askovo_cdp_strategy", path)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("askovo_cdp_strategy", module)
        spec.loader.exec_module(module)
        _cdp_strategy_module = module
    return _cdp_strategy_module

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
    "fullstack_developer",
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
CHAIN_NODE_STATUSES = ("hypothesis", "needs-validation", "validated", "rejected", "deprioritized")
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
RESEARCH_MODES = ("discover", "validate", "optimize")
RESEARCH_MODE_LABELS = {
    "discover": "机会发现",
    "validate": "假设验证",
    "optimize": "产品迭代",
}
RESEARCH_MODE_BY_STAGE = {
    "discovery": "discover",
    "concept": "discover",
    "validation": "validate",
    "pricing": "validate",
    "prelaunch": "validate",
    "postlaunch": "optimize",
    "audit": "optimize",
    "operate": "optimize",
}
RESEARCH_MODE_KEYWORDS = {
    "discover": (
        "机会",
        "发现",
        "创业",
        "新想法",
        "新点子",
        "新业务",
        "新品类",
        "从0到1",
        "从零到一",
        "市场空白",
        "空白市场",
        "未满足",
        "切入",
        "idea",
        "opportunity",
        "discover",
        "startup",
        "new product",
        "from scratch",
    ),
    "validate": (
        "验证",
        "假设",
        "待验证",
        "证伪",
        "是否成立",
        "能不能成立",
        "支持证据",
        "反证",
        "反例",
        "试点",
        "beta",
        "pilot",
        "hypothesis",
        "validate",
        "validation",
        "falsif",
    ),
    "optimize": (
        "优化",
        "迭代",
        "诊断",
        "改进",
        "下降",
        "下滑",
        "转化",
        "留存",
        "流失",
        "续费",
        "复购",
        "漏斗",
        "现有产品",
        "已有产品",
        "现有功能",
        "下一轮",
        "产品迭代",
        "上线后",
        "churn",
        "retention",
        "conversion",
        "funnel",
        "optimize",
        "improve",
        "iteration",
        "decline",
    ),
}
RESEARCH_MODE_BOUNDARY = (
    "入口只决定先回答什么，不豁免七节点的证据要求；上游未验证前只能作为假设，不能当作事实。"
)
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
    context = study_context.current_study_context()
    if context is not None and context.owns(path):
        return context.read_json(path)
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
        ("deliver", ("memo", "报告", "prd", "交付物", "决策纪要", "写一份", "业务方案")),
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


PUBLIC_COMMUNITY_BOUNDARY = (
    "公开社区是发言者自选择的便利样本，只能描述本语料，不能推总体发生率、市场规模或真实付费。"
)
INTERVIEW_BOUNDARY = "访谈用于理解场景、机制与反例，不能推市场规模或总体比例。"
PRICE_EXPERIMENT_BOUNDARY = (
    "公开评论、购买意向和竞品标价都不能证明本品真实付费；优先真实报价、可拒绝的付费试点或交付实验。"
)
SELECTION_BIAS_FIELDS = [
    "target_population",
    "recruitment_frame",
    "exposure_rule",
    "invited_count",
    "responded_count",
    "offer_accepted_count",
    "paid_count",
    "delivered_count",
    "nonresponse_and_attrition",
    "known_confounders",
]


def _sample_mechanism(
    method_id: str,
    question: str,
    *,
    action: str = "",
    intent: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Explain how observations enter a method before claiming what it can answer."""
    low = question.casefold()
    public = bool(sources) or any(
        token in low for token in ("公开社区", "社区评论", "公开评论", "reddit", "论坛", "评论", "community")
    )
    commercial = intent == "commercial" or any(
        token in low for token in ("付费", "价格", "定价", "成交", "报价", "purchase", "pricing", "payment", "paid")
    )
    experiment = (
        action == "experiment"
        or method_id in {"price-promo-test", "ab-test", "beta-soak"}
        or (commercial and any(token in low for token in ("实验", "试验", "试点", "experiment", "pilot")))
    )
    interview = method_id in {"discovery-interview", "contextual-inquiry", "diary-study"} or "访谈" in low
    if experiment:
        mechanism = "recruited_offer_or_delivery_experiment"
        description = "由招募框、曝光规则、报价/交付邀请和实际接受行为形成样本；逐层保留分母与流失。"
        bias = ["招募自选择", "曝光分配不均", "接受者偏差", "未交付与退出偏差"]
    elif interview:
        mechanism = "purposive_self_selected_interviews"
        description = "研究者按场景招募且受访者自愿参与，覆盖机制与反例，不构成总体抽样框。"
        bias = ["招募自选择", "回忆与 social-desirability 偏差", "热心用户过度代表"]
    elif public:
        mechanism = "public_community_self_selection"
        description = "平台可见性、搜索/排序与发言意愿共同决定哪些记录进入语料。"
        bias = ["平台与排序偏差", "发言者自选择", "沉默用户和非购买者缺失"]
    else:
        mechanism = "stage_specific_purposive_sampling"
        description = "按研究问题与生命周期阶段目的抽样；必须另行声明招募框、纳入规则和缺失 strata。"
        bias = ["目的抽样覆盖偏差", "未记录的无回应与缺失 strata"]
    return {
        "id": mechanism,
        "description": description,
        "selection_bias": bias,
        "public_community": public,
        "commercial_question": commercial,
        "interview_method": interview,
        "experiment_method": experiment,
    }


def research_method_selection(
    question: str,
    selected_methods: list[dict[str, Any]] | None = None,
    *,
    action: str = "",
    intent: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project question → sample formation → applicable methods → claim boundaries.

    This is deterministic methodological guidance, not a validation verdict. In
    particular, public comments never become payment proof and offer experiments
    always carry an explicit selection-bias register.
    """
    methods_value = selected_methods or []
    if not methods_value:
        low = question.casefold()
        commercial = intent == "commercial" or any(
            token in low for token in ("付费", "价格", "定价", "成交", "报价", "purchase", "pricing", "payment", "paid")
        )
        if action == "experiment" or commercial:
            fallback_ids = ["price-promo-test", "beta-soak"]
        elif "访谈" in low:
            fallback_ids = ["discovery-interview"]
        else:
            fallback_ids = ["contextual-inquiry"]
        catalog = methods()
        methods_value = [_method_view(catalog[item]) for item in fallback_ids if item in catalog]
    profiles: list[dict[str, Any]] = []
    applicable: list[dict[str, Any]] = []
    for method in methods_value:
        method_id = str(method.get("id") or "")
        profile = _sample_mechanism(method_id, question, action=action, intent=intent, sources=sources)
        boundaries = [str(value) for value in method.get("does_not_support", [])]
        if profile["public_community"]:
            boundaries.append(PUBLIC_COMMUNITY_BOUNDARY)
        if profile["interview_method"]:
            boundaries.append(INTERVIEW_BOUNDARY)
        if profile["commercial_question"]:
            boundaries.append(PRICE_EXPERIMENT_BOUNDARY)
        if profile["experiment_method"]:
            boundaries.append("报价/交付实验只适用于实际曝光且满足纳入规则的人群；必须记录选择偏差，不能外推总体。")
        entry = dict(method)
        entry.update({
            "research_question": question,
            "sample_formation_mechanism": profile,
            "conclusion_boundary": list(dict.fromkeys(boundaries)),
            "selection_bias_record_required": bool(profile["experiment_method"]),
            "selection_bias_fields": list(SELECTION_BIAS_FIELDS) if profile["experiment_method"] else [],
        })
        applicable.append(entry)
        profiles.append(profile)
    if not profiles:
        profiles.append(_sample_mechanism("", question, action=action, intent=intent, sources=sources))
    boundaries: list[str] = []
    for profile in profiles:
        if profile["public_community"]:
            boundaries.append(PUBLIC_COMMUNITY_BOUNDARY)
        if profile["interview_method"]:
            boundaries.append(INTERVIEW_BOUNDARY)
        if profile["commercial_question"]:
            boundaries.append(PRICE_EXPERIMENT_BOUNDARY)
    if any(profile["experiment_method"] for profile in profiles):
        boundaries.append("报价实验必须记录招募、曝光、回应、接受、支付、交付与退出各环节的选择偏差。")
    return {
        "research_question": question,
        "sample_formation_mechanisms": profiles,
        "applicable_methods": applicable,
        "conclusion_boundaries": list(dict.fromkeys(boundaries)),
        "selection_bias_fields": list(SELECTION_BIAS_FIELDS),
        "boundary": "方法选择只界定可回答的问题与结论边界，不自动升级任何节点或需求判断为 validated。",
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


def _research_mode_hits(text: str) -> dict[str, list[str]]:
    low = text.casefold()
    return {
        mode: [keyword for keyword in keywords if keyword.casefold() in low]
        for mode, keywords in RESEARCH_MODE_KEYWORDS.items()
    }


def _research_mode_alternatives(scores: dict[str, int], chosen: str) -> list[dict[str, Any]]:
    ranked = sorted(
        (name for name in RESEARCH_MODES if name != chosen and scores[name] > 0),
        key=lambda name: (-scores[name], RESEARCH_MODES.index(name)),
    )
    return [
        {"mode": name, "label": RESEARCH_MODE_LABELS[name], "score": scores[name]}
        for name in ranked
    ]


def detect_research_mode(
    text: str,
    stage: str | None = None,
    mode: str | None = None,
    stage_source: str | None = None,
) -> dict[str, Any]:
    """Detect discover/validate/optimize for the current task.

    Priority: explicit mode > task text > explicit stage > keyword-inferred
    stage > default. Stage is a background condition (where the product is),
    not the task type; it only decides when the task itself has no signal.
    ``confidence`` is a keyword heuristic score, not a calibrated probability.
    """
    hits_by_mode = _research_mode_hits(text)
    scores = {name: len(hits) for name, hits in hits_by_mode.items()}

    def result(chosen: str, confidence: float, source: str) -> dict[str, Any]:
        return {
            "mode": chosen,
            "label": RESEARCH_MODE_LABELS[chosen],
            "confidence": confidence,
            "score_basis": "keyword_hits" if source in {"text", "stage"} else "rule",
            "calibrated": False,
            "source": source,
            "signals": hits_by_mode[chosen],
            "alternatives": _research_mode_alternatives(scores, chosen),
        }

    if mode:
        if mode not in RESEARCH_MODES:
            raise ValueError(
                f"unknown research mode {mode!r}; choose from: {', '.join(RESEARCH_MODES)}"
            )
        return result(mode, 1.0, "explicit")

    ranked = sorted(
        RESEARCH_MODES, key=lambda name: (-scores[name], RESEARCH_MODES.index(name))
    )
    chosen = ranked[0]
    if scores[chosen] > 0:
        return result(chosen, round(min(0.95, 0.55 + 0.1 * scores[chosen]), 2), "text")

    effective_stage_source = stage_source or ("explicit" if stage else None)
    if stage in RESEARCH_MODE_BY_STAGE and effective_stage_source == "explicit":
        return result(RESEARCH_MODE_BY_STAGE[stage], 0.7, "stage")
    if stage in RESEARCH_MODE_BY_STAGE and effective_stage_source == "keywords":
        return result(RESEARCH_MODE_BY_STAGE[stage], 0.55, "stage")
    return result("discover", 0.3, "default")


def _research_entry_node(text: str, mode: str) -> str:
    low = text.casefold()
    if mode == "discover":
        return "scene"
    if mode == "validate":
        if any(token in low for token in ("付费", "价格", "定价", "商业", "收入")):
            return "business"
        if any(token in low for token in ("功能", "特性", "方案", "形态")):
            return "feature"
        return "need"
    if any(token in low for token in ("付费", "价格", "收入", "续费", "商业")):
        return "business"
    return "product"


def _research_why_entry(mode: str, entry_node: str) -> str:
    if mode == "discover":
        return (
            "Discover 从场景进入：先找到真实发生、可观察的任务与触发条件，"
            "再判断是否值得进入用户、痛点和需求。"
        )
    if mode == "validate":
        reasons = {
            "need": "Validate 从待验证的 need 节点进入：先检验谁在什么场景下有什么未满足结果，再讨论方案。",
            "feature": "Validate 从 feature 节点进入：把功能/形态当假设，检验它是否真的改变用户任务结果。",
            "business": "Validate 从 business 节点进入：先检验付费、价格或收入假设；商业证据不能替代需求与产品证据。",
        }
        return reasons[entry_node]
    reasons = {
        "product": "Optimize 从 product 节点进入：先诊断现有产品在真实使用中的断点，再回到上游修正假设。",
        "business": "Optimize 从 business 节点进入：先诊断商业化断点；商业指标下降不等于需求不存在。",
    }
    return reasons[entry_node]


def _research_questions(mode: str, entry_node: str) -> list[str]:
    if mode == "discover":
        return [
            "哪些真实场景中，用户已经在用替代方案或笨办法完成同一任务？",
            "这个场景的触发条件、频率和失败后果是什么，谁在承担成本？",
            "哪类用户或环境下的场景最值得优先研究，现有替代为什么不够？",
            "这个场景是否稳定、可观察，足以支撑进入用户与痛点研究？",
        ]
    if mode == "validate":
        questions = {
            "need": [
                "待验证的 need 命题具体是什么？支持、反证和未知各有哪些？",
                "哪类用户在哪个场景、完成什么任务时出现了什么未满足结果？",
                "现有替代方案（人工、竞品、不行动）为什么不够，用户付出了什么代价？",
                "哪些新证据会推翻“这是真需求”的判断？",
            ],
            "feature": [
                "这个功能/形态对应哪个尚未验证的 need？",
                "目标用户能否在真实任务中完成任务，完成率、失败点和代价是什么？",
                "与现有替代方案相比，增量价值是什么，在什么条件下不成立？",
                "哪些结果会证明“功能有价值”是错的？",
            ],
            "business": [
                "谁付费、为哪个结果付费、在什么场景下付费？",
                "价格、计费方式或收入假设有哪些可拒绝的真实证据？",
                "即使有人愿意付费，需求与产品证据是否足以支撑商业假设？",
                "哪些反证（不续费、压价、采购周期、替代品）会推翻当前判断？",
            ],
        }
        return questions[entry_node]
    if entry_node == "business":
        return [
            "商业化指标的口径、分母和时间窗是什么，是否存在埋点或归因缺口？",
            "变化集中在哪些客群、套餐/价格、渠道或销售阶段？",
            "断点来自需求、产品体验还是定价/销售机制，哪些替代解释未排除？",
            "上游哪个节点假设需要重新验证？",
            "哪些商业反证会推翻当前判断？",
        ]
    return [
        "指标变差的口径、分母、时间窗和数据完整性是否可信？",
        "变化集中在哪些用户分层、场景、版本或渠道？",
        "真实任务中的断点在哪里，机制假设和替代解释各是什么？",
        "需要回到七节点中的哪个上游假设修正？",
        "改进的预期结果、反例与停止条件是什么？",
    ]


def _research_first_actions(mode: str, entry_node: str) -> list[str]:
    if mode == "discover":
        return [
            "选 3–5 个典型场景做情境访查，记录触发、步骤、替代方案和结果。",
            "用工单、社区讨论、搜索或售后记录三角验证场景线索，只作发现，不作总体推断。",
            "为每个候选场景写清可证伪假设：哪个条件不成立，场景就不成立。",
            "按频率 × 后果 × 替代成本排出候选机会，并标注证据缺口。",
        ]
    if mode == "validate":
        actions = {
            "need": [
                "把待验证命题写成一句可证伪的判断，并预登记支持、反证与未知。",
                "对目标用户做情境访谈，追问最近一次真实发生及替代方案，而非泛问需求。",
                "收集行为或交付证据（使用记录、工单、真实承诺），与访谈分开登记。",
                "做一次最小可拒绝验证（试用、预约、可退押金），记录拒绝与流失。",
            ],
            "feature": [
                "用可点击原型或 concierge 跑真实任务测试，记录完成率、失败点和代价。",
                "设置替代方案对照，判断增量来自功能本身还是场景/人群差异。",
                "预登记证伪条件：出现哪些失败任务或替代更优，就判定功能假设不成立。",
                "把支持、反证、未知写入证据台账，禁止用满意度替代任务结果。",
            ],
            "business": [
                "访谈付费决策人与使用者，分开记录“愿意付”和“实际付”。",
                "设计可拒绝的报价、付费试点或退款承诺，保留邀请、接受、支付、交付分母。",
                "核对价格、成本和收入假设的来源与时间窗，缺数就保留 null。",
                "收集不续费、压价、采购周期和替代品等反证，并预登记推翻条件。",
            ],
        }
        return actions[entry_node]
    if entry_node == "business":
        return [
            "固化转化、续费、收入等指标的口径、分母与时间窗。",
            "按客群、套餐/价格、渠道和销售阶段分层，定位商业断点。",
            "与财务/销售复核价格、成本和收入假设，缺数保留 null。",
            "访谈成交、流失和拒绝客户，区分需求不足、体验断点与定价问题。",
            "设计可拒绝的定价或续费实验，预登记反证与停止条件。",
        ]
    return [
        "先固化指标口径、分母、时间窗和数据完整性，再做比较。",
        "按用户分层、场景、版本、渠道拆解变化，找出最大断点。",
        "走查漏斗、日志与工单，列出机制假设和至少两个替代解释。",
        "访谈流失、未转化和高频用户，验证断点是否发生在真实任务中。",
        "选定最小改进实验，预登记成功指标、反例和回滚条件。",
    ]


def _research_stop_conditions(mode: str) -> list[str]:
    if mode == "discover":
        return [
            "场景只能由二手评论推断，找不到可访谈或可观察的当事人。",
            "场景无法落到具体触发、任务和后果，只剩人群标签或抽象趋势。",
            "继续研究需要不可接受的安全、合规或数据授权风险。",
        ]
    if mode == "validate":
        return [
            "关键命题无法写成可证伪条件，支持与反证无法区分。",
            "现有证据只有态度或意向，缺少行为、交付或真实承诺。",
            "补证成本超过该决策的价值，或所需授权不可获得。",
            "出现清晰的反证而当前假设无法解释或修正。",
        ]
    return [
        "指标口径、分母或埋点不可信，无法做时间窗与分层比较。",
        "分层样本不足，或只能得到相关性而无法识别机制。",
        "改进涉及安全、合规、财务或发布审查，尚未获得责任人批准。",
        "上游假设需要重新验证，当前迭代范围无法覆盖。",
    ]


def research_entry_contract(
    text: str,
    mode: str | None = None,
    stage: str | None = None,
    stage_source: str | None = None,
) -> dict[str, Any]:
    """Return the mode entry contract without waiving any node's evidence requirement."""
    mode_info = detect_research_mode(
        text, stage=stage, mode=mode, stage_source=stage_source
    )
    entry_node = _research_entry_node(text, mode_info["mode"])
    entry_index = REASONING_NODES.index(entry_node)
    node_order = list(REASONING_NODES[entry_index:]) + list(REASONING_NODES[:entry_index])
    return {
        "mode": mode_info["mode"],
        "mode_label": RESEARCH_MODE_LABELS[mode_info["mode"]],
        "mode_source": mode_info["source"],
        "mode_score": mode_info["confidence"],
        "score_basis": mode_info.get("score_basis", "rule"),
        "calibrated": bool(mode_info.get("calibrated", False)),
        "entry_node": entry_node,
        "entry_label": REASONING_NODE_LABELS[entry_node],
        "node_order": node_order,
        "upstream_nodes": list(REASONING_NODES[:entry_index]),
        "why_entry": _research_why_entry(mode_info["mode"], entry_node),
        "questions": _research_questions(mode_info["mode"], entry_node),
        "first_actions": _research_first_actions(mode_info["mode"], entry_node),
        "stop_conditions": _research_stop_conditions(mode_info["mode"]),
        "boundary": RESEARCH_MODE_BOUNDARY,
    }


def opportunity_map_contract(study: dict[str, Any]) -> dict[str, Any]:
    """Scaffold the five-layer opportunity space for a 0→1 study.

    This is a structure, not a finding: every layer starts empty and requires
    source-linked items before it can influence the reasoning chain.
    """
    mode = str((study.get("research_mode") or {}).get("mode") or "discover")
    entry = str((study.get("research_mode") or {}).get("entry_node") or "scene")
    layers = {
        "market_and_alternatives": {
            "label": "市场与替代",
            "questions": [
                "谁已经在用相关方案完成任务？通过什么产品、服务或人工方式？",
                "现有供给最近发生了什么变化（价格、形态、渠道、能力）？",
                "哪些替代方案的成本、失败与退出条件是可观察的？",
                "这个市场里哪些说法只有厂商宣称、没有独立证据？",
            ],
            "items": [],
        },
        "users_and_tasks": {
            "label": "用户与任务",
            "questions": [
                "哪几类人分别为什么任务、在什么触发条件下使用替代方案？",
                "任务的频率、失败后果与约束条件是什么？",
                "哪些人群只是相邻用户，不能被当成目标用户？",
                "现有证据覆盖了哪些人群，缺了哪些人群？",
            ],
            "items": [],
        },
        "opportunity_hypotheses": {
            "label": "机会假设",
            "questions": [
                "哪些需求尚未被充分满足，为什么现有替代难以解决？",
                "这个判断依赖哪条关键假设？它被证伪的条件是什么？",
                "机会来自人群变化、技术变化、渠道变化还是成本结构变化？",
                "如果只能验证一个假设，哪个最能改变是否继续的判断？",
            ],
            "items": [],
        },
        "solution_space": {
            "label": "方案空间",
            "questions": [
                "可能的产品形态、能力边界与交付方式有哪些？",
                "每个方案依赖哪些关键技术、供应、渠道或合规条件？",
                "哪些方案只是功能堆叠，没有对应真实任务？",
                "最小可验证形态是什么，什么可以先不做？",
            ],
            "items": [],
        },
        "validation_paths": {
            "label": "验证路径",
            "questions": [
                "哪些机会可以继续用外部数据验证，哪些必须访谈或观察？",
                "哪些假设需要原型、真实报价、可拒绝的试点或交易测试？",
                "每个验证动作的成功、反证与停止条件是什么？",
                "验证成本与所需授权是否值得，谁来做决定？",
            ],
            "items": [],
        },
    }
    return {
        "schema": "askovo.opportunity-map/1",
        "study_id": study.get("study_id"),
        "domain": study.get("product_domain"),
        "mode": mode,
        "entry_node": entry,
        "fit_for_mode": mode == "discover",
        "layers": layers,
        "item_schema": {
            "id": "O1 / U1 / H1 / S1 / V1",
            "statement": "一句话判断",
            "status": "hypothesis | supported | contradicted | unknown",
            "evidence_ids": ["R01"],
            "counter_evidence_ids": [],
            "source_refs": ["https://…"],
            "assumptions": [],
            "next_test": "",
        },
        "evidence_boundary": (
            "公开讨论只能发现机会与替代，不能证明目标用户愿意购买；"
            "没有真实用户证据时，市场规模与付费意愿保持 unknown。"),
        "boundary": (
            "这是机会空间脚手架，不是研究结论；每个条目必须有来源、状态与反证记录，"
            "未经验证的条目不得进入产品方案或商业判断。"),
    }


def opportunity_map_markdown(contract: dict[str, Any]) -> str:
    lines = ["# 机会空间地图", ""]
    lines.append(f"- 研究模式：`{contract['mode']}`；入口节点：`{contract['entry_node']}`")
    if not contract.get("fit_for_mode"):
        lines.append("- 注意：当前不是 Discover 模式；该地图仍可用，但不应替代迭代诊断。")
    lines.append("")
    for key, layer in contract["layers"].items():
        lines.append(f"## {layer['label']}（`{key}`）")
        lines.append("")
        lines.append("要回答：")
        lines.extend(f"- {question}" for question in layer["questions"])
        lines.append("")
        items = layer.get("items") or []
        if items:
            for item in items:
                lines.append(
                    f"- **{item.get('id', '')}** {item.get('statement', '')}  "
                    f"（{item.get('status', 'unknown')}；证据 {', '.join(item.get('evidence_ids') or []) or '无'}）")
                if item.get("counter_evidence_ids"):
                    lines.append(f"  - 反证：{', '.join(item['counter_evidence_ids'])}")
                if item.get("next_test"):
                    lines.append(f"  - 下一步：{item['next_test']}")
        else:
            lines.append("当前条目：无（待补来源与状态）")
        lines.append("")
    lines.append("## 条目写法")
    lines.append("")
    lines.append("每个条目至少包含：判断、状态（hypothesis/supported/contradicted/unknown）、"
                 "支持证据 ID、反证 ID、来源链接、关键假设与下一步验证。")
    lines.append("")
    lines.append(f"> {contract['evidence_boundary']}")
    return "\n".join(lines) + "\n"


def research_mode_markdown(contract: dict[str, Any]) -> str:
    upstream = contract["upstream_nodes"]
    upstream_text = (
        " → ".join(REASONING_NODE_LABELS[node] for node in upstream)
        if upstream
        else "无（从主链起点进入）"
    )
    lines = [
        "# Askovo 研究模式",
        "",
        "## 模式与入口",
        "",
        f"- 模式：**{contract['mode_label']}**（`{contract['mode']}`，来源 `{contract['mode_source']}`）",
        f"- 判定分数：{contract.get('mode_score')}（{contract.get('score_basis', 'rule')}，未校准，不等于概率）",
        f"- 入口节点：**{contract['entry_label']}**（`{contract['entry_node']}`）",
        f"- 上游节点（未验证前只能是假设）：{upstream_text}",
        "",
        "## 为什么从这里进",
        "",
        contract["why_entry"],
        "",
        "## 节点顺序（从入口开始）",
        "",
        " → ".join(REASONING_NODE_LABELS[node] for node in contract["node_order"]),
        "",
        "## 要回答的问题",
        "",
    ]
    lines.extend(f"{index}. {question}" for index, question in enumerate(contract["questions"], start=1))
    lines.extend(["", "## 先做的动作", ""])
    lines.extend(f"{index}. {action}" for index, action in enumerate(contract["first_actions"], start=1))
    lines.extend(["", "## 停止条件", ""])
    lines.extend(f"- {condition}" for condition in contract["stop_conditions"])
    lines.extend(["", "## 边界", "", contract["boundary"]])
    return "\n".join(lines) + "\n"


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
    research_mode = research_entry_contract(
        text, stage=stage_info["stage"], stage_source=stage_info.get("source")
    )
    if domain_info["needs_domain"]:
        questions = ["你要研究的是软件、硬件、消费品、汽车还是手机/可穿戴产品？"]
        lowered_text = str(text or "").casefold()
        if any(word in lowered_text for word in ("全栈", "研发转型", "独立开发", "自己扛产品", "full-stack", "indie dev", "solo builder")):
            questions.append("研发转全栈：描述你的产品（如 CLI 工具、开源项目、SaaS、App）即可自动路由。")
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
            "research_mode": research_mode,
            "method_selection": research_method_selection(text, [], intent=intent_info["intent"]),
            "questions": questions,
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
    role_plan = role_catalog.recommend_roles(text, stage=stage_key, base_domain=str(domain_info["domain"]))
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
    next_commands.append(shlex.join([
        "askovo", "roles", "recommend", text,
        "--industry", role_plan["industry"]["id"], "--stage", stage_key,
        "--base-domain", str(domain_info["domain"]),
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
        "research_mode": research_mode,
        "industry_context": role_plan["industry"],
        "role_recommendation": role_plan,
        "risk_flags": risks,
        "safety_gate": "review" if requires_ack else "clear",
        "risk_notes": pack.get("risk_notes", []),
        "recommended_methods": selected,
        "method_selection": research_method_selection(text, selected, intent=intent_name),
        "alternatives": list(alternatives.values()),
        "decisions": stage_data.get("decisions", []),
        "deliverables": stage_data.get("deliverables", []),
        "questions": stage_data.get("decisions", []),
        "claim_boundaries": pack.get("claim_boundaries", []),
        "next_commands": next_commands,
        "catalog_version": method_catalog().get("schema_version", "1.0"),
        "platform_preview": platform_fit(
            text, str(domain_info["domain"]),
            require_bulk=intent_name == "collect",
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
        f"- 行业上下文：**{route.get('industry_context', {}).get('label_zh', '待确认')}**（`{route.get('industry_context', {}).get('id', 'unknown')}`）",
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
    role_plan = route.get("role_recommendation", {})
    if role_plan.get("assignments"):
        lines.extend(["", "## 岗位编排（工作分工，不是结论）", ""])
        for item in role_plan["assignments"]:
            lines.append(f"- **{item['id']} {item['name_zh']}**：{item['reason']}；产出：{'、'.join(item['primary_deliverables'])}")
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
    nodes["feature"].update({"capability": "待填写", "capabilities": [], "acceptance_conditions": [], "alternatives_considered": []})
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


FILL_CHECKLIST = {
    "scene": ["statement", "rationale", "trigger", "environment", "task_context"],
    "user": ["statement", "rationale", "role", "state", "decision_role"],
    "pain": ["statement", "rationale", "current_substitute", "friction_cost", "consequence"],
    "need": ["statement", "rationale", "desired_outcome", "constraints", "measure"],
    "feature": ["statement", "rationale", "capability", "capabilities",
                "acceptance_conditions", "alternatives_considered"],
    "product": ["statement", "rationale", "form", "scope", "non_goals",
                "acceptance_criteria"],
    "business": ["statement", "rationale", "market_definition", "target_segment",
                 "payer", "positioning", "revenue_model", "pricing_hypothesis",
                 "channels", "cost_drivers", "market_estimates",
                 "unit_economics_inputs", "success_metrics", "gate"],
}


def fill_checklist_markdown(study: dict[str, Any] | None = None) -> str:
    """The first-version fill guide for a new study.

    The scaffold is intentionally hypothesis-only; this checklist turns the
    JSON wall into an ordered task list. It does not invent any content.
    """
    study = study or {}
    title = str(study.get("title") or "当前研究")
    lines = [
        f"# 填写清单：{title}",
        "",
        "目标：先写出第一版可审主链，不追求“填满”。每个节点先写 `statement`（一句话判断）",
        "和 `rationale`（为什么由上一步推出），再补右侧字段；不知道的保留 `hypothesis`。",
        "",
        "## 1. study.json（先过合同门）",
        "",
        "- `decision.question`：这次到底要决定什么（一句话）",
        "- `decision.options`：至少两个选项，其中一个是“不做/维持现状”",
        "- `decision.owner` / `deadline` / `minimum_evidence`：谁拍板、何时、看到什么证据才敢拍",
        "- `scope.target_users` / `markets` / `languages` / `source_time_window`：研究边界",
        "- `scope.allowed_sources`：允许的来源（没有就留空，但设计门会提示）",
        "- `hypotheses[].statement` / `falsified_if`：至少一条可证伪假设",
        "- `stopping_rules` / `restart_rules`：什么时候停、什么条件下重启",
        "",
        "## 2. product-reasoning.json（七节点，按顺序填）",
        "",
        "| 节点 | 必须填的字段 | 一句话写法 |",
        "|---|---|---|",
        "| 场景 | statement / rationale / trigger / environment / task_context | 当 X 触发时，Y 环境里的 Z 角色要完成 T |",
        "| 用户 | statement / rationale / role / state / decision_role | 是这个角色/状态，而不是泛人口画像；谁做决定 |",
        "| 痛点 | statement / rationale / current_substitute / friction_cost / consequence | 现在用 A 替代，卡在 B，导致 C |",
        "| 需求 | statement / rationale / desired_outcome / constraints / measure | 要的是结果 R，受约束 C，用 M 衡量 |",
        "| 特性 | statement / rationale / capability / capabilities / acceptance_conditions / alternatives_considered | 能力 A 通过机制 M 改变结果 R；替代方案是什么 |",
        "| 产品 | statement / rationale / form / scope / non_goals / acceptance_criteria | 这些特性为什么组合成这个形态；不做什么 |",
        "| 商业 | statement / rationale / market_definition / target_segment / payer / positioning / revenue_model / pricing_hypothesis / channels / cost_drivers / market_estimates / unit_economics_inputs / success_metrics / gate | 市场边界、谁付钱、怎么收钱、成本与 Gate |",
        "",
        "## 3. 最小可审顺序",
        "",
        "1. 先填 `scene → user → pain → need` 四段，跑 `askovo check . --stage design`；",
        "2. 再补 `feature → product → business`，每补一段重跑一次；",
        "3. 商业数字没有总体、时间窗、单位、公式和来源时，保持 `hypothesis`，不要编。",
        "",
        "## 4. 命令",
        "",
        "```bash",
        "askovo check . --stage design",
        "askovo chain .",
        "askovo deliver . --kind plan   # 审计通过后再作为正式交付",
        "```",
        "",
        "字段的机器真值仍是 `04-findings/product-reasoning.json`；本清单只做填写顺序，不产生第二套结论。",
        "",
    ]
    return "\n".join(lines)


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
            f"负责人：{_gap_or_value(gate.get('owner'), '无法确定谁对投入负责', '补写负责人', compact=True)}；"
            f"资源承诺：{_gap_or_value(gate.get('resource_commitment'), '无法核对投入的人力和预算', '补写已承诺的人力和预算', compact=True)}；"
            f"复审触发：{_gap_or_value(gate.get('revisit_trigger'), '无法知道何时重新评审', '补写复审触发条件', compact=True)}"
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
            method = _gap_or_value(
                prioritization.get("method"), "无法核对优先级比较方法", "补写优先级比较方法", compact=True
            )
            owner = _gap_or_value(
                prioritization.get("owner"), "无法确定谁做的优先级判断", "补写优先级负责人", compact=True
            )
            rationale = _gap_or_value(
                prioritization.get("rationale"), "无法复核为什么选这条链路", "补写选择这条链路的理由", compact=True
            )
            line = f"- 优先级：方法 {method}；负责人 {owner}；理由 {rationale}"
            factors = prioritization.get("factors", {})
            if not _delivery_missing(factors):
                line += f"；因素 {_delivery_value(factors)}"
            lines.append(line)
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
    body = _product_chain_lines(data)
    return "\n".join(
        [f"# {title}", ""] + body + [
            "",
            "## 边界",
            "",
            "本文件是七节点链的直接渲染，不证明总体比例、市场规模、因果或产品成功；"
            "节点状态是研究口径，不是发布依据；决定与签收仍由负责人完成并留痕。",
        ]
    ) + "\n"


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
        "industry_context": route.get("industry_context", {}).get("id"),
        "lifecycle_stage": route["stage"],
        "research_mode": route.get("research_mode", {}),
        "recommended_roles": [item["id"] for item in route.get("role_recommendation", {}).get("assignments", [])],
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
    (study_dir / "01-sources" / "fill-checklist.md").write_text(
        fill_checklist_markdown(study), encoding="utf-8")
    if (study.get("research_mode") or {}).get("mode") == "discover":
        opportunity = opportunity_map_contract(study)
        (study_dir / "04-findings" / "opportunity-map.json").write_text(
            json.dumps(opportunity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (study_dir / "04-findings" / "opportunity-map.md").write_text(
            opportunity_map_markdown(opportunity), encoding="utf-8")
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
- 行业上下文：{route.get('industry_context', {}).get('label_zh', '待确认')} (`{route.get('industry_context', {}).get('id', 'unknown')}`)
- 阶段：{route['stage_label']} (`{route['stage']}`)
- 研究模式：{(route.get('research_mode') or {}).get('mode_label', '待确认')}（入口：{(route.get('research_mode') or {}).get('entry_label', '待确认')}）
- 方法：{', '.join(item['name'] for item in selected)}
- 安全门：`{route['safety_gate']}`

## 产品推理主链

场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业

先填写 `04-findings/product-reasoning.json`：每个节点都要有判断、推导理由、状态和假设；再针对最薄弱的节点设计采集与分析。字段顺序与最小可审顺序见 [`01-sources/fill-checklist.md`](01-sources/fill-checklist.md)。

## 岗位执行包

确认主链后运行 `askovo roles scaffold .` 原子生成 `01-sources/role-workbench/`：角色分工、KPI 定义（目标为 null）、SOP 质量门和交付模板；它们只组织工作，不替代主链与专业签收。多链时需加 `--chain PRxx`。

## 下一步

```bash
askovo chain .
askovo roles recommend "{route['query']}" --stage {route['stage']}
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
    role_workbench_command = shlex.join(["askovo", "roles", "scaffold", str(study_dir)])
    return {
        "status": "created",
        "study_dir": str(study_dir),
        "study_id": study_id,
        "domain": route["domain"],
        "industry_context": study.get("industry_context"),
        "role_workbench_command": role_workbench_command,
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
        f"- 研究模式：{(route.get('research_mode') or {}).get('mode_label', '待确认')}（入口：{(route.get('research_mode') or {}).get('entry_label', '待确认')}）",
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
    method_choice = route.get("method_selection") if isinstance(route.get("method_selection"), dict) else {}
    if method_choice:
        lines.extend(["", "## 5A. 研究问题 → 样本形成 → 方法 → 结论边界", ""])
        for profile in method_choice.get("sample_formation_mechanisms") or []:
            lines.append(f"- 样本形成 `{profile.get('id')}`：{profile.get('description')}")
            lines.append("  - 选择偏差：" + "；".join(str(item) for item in profile.get("selection_bias") or []))
        for method in method_choice.get("applicable_methods") or []:
            lines.append(f"- 适用方法 **{method.get('name') or method.get('id')}**：{method.get('research_question')}")
            for boundary in method.get("conclusion_boundary") or []:
                lines.append(f"  - 结论边界：{boundary}")
        for boundary in method_choice.get("conclusion_boundaries") or []:
            lines.append(f"- 总结边界：{boundary}")
        lines.append("- 报价/交付实验的选择偏差登记字段：" + ", ".join(method_choice.get("selection_bias_fields") or []))
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


def _first_nonempty(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Read the first non-empty scalar field, tolerating author objects."""
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            value = (value.get("name") or value.get("displayName") or value.get("login")
                     or value.get("handle") or value.get("username") or "")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _raw_text(raw: dict[str, Any]) -> str:
    """Canonical text extraction for imported material.

    A title alone is not reproducible evidence text. Platform normalization may
    deliberately keep title-only posts, but the generic import path must not.
    """
    return _first_nonempty(raw, (
        "text", "text_excerpt", "body", "selftext", "content", "quote",
        "message", "comment", "内容",
    ))


def _raw_created_at(raw: dict[str, Any]) -> str:
    value = _first_nonempty(raw, (
        "created_at", "published_at", "source_time", "created", "timestamp",
        "created_utc", "datetime", "date", "time", "published_time", "date_text",
    ))
    if not value:
        return ""
    try:
        if value.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    return value


def _raw_source_url(raw: dict[str, Any]) -> str:
    return _first_nonempty(raw, ("source_url", "url", "html_url", "permalink", "link", "href"))


def _raw_author(raw: dict[str, Any]) -> str:
    return _first_nonempty(raw, ("author", "author_name", "username", "handle", "user"))


def _normalize_record(raw: dict[str, Any], index: int, defaults: dict[str, str],
                      level_cap: str | None = None) -> dict[str, Any]:
    text = _raw_text(raw)
    created_at = _raw_created_at(raw)
    record_id = _first_nonempty(raw, ("record_id", "id", "记录编号", "记录ID", "编号")) \
        or f"{defaults['source_family']}-{index:04d}"
    form = _first_nonempty(raw, ("evidence_form", "证据形式")) or defaults["evidence_form"]
    form = str(form).strip() or "self_report"
    cap = level_cap
    if level_cap:
        row_cap = IMPORT_LEVEL_CAPS.get(form, "E2")
        if IMPORT_LEVEL_ORDER[row_cap] < IMPORT_LEVEL_ORDER[level_cap]:
            cap = row_cap
    level_declared = _first_nonempty(raw, ("evidence_level", "证据等级")).strip().upper()
    if level_declared and level_declared not in IMPORT_LEVEL_ORDER:
        raise ImportReviewError(
            f"record {record_id}: unknown evidence_level {level_declared!r}",
            "INVALID_INPUT", "E0, E1, E2, E3, E4-, E4+, E5")
    level = level_declared or defaults.get("evidence_level") or "unclassified"
    requested_level = level
    capped_from = ""
    if cap and level in IMPORT_LEVEL_ORDER and IMPORT_LEVEL_ORDER[level] > IMPORT_LEVEL_ORDER[cap]:
        capped_from = level
        level = cap
    level_basis = f"import derivation: form={form}, cap={cap}"
    if capped_from:
        level_basis += f"; declared {capped_from} capped to {cap}"
    if form in TRANSACTION_FORMS and IMPORT_LEVEL_ORDER.get(level, 0) >= IMPORT_LEVEL_ORDER["E4-"]:
        missing = _missing_transaction_fields(raw)
        if missing:
            level_basis += ("; transaction structure incomplete: missing "
                            f"{', '.join(missing)}; {level} held at E2")
            level = "E2"
    record = {
        "record_id": record_id,
        "context_key": str(raw.get("context_key") or defaults.get("context_key") or ""),
        "user_role": str(raw.get("user_role") or raw.get("角色") or "unknown"),
        "scene_trigger": str(raw.get("scene_trigger") or raw.get("scene") or "unknown"),
        "task_outcome": str(raw.get("task_outcome") or raw.get("task") or "unknown"),
        "current_substitute": str(raw.get("current_substitute") or "unknown"),
        "friction_cost": str(raw.get("friction_cost") or raw.get("friction") or "unknown"),
        "consequence": str(raw.get("consequence") or "unknown"),
        "evidence_level": level,
        "level_declared": requested_level,
        "requested_evidence_level": requested_level,
        "level_derivation_version": "askovo-import-derivation/2",
        "level_basis": level_basis,
        "evidence_basis": str(raw.get("evidence_basis") or "imported; grade before use"),
        "corpus_role": str(raw.get("corpus_role") or defaults.get("corpus_role") or "open_scene"),
        "source_family": _first_nonempty(raw, ("source_family", "source", "来源")) or defaults["source_family"],
        "source_ref": str(raw.get("source_ref") or defaults["source_ref"]),
        "source_url": _raw_source_url(raw),
        "author_hash": str(raw.get("author_hash") or _hash_author(_raw_author(raw))),
        "created_at": created_at,
        # created_at 只表示内容发生时间；collected_at 单独保留采集时间，不能互相补齐。
        "collected_at": _first_nonempty(raw, ("collected_at", "采集时间", "收集时间")) or created_at,
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
        record["normalized_text_hash"] = _import_text_hash(record)
    return record


def _import_text_hash(record: dict[str, Any]) -> str:
    text = str(record.get("text") or record.get("record_id") or "")
    normalized = " ".join(text.split())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ImportReviewError(ValueError):
    """An import review rule was violated; carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INPUT_REQUIRED",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


# What an imported file can honestly support, by evidence form. A pasted
# self-report states a need (E1) and can document current practice (E2); it
# can never prove acceptance (E3) or payment (E4+/E5). Transaction exports
# are system records and may carry commercial levels.
IMPORT_LEVEL_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4-": 4, "E4+": 4, "E5": 5}
IMPORT_LEVEL_CAPS = {
    "self_report": "E2",
    "behavior_log": "E2",
    "transaction": "E5",
    "purchase": "E5",
}

# A transaction/purchase export earns commercial grades (E4-/E4+/E5) only when
# each row itself says what was traded, when, with whom, how much, and where the
# voucher sits. `--evidence-form transaction` is an operator claim about the
# file; these row fields are the checkable structure behind it. Rows missing any
# of them are held at E2 (documented practice), never at the form's cap.
TRANSACTION_FORMS = ("transaction", "purchase")
TRANSACTION_STRUCTURE_FIELDS = {
    "counterparty": ("counterparty", "vendor", "交易对象", "对方"),
    "occurred_at": ("occurred_at", "event", "date", "交易日期", "事件时间"),
    "amount": ("amount", "total", "金额"),
    "source_ref": ("source_ref", "来源"),
    "evidence_ref": ("evidence_ref", "voucher", "凭证定位"),
}


def _missing_transaction_fields(raw: dict[str, Any]) -> list[str]:
    """Judge structure from the row's own fields; defaults never fill the gap."""
    missing: list[str] = []
    for name, aliases in TRANSACTION_STRUCTURE_FIELDS.items():
        if not any(str(raw.get(alias) if raw.get(alias) is not None else "").strip(" \t")
                   for alias in aliases):
            missing.append(name)
    return missing


def _ensure_imported_source_plan(study_dir: Path, family: str, record_count: int) -> None:
    """Declare an imported source family before its records become evidence.

    The audit refuses evidence from a source family the plan never named; the
    import command is the human act that declares it (idempotent).
    """
    path = study_dir / "01-sources" / "source-plan.csv"
    rows: list[dict[str, str]] = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)
                    if str(row.get("source_family") or "").strip()]
    if any(str(row.get("source_family")) == family for row in rows):
        return
    fields = ("corpus_role", "source_family", "route_or_query", "target_records",
              "cap_share", "access_status", "known_bias")
    rows.append({
        "corpus_role": "open_scene",
        "source_family": family,
        "route_or_query": "local import reviewed by the operator",
        "target_records": str(record_count),
        "cap_share": "0.50",
        "access_status": "operator-provided local file",
        "known_bias": "operator-selected material; selection bias is explicit, not corrected",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def import_material(
    study_dir: Path,
    file_path: Path,
    source_family: str = "imported",
    evidence_form: str = "self_report",
    claim_type: str = "need",
    method_id: str = "imported",
    evidence_level: str = "E1",
    corpus_role: str = "open_scene",
    context_key: str = "",
) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    # A page-capture/OCR candidate has exactly one admission route. Generic
    # import must not relabel it as paste or bypass the named-review join.
    candidate_path = file_path.resolve()
    capture_root = (study_dir / "01-sources" / "captures").resolve()
    is_capture_file = False
    try:
        candidate_path.relative_to(capture_root)
        is_capture_file = True
    except ValueError:
        pass
    if not is_capture_file and file_path.suffix.lower() == ".json":
        try:
            candidate_document = json.loads(file_path.read_text(encoding="utf-8"))
            is_capture_file = isinstance(candidate_document, dict) and (
                candidate_document.get("schema") == "askovo.page-capture/1")
        except (OSError, json.JSONDecodeError):
            is_capture_file = False
    if str(source_family).strip() == "capture" or is_capture_file:
        raise ImportReviewError(
            "page-capture/OCR candidates require `askovo capture accept --by NAME "
            "--evidence-level ...`; generic import cannot admit them",
            "POLICY_DENIED")
    level = str(evidence_level or "E1").strip().upper()
    if level not in IMPORT_LEVEL_ORDER:
        raise ImportReviewError(
            f"unknown evidence_level {level!r}", "INPUT_REQUIRED",
            "E0, E1, E2, E3, E4-, E4+, E5")
    cap = IMPORT_LEVEL_CAPS.get(str(evidence_form or "self_report"), "E2")
    if IMPORT_LEVEL_ORDER[level] > IMPORT_LEVEL_ORDER[cap]:
        raise ImportReviewError(
            f"an imported {evidence_form} cannot support evidence_level {level} "
            f"(cap {cap})", "POLICY_DENIED",
            "acceptance (E3) needs concept tests; payment (E4+/E5) needs transaction "
            "records, not a pasted self-report")
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
        "evidence_level": level,
        "corpus_role": corpus_role,
        "context_key": context_key,
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
            records.append(_normalize_record(raw, index, defaults, level_cap=cap))
    elif suffix == ".csv":
        with file_path.open(encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=1):
                records.append(_normalize_record(dict(row), index, defaults, level_cap=cap))
    else:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        records.append(_normalize_record({"text": text, "record_id": file_path.stem}, 1,
                                            defaults, level_cap=cap))

    evidence_path = study_dir / "02-data" / "evidence.jsonl"
    existing_by_id: dict[str, dict[str, Any]] = {}
    existing_by_text: dict[str, dict[str, Any]] = {}
    if evidence_path.is_file():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            record_id = str(existing.get("record_id") or "")
            if record_id:
                existing_by_id[record_id] = existing
                existing_by_text.setdefault(_import_text_hash(existing), existing)
    accepted: list[dict[str, Any]] = []
    duplicates: list[dict[str, str]] = []
    for record in records:
        record_id = str(record["record_id"])
        text_hash = _import_text_hash(record)
        previous_id = existing_by_id.get(record_id)
        if previous_id is not None and _import_text_hash(previous_id) != text_hash:
            raise ImportReviewError(
                f"证据编号 {record_id} 已存在，但正文不同；拒绝整批导入，未新增或覆盖证据",
                "CONFLICT", "核对原始记录后使用新编号，或先撤销错误记录")
        previous_text = existing_by_text.get(text_hash)
        if previous_text is not None and str(previous_text.get("record_id")) != record_id:
            duplicates.append({"record_id": record_id,
                               "duplicate_of": str(previous_text.get("record_id") or ""),
                               "reason": "same_text"})
            continue
        if previous_id is not None:
            duplicates.append({"record_id": record_id, "duplicate_of": record_id,
                               "reason": "same_record_id"})
            continue
        accepted.append(record)
        existing_by_id[record_id] = record
        existing_by_text[text_hash] = record
    with evidence_path.open("a", encoding="utf-8") as handle:
        for record in accepted:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    added = len(accepted)
    for family in {str(record.get("source_family") or source_family) for record in records}:
        _ensure_imported_source_plan(study_dir, family, added or len(records))
    row_levels = [str(record.get("evidence_level") or "") for record in records]
    row_level_max = max(row_levels, key=lambda value: IMPORT_LEVEL_ORDER.get(value, -1),
                        default="unclassified")
    structure_downgrades = sum(
        1 for record in records
        if "transaction structure incomplete" in str(record.get("level_basis") or ""))
    return {
        "status": "imported",
        "file": str(file_path),
        "raw_copy": str(raw_copy),
        "parsed": len(records),
        "added": added,
        "skipped_duplicates": len(records) - added,
        "duplicates": duplicates,
        "evidence_file": str(evidence_path),
        "review": {
            "evidence_level": row_level_max,
            "requested_level": level,
            "evidence_form": evidence_form,
            "corpus_role": corpus_role,
            "level_cap": cap,
            "row_level_rule": "a row's evidence_level is capped by its evidence form and "
                              "the command's form; an unknown level rejects the file",
            "structure_rule": "transaction/purchase rows reach E4-/E4+/E5 only when the row "
                              "itself carries counterparty, date/event, amount, source and "
                              "voucher location; otherwise the row is held at E2",
            "structure_downgrades": structure_downgrades,
            "note": "operator-reviewed import; the level is capped by the evidence form "
                    "and by the row's own transaction structure",
        },
        "source_plan": str(study_dir / "01-sources" / "source-plan.csv"),
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


EVIDENCE_LEVELS = frozenset({"E0", "E1", "E2", "E3", "E4+", "E4-", "E5"})
COMMERCIAL_EVIDENCE_LEVELS = frozenset({"E4+", "E5"})


def is_qualified_evidence(record: dict[str, Any]) -> bool:
    """The single evidence-validity rule shared by audit (`check`) and delivery.

    A record counts as decision evidence only when it is registered in
    02-data/evidence.jsonl with a valid evidence_level. Collection rows that
    live only in normalized.jsonl are inventory, not basis: collecting is not
    having evidence (review 2026-11-04, A-1).
    """
    record_id = str(record.get("record_id") or "")
    return bool(record_id) and str(record.get("evidence_level") or "") in EVIDENCE_LEVELS


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    context = study_context.current_study_context()
    if context is not None and context.owns(path):
        if not path.is_file():
            return []
        return context.read_jsonl(path)
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            rows.append(record)
    return rows


def evidence_store_integrity(study_dir: Path) -> dict[str, Any]:
    """Check that evidence.jsonl can be read without losing records.

    A malformed line is not "one bad row": it means the store may be missing a
    record the conclusion depends on. The answer path must refuse a trusted
    conclusion instead of silently skipping it (review 2026-11-18, A-09).
    """
    path = Path(study_dir) / "02-data" / "evidence.jsonl"
    problems: list[dict[str, Any]] = []
    if not path.is_file():
        return {"valid": True, "problems": problems, "path": str(path)}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append({"line": lineno, "code": "invalid_json",
                             "detail": str(exc)[:200]})
            continue
        if not isinstance(item, dict):
            problems.append({"line": lineno, "code": "not_an_object",
                             "detail": type(item).__name__})
    return {"valid": not problems, "problems": problems, "path": str(path)}


def load_evidence_store(study_dir: Path) -> dict[str, Any]:
    """One evidence-store definition for audit and delivery (A-1 convergence).

    qualified records come from evidence.jsonl and must pass
    is_qualified_evidence; collected records come from normalized.jsonl and
    are everything not already qualified. Delivery may draw decision basis
    from qualified records only; collected rows must never be rendered as
    basis, so the two commands can no longer disagree on validity.
    """
    study_dir = Path(study_dir)
    qualified: list[dict[str, Any]] = []
    qualified_ids: set[str] = set()
    for record in _read_jsonl_rows(study_dir / "02-data" / "evidence.jsonl"):
        if record.get("retracted"):
            continue
        record_id = str(record.get("record_id") or "")
        if is_qualified_evidence(record) and record_id not in qualified_ids:
            qualified_ids.add(record_id)
            qualified.append(record)
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in _read_jsonl_rows(study_dir / "02-data" / "normalized.jsonl"):
        key = str(record.get("record_id") or record.get("normalized_text_hash") or "")
        if not key or key in seen or str(record.get("record_id") or "") in qualified_ids:
            continue
        seen.add(key)
        collected.append(record)
    return {
        "count": len(qualified),
        "records": qualified,
        "collected_count": len(collected),
        "collected_records": collected,
    }


def _evidence_summary(study_dir: Path) -> dict[str, Any]:
    # A-1: audit 与 deliver 共用 load_evidence_store 这一条读取路径（唯一有效性规则）
    store = load_evidence_store(study_dir)
    records = store["records"]
    by_form: dict[str, int] = {}
    by_claim: dict[str, int] = {}
    for record in records:
        form = _evidence_form(record)
        claim = _evidence_claim(record)
        by_form[form] = by_form.get(form, 0) + 1
        by_claim[claim] = by_claim.get(claim, 0) + 1
    return {
        "count": len(records),
        "by_form": by_form,
        "by_claim": by_claim,
        "records": records,
        # A-1: 采集库存单独披露（采集 ≠ 证据，不计入依据）
        "collected_count": store.get("collected_count", 0),
        "collected_records": store.get("collected_records", []),
        # A-01 正交资格投影：三属性 + needs_requalification 标记（不改写原值）
        "qualification": evidence_qualification(records),
    }


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


def chain_cited_evidence_ids(reasoning: dict[str, Any] | None) -> list[str]:
    """Every evidence id the chains cite, in citation order (nodes + counter)."""
    ordered_ids: list[str] = []
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        for node_name in REASONING_NODES:
            node = nodes.get(node_name, {}) if isinstance(nodes, dict) else {}
            if isinstance(node, dict):
                ordered_ids.extend(str(value) for value in node.get("evidence_ids", []) if str(value))
        ordered_ids.extend(
            str(value) for value in chain.get("counter_evidence_ids", []) if str(value)
        )
    return ordered_ids


def _unresolved_chain_references(
    reasoning: dict[str, Any] | None, evidence: dict[str, Any]
) -> list[str]:
    """Chain-cited ids that resolve to no qualified evidence record.

    The audit reports exactly these as `references unknown evidence`; the
    delivery must surface the same set instead of rendering those records as
    basis, so the two commands cannot disagree on evidence validity (A-1).
    """
    qualified_ids = {str(record.get("record_id")) for record in evidence.get("records", [])}
    return [value for value in dict.fromkeys(chain_cited_evidence_ids(reasoning)) if value not in qualified_ids]


DELIVERY_PLACEHOLDERS = frozenset(
    {"待填写", "待确认", "未记录", "未关联", "未设置", "tbd", "todo", "none", "null", "n/a"}
)


def _delivery_missing(value: Any) -> bool:
    """True when a delivery value gives the reader nothing to work with."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        if text.lower() in DELIVERY_PLACEHOLDERS:
            return True
        return text.startswith(("待填写", "待确认"))
    if isinstance(value, dict):
        return not value or all(_delivery_missing(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return not value or all(_delivery_missing(item) for item in value)
    return False


def _delivery_value(value: Any) -> str:
    """Render a value as business text; `[]`, `{}` and `None` never reach the page."""
    if isinstance(value, dict):
        parts = [
            f"{key}：{_delivery_value(item)}" for key, item in value.items() if not _delivery_missing(item)
        ]
        return "；".join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        parts = [_delivery_value(item) for item in value if not _delivery_missing(item)]
        return "；".join(part for part in parts if part)
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _gap_note(impact: str, action: str, compact: bool = False) -> str:
    """State what is missing, why it matters, and how to add it."""
    if compact:
        return f"未提供｜补充方式：{action}"
    return f"未提供｜影响：{impact}｜补充方式：{action}"


def _gap_or_value(value: Any, impact: str, action: str, compact: bool = False) -> str:
    if _delivery_missing(value):
        return _gap_note(impact, action, compact=compact)
    return _delivery_value(value)


def _missing_fields(rows: list[tuple[str, Any]]) -> list[str]:
    return [label for label, value in rows if _delivery_missing(value)]


def _delivery_gap_block(
    chain_id: Any, labels: list[str], guide: dict[str, tuple[str, str]]
) -> list[str]:
    """Per-chain list of what this document could not fill in."""
    if not labels:
        return []
    lines = ["**材料缺口（本篇未提供的内容）**", ""]
    for label in labels:
        impact, action = guide[label]
        lines.append(f"- {chain_id} · {label}：{_gap_note(impact, action)}")
    lines.extend(["", "> 缺口不是结论：补齐前，相应判断保持待验证。", ""])
    return lines


BRD_FIELD_GUIDE: dict[str, tuple[str, str]] = {
    "产品→商业结论": ("无法判断这条链是否值得投入", "在商业环节补一句话结论"),
    "产品→商业的推导": ("无法复核这条结论为什么成立", "补写从产品到商业的推导理由"),
    "决策人": ("无法确定谁对投入负责", "补写对这次投入负责的人"),
    "资源承诺": ("无法核对投入的人力和预算", "补写已承诺的人力和预算"),
    "复审触发": ("无法知道什么条件下需要重新评审", "补写触发重新评审的条件"),
    "商业证据": (
        "商业判断没有可核对的成交或付费依据",
        "用 askovo chain-node <study> bind-evidence --node business 绑定证据",
    ),
    "需求判断": ("商业结论无法回溯到需求依据", "关联支撑这条商业判断的需求判断"),
    "下一项商业/产品验证": ("无法安排下一轮降低不确定性的验证", "补写下一项要做的商业或产品验证"),
}

MRD_FIELD_GUIDE: dict[str, tuple[str, str]] = {
    "市场定义": ("无法判断这里说的市场指哪一群人、哪笔支出", "用一句话界定市场边界"),
    "地理范围": ("无法判断结论适用于哪些地区", "列出覆盖的国家或地区"),
    "时间窗": ("无法判断数据对应哪段时间", "写明数据覆盖的起止时间"),
    "纳入市场": ("无法知道这次分析包含哪些市场", "列出纳入分析的市场"),
    "排除市场": ("无法知道这次分析有意排除了什么", "列出排除的市场及原因"),
    "目标细分": ("无法判断先服务哪一群人", "写清最先切入的细分人群"),
    "细分定义": ("无法核对细分人群的边界和规模口径", "给出每个细分的定义与划分依据"),
    "付费者": ("无法判断谁掏钱、谁使用", "写清付费方与使用方是否同一人"),
    "竞争定位": ("无法判断客户为什么选你而不是替代方案", "写清相对替代方案的定位"),
    "竞争与替代": ("无法核对客户现在用什么解决问题", "列出客户当前的替代做法"),
    "渠道": ("无法判断客户从哪里触达和购买", "列出计划使用的触达与成交渠道"),
    "价格假设": ("无法判断这一定价的依据", "写清价格假设及其依据"),
    "价格口径": ("无法复核对账用的价格记录", "按币种、单位、周期列出价格"),
    "市场估计口径": ("无法复核任何市场规模数字", "补总体、时间窗、单位、公式、来源与推断范围"),
}

PRD_FIELD_GUIDE: dict[str, tuple[str, str]] = {
    "特性主张": ("无法判断这次到底要做什么", "补写一句话特性主张"),
    "能力承诺": ("无法判断这项特性承诺到什么程度", "补写能力承诺的边界"),
    "逐条能力说明": ("无法判断每条能力解决哪个需求", "补写每条能力做什么、对应哪个需求"),
    "产品形态": ("无法判断交付物长什么样", "写清产品以什么形态交付"),
    "范围": ("无法判断这次做到哪里为止", "写清本次交付范围"),
    "非目标": ("无法判断明确不做什么", "列出本次明确不做的内容"),
}


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
        chain_id = chain.get("id", "PR?")
        gate = business.get("gate", {}) if isinstance(business.get("gate"), dict) else {}
        evidence_ids = [f"`{item}`" for item in business.get("evidence_ids", []) if str(item).strip()]
        demand_id = chain.get("demand_judgment_id")
        field_rows = [
            ("产品→商业结论", business.get("statement")),
            ("产品→商业的推导", business.get("rationale")),
            ("决策人", gate.get("owner")),
            ("资源承诺", gate.get("resource_commitment")),
            ("复审触发", gate.get("revisit_trigger")),
            ("商业证据", evidence_ids),
            ("需求判断", f"`{demand_id}`" if not _delivery_missing(demand_id) else demand_id),
            ("下一项商业/产品验证", chain.get("next_test")),
        ]
        statement_impact, statement_action = BRD_FIELD_GUIDE["产品→商业结论"]
        statement = _gap_or_value(
            business.get("statement"), statement_impact, statement_action, compact=True
        )
        lines.extend([f"### {chain_id} · {statement}", ""])
        lines.extend(_delivery_gap_block(chain_id, _missing_fields(field_rows), BRD_FIELD_GUIDE))
        lines.append(f"- 商业门：`{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}`")
        for label, value in field_rows[1:]:
            impact, action = BRD_FIELD_GUIDE[label]
            lines.append(f"- {label}：{_gap_or_value(value, impact, action)}")
        records = [item for item in data.get("decision_records") or []
                   if isinstance(item, dict) and item.get("chain_id") == chain_id]
        if records:
            record = max(records, key=lambda item: int(item.get("version") or 0))
            lines.extend([
                "- 已登记决策（不代表执行或结果已验收）：",
                f"  - 记录：`{record.get('record_id') or '未登记'}`；决策人：{record.get('decision_maker') or '未登记'}",
                f"  - 决定：{record.get('decision') or '未登记'}",
                f"  - 下一动作：{record.get('next_action') or '未登记'}",
            ])
        lines.append("")
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
        chain_id = chain.get("id", "PR?")
        field_rows = [
            ("市场定义", business.get("market_definition")),
            ("地理范围", business.get("geographies", [])),
            ("时间窗", business.get("time_window")),
            ("纳入市场", business.get("included_markets", [])),
            ("排除市场", business.get("excluded_markets", [])),
            ("目标细分", business.get("target_segment")),
            ("细分定义", business.get("segments", [])),
            ("付费者", business.get("payer")),
            ("竞争定位", business.get("positioning")),
            ("竞争与替代", business.get("competitive_alternatives", [])),
            ("渠道", business.get("channels", [])),
            ("价格假设", business.get("pricing_hypothesis")),
            ("价格口径", business.get("pricing", [])),
            ("市场估计口径", business.get("market_estimates", [])),
        ]
        lines.extend([f"### {chain_id} 的市场边界与选择", ""])
        lines.extend(_delivery_gap_block(chain_id, _missing_fields(field_rows), MRD_FIELD_GUIDE))
        for label, value in field_rows:
            impact, action = MRD_FIELD_GUIDE[label]
            lines.append(f"- {label}：{_gap_or_value(value, impact, action)}")
        lines.append("")
    lines.extend(
        [
            "MRD 是商业节点中市场部分的候选基线与选择视图；它不证明用户需求、产品成功或精确市场规模。",
            "所有数字必须带总体、抽样框、时间窗、单位、公式、来源和推断范围；未知保留为未知，不用 0 或假精确值补齐。",
            "",
        ]
    )
    return lines


def _prd_lines(data: dict[str, Any]) -> list[str]:
    """Project need→feature→product nodes as a requirements view with a
    copy-paste acceptance checklist; a read-only projection of the chain,
    never test-case or release authorship."""
    lines = ["## 2. PRD 需求与验收（开发视图）", ""]
    chains = data.get("chains", [])
    rendered = False
    for chain in chains if isinstance(chains, list) else []:
        if not isinstance(chain, dict):
            continue
        nodes = chain.get("nodes", {})
        nodes = nodes if isinstance(nodes, dict) else {}
        feature = nodes.get("feature") if isinstance(nodes.get("feature"), dict) else {}
        product = nodes.get("product") if isinstance(nodes.get("product"), dict) else {}
        if not feature and not product:
            continue
        rendered = True
        chain_id = chain.get("id", "PR?")
        lines.extend([f"### {chain_id} 需求基线", ""])
        field_rows: list[tuple[str, Any]] = []
        capability_lines: list[str] = []
        capability_gaps = False
        capabilities = feature.get("capabilities") if feature else None
        for cap in capabilities if isinstance(capabilities, list) else []:
            if not isinstance(cap, dict):
                continue
            what = cap.get("what")
            if _delivery_missing(what):
                capability_gaps = True
            cap_impact, cap_action = PRD_FIELD_GUIDE["逐条能力说明"]
            entry = f"- 逐条能力 {cap.get('name') or '未命名'}：{_gap_or_value(what, cap_impact, cap_action, compact=True)}"
            if cap.get("solves"):
                entry += f"（对应：{cap.get('solves')}）"
            capability_lines.append(entry)
        if feature:
            field_rows.extend(
                [("特性主张", feature.get("statement")), ("能力承诺", feature.get("capability"))]
            )
        if product:
            field_rows.extend(
                [
                    ("产品形态", product.get("form")),
                    ("范围", product.get("scope")),
                    ("非目标", product.get("non_goals", [])),
                ]
            )
        gap_labels = _missing_fields(field_rows)
        if capability_gaps:
            gap_labels.insert(2 if feature else 0, "逐条能力说明")
        lines.extend(_delivery_gap_block(chain_id, gap_labels, PRD_FIELD_GUIDE))
        values = dict(field_rows)

        def _prd_field(label: str) -> str:
            impact, action = PRD_FIELD_GUIDE[label]
            shown = "非目标（不做什么）" if label == "非目标" else label
            return f"- {shown}：{_gap_or_value(values[label], impact, action)}"

        if feature:
            lines.extend([_prd_field("特性主张"), _prd_field("能力承诺")])
            lines.append(f"- 状态：`{feature.get('status', 'unknown')}`")
            lines.extend(capability_lines)
            lines.append("")
        if product:
            lines.extend([_prd_field(label) for label in ("产品形态", "范围", "非目标")])
            lines.append(f"- 状态：`{product.get('status', 'unknown')}`")
            lines.append("")
        lines.extend(
            [
                f"**{chain_id} 验收清单（可直接粘贴到 issue / 任务列表）**",
                "",
                f"来源：`product-reasoning.json#chains/{chain_id}/nodes`（只读投影，改验收先改主链）",
                "",
            ]
        )
        items: list[tuple[str, str]] = []
        feature_conditions = feature.get("acceptance_conditions")
        if isinstance(feature_conditions, list):
            items.extend((str(item), "特性接受条件") for item in feature_conditions)
        product_criteria = product.get("acceptance_criteria")
        if isinstance(product_criteria, list):
            items.extend((str(item), "产品验收标准") for item in product_criteria)
        if items:
            for item, source in items:
                lines.append(f"- [ ] {item}（{source}）")
        else:
            lines.append(
                "- 验收清单为空：主链尚未写 acceptance_conditions / acceptance_criteria；"
                "这是尚未定义，不是没有验收。"
            )
        lines.append("")
    if not rendered:
        lines.append("特性/产品节点尚未建立；先完成需求到特性、特性到产品的推导，再生成 PRD。")
    lines.extend(
        [
            "验收清单是研究侧验收参数的只读投影：勾选完成不等于需求已验证、工程放行或发布就绪。",
            "工程实现标准、测试用例与放行决定由研发与负责人另行制定；每条特性的证据强度与推导理由以主链为准。",
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
TOTAL_COST_PATTERN = re.compile(r"total|合计|总计|sum", re.IGNORECASE)
GROSS_PROFIT_PATTERN = re.compile(r"毛利|gross\s*profit", re.IGNORECASE)
MARGIN_RATE_PATTERN = re.compile(r"毛利\s*率|利润率|margin", re.IGNORECASE)
ROI_PATTERN = re.compile(r"\broi\b|回报率|投资回报", re.IGNORECASE)
PRICE_NAME_PATTERN = re.compile(r"price|pricing|价格|单价|售价|定价|月费|年费|订阅费", re.IGNORECASE)
ECONOMICS_TOLERANCE = Decimal("0.01")
ECONOMICS_RELATIVE_TOLERANCE = Decimal("0.005")


def _decimal_business_value(value: Any) -> Decimal | None:
    """Parse a real number as Decimal; null, text and ranges stay unknown, never zero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    return None


def _format_decimal(value: Decimal) -> str:
    """Format without binary float residue or scientific notation."""
    if not value.is_finite():
        return str(value)
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    return format(value.normalize(), "f")


def _economics_close(expected: Decimal, actual: Decimal) -> bool:
    tolerance = max(ECONOMICS_TOLERANCE, abs(expected) * ECONOMICS_RELATIVE_TOLERANCE)
    return abs(expected - actual) <= tolerance


def _economics_mismatch(metric: str, expected: Decimal, actual: Decimal) -> dict[str, str]:
    return {
        "code": "economics_mismatch",
        "metric": metric,
        "expected": _format_decimal(expected),
        "actual": _format_decimal(actual),
        "delta": _format_decimal(actual - expected),
    }


def _economics_check(
    checks: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
    kind: str,
    metric: str,
    expected: Decimal,
    actual: Decimal,
) -> None:
    passed = _economics_close(expected, actual)
    checks.append(
        {
            "kind": kind,
            "metric": metric,
            "expected": _format_decimal(expected),
            "actual": _format_decimal(actual),
            "status": "ok" if passed else "mismatch",
        }
    )
    if not passed:
        mismatches.append({**_economics_mismatch(metric, expected, actual), "kind": kind})


def _economics_rate(value: Decimal, metric: str) -> Decimal:
    """Read an explicitly percent-valued rate as a ratio; otherwise keep the declaration as-is."""
    text = metric.casefold()
    percent_hint = "%" in metric or "率" in metric or "percent" in text or "margin" in text
    if percent_hint and value > 1 and value <= 100:
        return value / 100
    return value


def _format_percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _format_ratio(value: Decimal) -> str:
    return _format_decimal(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def validate_unit_economics(business: dict[str, Any]) -> dict[str, Any]:
    """Check the business node's declared arithmetic with Decimal.

    Only relationships the node itself declares are checked. Mismatches are
    reported, never rewritten; missing declarations stay unknown, never zero.
    """
    checks: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    computed: dict[str, dict[str, str]] = {}
    if not isinstance(business, dict):
        business = {}

    prices: list[tuple[str, dict[str, Any], Decimal]] = []
    for index, entry in enumerate(business.get("pricing") or []):
        if not isinstance(entry, dict):
            continue
        amount = _decimal_business_value(entry.get("amount"))
        if amount is None or amount <= 0:
            continue
        prices.append((str(entry.get("model") or f"price-{index + 1}"), entry, amount))

    inputs: list[tuple[dict[str, Any], Decimal, bool]] = []
    for item in business.get("unit_economics_inputs") or []:
        if not isinstance(item, dict):
            continue
        value = _decimal_business_value(item.get("value"))
        if value is None:
            continue
        if not str(item.get("source_ref") or "").strip():
            continue
        name = str(item.get("metric") or "")
        cost_like = bool(
            COST_NAME_PATTERN.search(name) or COST_NAME_PATTERN.search(str(item.get("status") or ""))
        )
        inputs.append((item, value, cost_like))

    for label, entry, amount in prices:
        unit = str(entry.get("unit") or "").strip()
        matched = [
            (item, value, cost_like)
            for item, value, cost_like in inputs
            if str(item.get("unit") or "").strip() == unit
        ]
        computed_entry: dict[str, str] = {}

        volume = None
        for key in ("volume", "units", "quantity"):
            volume = _decimal_business_value(entry.get(key))
            if volume is not None:
                break
        revenue = None
        for key in ("revenue", "total_revenue"):
            revenue = _decimal_business_value(entry.get(key))
            if revenue is not None:
                break

        if volume is not None and revenue is not None:
            _economics_check(checks, mismatches, "revenue", f"{label} · 收入", amount * volume, revenue)
        elif volume is not None:
            computed_entry["revenue"] = _format_decimal(amount * volume)
            notes.append(
                {
                    "code": "revenue_computed",
                    "metric": label,
                    "message": (
                        f"未声明总营收；按 {_format_decimal(amount)} × {_format_decimal(volume)} "
                        f"推得 {computed_entry['revenue']}，仅作计算，不替代声明"
                    ),
                }
            )
        elif revenue is not None:
            computed_entry["volume"] = _format_decimal(revenue / amount)
            notes.append(
                {
                    "code": "volume_implied",
                    "metric": label,
                    "message": (
                        f"未声明数量；按总营收 {_format_decimal(revenue)} ÷ 单价 {_format_decimal(amount)} "
                        f"推得 {computed_entry['volume']}，仅作计算，不替代声明"
                    ),
                }
            )

        costs = [(item, value) for item, value, cost_like in matched if cost_like]
        detail_costs = [
            (item, value)
            for item, value in costs
            if not TOTAL_COST_PATTERN.search(str(item.get("metric") or ""))
        ]
        declared_totals = [
            (item, value)
            for item, value in costs
            if TOTAL_COST_PATTERN.search(str(item.get("metric") or ""))
        ]

        cost_basis: Decimal | None = None
        if detail_costs:
            cost_basis = sum((value for _, value in detail_costs), Decimal("0"))
            for item, declared in declared_totals:
                _economics_check(
                    checks,
                    mismatches,
                    "total_cost",
                    f"{label} · {item.get('metric') or '成本合计'}",
                    cost_basis,
                    declared,
                )
        elif declared_totals:
            cost_basis = sum((value for _, value in declared_totals), Decimal("0"))
            notes.append(
                {
                    "code": "cost_basis_from_declared_total",
                    "metric": label,
                    "message": "只有成本合计、没有分项成本；毛利与毛利率按该合计值计算，成本口径未核验",
                }
            )

        if cost_basis is not None:
            gross_profit = amount - cost_basis
            computed_entry["cost_basis"] = _format_decimal(cost_basis)
            computed_entry["gross_profit"] = _format_decimal(gross_profit)
            computed_entry["margin_rate"] = _format_percent(gross_profit / amount * 100)
            if cost_basis != 0:
                computed_entry["roi"] = _format_ratio(gross_profit / cost_basis)

        for item, value, cost_like in matched:
            name = str(item.get("metric") or "")
            metric_label = f"{label} · {name or '未命名输入'}"
            if cost_like:
                continue
            if MARGIN_RATE_PATTERN.search(name):
                if cost_basis is None:
                    notes.append(
                        {
                            "code": "margin_rate_unchecked",
                            "metric": metric_label,
                            "message": "声明了毛利率，但没有同单位、带来源的成本输入；未做校验",
                        }
                    )
                    continue
                _economics_check(
                    checks,
                    mismatches,
                    "margin_rate",
                    metric_label,
                    (amount - cost_basis) / amount,
                    _economics_rate(value, name),
                )
            elif ROI_PATTERN.search(name):
                if cost_basis is None or cost_basis == 0:
                    notes.append(
                        {
                            "code": "roi_undefined",
                            "metric": metric_label,
                            "message": "成本基础为零或缺失，ROI 无定义；作为缺口保留，不按零计算",
                        }
                    )
                    continue
                _economics_check(
                    checks,
                    mismatches,
                    "roi",
                    metric_label,
                    (amount - cost_basis) / cost_basis,
                    _economics_rate(value, name),
                )
            elif GROSS_PROFIT_PATTERN.search(name):
                if cost_basis is None:
                    notes.append(
                        {
                            "code": "gross_profit_unchecked",
                            "metric": metric_label,
                            "message": "声明了毛利，但没有同单位、带来源的成本输入；未做校验",
                        }
                    )
                    continue
                _economics_check(
                    checks,
                    mismatches,
                    "gross_profit",
                    metric_label,
                    amount - cost_basis,
                    value,
                )
            elif PRICE_NAME_PATTERN.search(name) and value == amount:
                notes.append(
                    {
                        "code": "price_restated_as_input",
                        "metric": metric_label,
                        "message": "金额与定价相同且名称像价格；疑似重复登记，不作为成本参与减法",
                    }
                )
        if computed_entry:
            computed[label] = computed_entry

    if mismatches:
        status = "mismatch"
    elif checks:
        status = "ok"
    else:
        status = "insufficient"
    return {
        "status": status,
        "checks": checks,
        "mismatches": mismatches,
        "notes": notes,
        "computed": computed,
    }


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
    unknown, never zero; mismatches with declared values are reported, not
    rewritten, and no causal or commercial proof is claimed.
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
        "validation_status": "insufficient",
        "mismatch_count": 0,
        "mismatches": [],
        "notes": [],
    }
    lines.append(f"## {stats['id']} — {stats['title'] or '（未命名）'}")
    lines.append("")
    lines.append(f"- 收入模型：{business.get('revenue_model') or '未填写'}")
    lines.append(f"- 定价假设：{business.get('pricing_hypothesis') or '未填写'}")
    lines.append("")

    prices: list[tuple[dict[str, Any], Decimal]] = []
    for entry in business.get("pricing") or []:
        if not isinstance(entry, dict):
            continue
        amount = _decimal_business_value(entry.get("amount"))
        ev = ", ".join(str(x) for x in entry.get("evidence_ids") or [])
        shown = _format_decimal(amount) if amount is not None else "未知"
        lines.append(
            f"- 定价：{entry.get('model') or '未命名'} = "
            f"{shown} "
            f"{entry.get('currency') or ''}/{entry.get('unit') or '单位未注明'}"
            f"（{entry.get('term') or '期限未注明'}；证据：{ev or '无'}）"
        )
        if amount is not None and amount > 0:
            prices.append((entry, amount))
    stats["prices"] = len(prices)
    lines.append("")

    inputs = [item for item in business.get("unit_economics_inputs") or [] if isinstance(item, dict)]
    known: list[tuple[dict[str, Any], Decimal, bool]] = []
    unknown: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in inputs:
        value = _decimal_business_value(item.get("value"))
        has_source = bool(str(item.get("source_ref") or "").strip())
        if value is None:
            unknown.append(item)
            continue
        if not has_source:
            warnings.append(
                f"{item.get('metric') or '未命名'}：数值 {_format_decimal(value)} 缺少 source_ref，不进入计算"
            )
            unknown.append(item)
            continue
        name = str(item.get("metric") or "")
        cost_like = bool(
            COST_NAME_PATTERN.search(name) or COST_NAME_PATTERN.search(str(item.get("status") or ""))
        )
        known.append((item, value, cost_like))
    stats["unknown_inputs"] = len(unknown)
    stats["provenance_warnings"] = len(warnings)

    lines.append("### 单位经济输入（带来源的数值才可计算）")
    lines.append("")
    lines.append("| 输入 | 数值 | 单位 | 来源 |")
    lines.append("|---|---|---|---|")
    for item, value, _cost_like in known:
        lines.append(
            f"| {item.get('metric') or '未命名'} | {_format_decimal(value)} | {item.get('unit') or '未注明'} | "
            f"{item.get('source_ref') or ''} |"
        )
    for item in unknown:
        shown = item.get("value") if item.get("value") is not None else "未知（null 不是 0）"
        lines.append(f"| {item.get('metric') or '未命名'} | {shown} | {item.get('unit') or '未注明'} | 未知/缺来源 |")
    lines.append("")

    for entry, amount in prices:
        unit = str(entry.get("unit") or "").strip()
        matched = [
            (item, value, cost_like)
            for item, value, cost_like in known
            if str(item.get("unit") or "").strip() == unit
        ]
        stats["unit_matched_inputs"] += len(matched)
        model = entry.get("model") or "定价"
        lines.append(f"### 计算：{model}（{_format_decimal(amount)} / {unit or '单位未注明'}）")
        lines.append("")
        if not matched:
            lines.append(f"- 没有单位匹配（unit = “{unit or '未注明'}”）且带来源的数值输入；无法进行任何算术。")
            lines.append("")
            continue
        cost_like = [(item, value) for item, value, is_cost in matched if is_cost]
        for item, value, is_cost in matched:
            name = item.get("metric") or "未命名"
            if is_cost:
                delta = amount - value
                multiple = amount / value if value else None
                multiple_text = f"；{_format_ratio(multiple)}×" if multiple is not None else ""
                lines.append(
                    f"- {name}：{_format_decimal(amount)} − {_format_decimal(value)} = "
                    f"{_format_decimal(delta)}（单位 {unit or '未注明'}）{multiple_text}"
                )
            else:
                text = (
                    f"- {name}：同单位但不是成本项，不参与价格减法"
                    f"（单位 {unit or '未注明'}；数值 {_format_decimal(value)}）"
                )
                if PRICE_NAME_PATTERN.search(str(item.get("metric") or "")) and value == amount:
                    text += "；与定价金额相同，疑似重复登记"
                lines.append(text)
        detail_costs = [
            (item, value)
            for item, value in cost_like
            if not TOTAL_COST_PATTERN.search(str(item.get("metric") or ""))
        ]
        declared_totals = [
            (item, value)
            for item, value in cost_like
            if TOTAL_COST_PATTERN.search(str(item.get("metric") or ""))
        ]
        if detail_costs:
            cost_sum = sum((value for _, value in detail_costs), Decimal("0"))
            margin = (amount - cost_sum) / amount * 100 if amount else None
            names = "、".join(str(item.get("metric")) for item, _ in detail_costs)
            lines.append("")
            lines.append(f"- 指示性成本类合计（仅按名称匹配“cost/成本/费用”：{names}）：{_format_decimal(cost_sum)}")
            if margin is not None:
                lines.append(
                    f"- 指示性毛利：{_format_decimal(amount)} − {_format_decimal(cost_sum)} = "
                    f"{_format_decimal(amount - cost_sum)}（{_format_percent(margin)}）"
                )
        elif declared_totals:
            cost_sum = sum((value for _, value in declared_totals), Decimal("0"))
            names = "、".join(str(item.get("metric")) for item, _ in declared_totals)
            lines.append("")
            lines.append(f"- 声明成本合计（{names}）：{_format_decimal(cost_sum)}（无分项成本可核对）")
        if cost_like:
            lines.append("- 上述合计依赖输入命名与单位一致，不构成成本口径核验；财务评审独立进行。")
            stats["computed"] = True
        lines.append("")

    if warnings:
        lines.append("### 来源缺口")
        lines.append("")
        lines.extend(f"- {text}" for text in warnings)
        lines.append("")

    validation = validate_unit_economics(business)
    stats["validation_status"] = validation["status"]
    stats["mismatch_count"] = len(validation["mismatches"])
    stats["mismatches"] = validation["mismatches"]
    stats["notes"] = validation["notes"]
    lines.append("### 测算校验（声明值与确定性计算）")
    lines.append("")
    if validation["status"] == "mismatch":
        lines.append(
            f"- 状态：发现 {len(validation['mismatches'])} 处声明值与确定性计算不一致"
            "（只报告，不替用户改数；容差 0.01 或 0.5%）。"
        )
        for mismatch in validation["mismatches"]:
            lines.append(
                f"- {mismatch['metric']}：应为 {mismatch['expected']}，"
                f"声明 {mismatch['actual']}，差 {mismatch['delta']}"
            )
    elif validation["status"] == "ok":
        lines.append(f"- 状态：一致（{len(validation['checks'])} 项声明通过容差校验；容差 0.01 或 0.5%）。")
    else:
        lines.append("- 状态：没有可校验的数量声明；只列出确定性计算，未补默认值。")
    for note in validation["notes"]:
        lines.append(f"- 备注：{note['message']}")
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
        "> 声明值与计算值不一致时只报告，不替用户改数；缺失声明保持未知，不补默认值。",
        "> 本投影不构成商业证明、发布就绪或因果结论；E4/E5 商业证据、财务评审与人工决策保持独立。",
        "",
    ]
    if not sections:
        lines.append("（当前没有包含商业节点的 chain；`askovo chain` 脚手架后填写 business 节点。）")
        lines.append("")
    lines.extend(sections)
    lines.extend([
        "## 边界",
        "",
        "本文件是 business 节点数值输入的算术投影：null 表示未知，不是零；计算成立不等于商业成立。"
        "它不证明需求、付费意愿、市场规模、单位经济可持续、发布就绪或因果；"
        "E4+/E5 商业证据、财务评审与人工决策保持独立。",
        "",
    ])
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
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label') or _study_labels(study)[0]}；"
        f"阶段：{route.get('stage_label') or _study_labels(study)[1]}。",
        "",
        f"- 决策问题：{_gap_or_value(decision.get('question') or study.get('decision_question') or study.get('title'), '读者不知道这份决策包回答什么', '补写决策问题', compact=True)}",
        f"- 决策负责人：{_gap_or_value(decision.get('owner'), '无法确定谁对结论负责', '补写决策负责人', compact=True)}；"
        f"截止：{_gap_or_value(decision.get('deadline'), '无法判断什么时候必须拍板', '补写截止时间', compact=True)}",
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
            method = _gap_or_value(
                prioritization.get("method"), "无法核对优先级比较方法", "补写优先级比较方法", compact=True
            )
            owner = _gap_or_value(
                prioritization.get("owner"), "无法确定谁做的优先级判断", "补写优先级负责人", compact=True
            )
            rationale = _gap_or_value(
                prioritization.get("rationale"), "无法复核为什么选这条链路", "补写选择这条链路的理由", compact=True
            )
            resource = _gap_or_value(
                gate.get("resource_commitment"),
                "无法核对投入的人力和预算",
                "补写已承诺的人力和预算",
                compact=True,
            )
            lines.extend(
                [
                    f"### {chain.get('id', 'PR?')} · {chain.get('title', '')}",
                    "",
                    f"- 推荐读法：`decided` 是**产品/商业选择记录**，不是发布或商业成功证明。",
                    f"- 优先级：方法 {method}；负责人 {owner}；理由 {rationale}",
                    f"- 商业门：`{gate.get('stage', 'G0')}` / `{gate.get('decision', 'hypothesis')}`；"
                    f"资源承诺 {resource}",
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


# Evidence-strength markers for the business plan (Roy's hand-written prototype
# notation, absorbed 2026-11-03). The rule is deterministic and data-first:
# strength is computed only from the records a node cites, never hand-set, and
# is a reading aid — not proof of prevalence, market size or causality.
_PLAN_STRENGTH_OBSERVED = {"E2", "E3", "E4", "E4+", "E5"}  # observed behavior/acceptance/payment; E4- is counter behavior
_PLAN_STRENGTH_WITH_LEADS = _PLAN_STRENGTH_OBSERVED | {"E1"}


def _plan_strength_level(record: dict[str, Any]) -> str:
    return str(record.get("evidence_level") or "").strip().upper()


def _plan_strength_families(records: list[dict[str, Any]]) -> set:
    families: set = set()
    for record in records:
        families.add(str(record.get("source_family") or "").strip() or "未记录")
    return families


def _evidence_text(record: dict[str, Any]) -> str:
    """Canonical evidence stores `text_excerpt`; imported/legacy rows may store text/body/content.

    `title` is deliberately not a fallback here: a title-only issue is not
    reproducible evidence text, even though normalization may preserve the title
    for display.
    """
    return str(
        record.get("text")
        or record.get("text_excerpt")
        or record.get("body")
        or record.get("selftext")
        or record.get("content")
        or record.get("quote")
        or record.get("message")
        or record.get("comment")
        or record.get("evidence_basis")
        or ""
    ).strip()


def _evidence_form(record: dict[str, Any]) -> str:
    """Fall back to corpus_role: canonical records do not carry evidence_form."""
    return str(record.get("evidence_form") or record.get("corpus_role") or "unknown").strip() or "unknown"


_CLAIM_BY_LEVEL = {
    "E0": "context", "E1": "need", "E2": "need", "E3": "acceptance",
    "E4+": "commercial", "E5": "commercial", "E4-": "counter",
}


def _evidence_claim(record: dict[str, Any]) -> str:
    """Use an explicit claim_type, else derive a coarse one from the evidence level."""
    explicit = str(record.get("claim_type") or "").strip()
    if explicit:
        return explicit
    level = str(record.get("evidence_level") or "").strip().upper()
    return _CLAIM_BY_LEVEL.get(level, "未标注")


# ---------------------------------------------------------------------------
# A-01 正交证据资格（orthogonal evidence qualification，2026-11-15）。
#
# E0–E5 契约保持不变；这里新增三条**正交、非单调**的显示属性，只做解释投影：
#   measurement_integrity  数值/记录真实性（观测可信度）；
#   behavior_kind          记录捕捉的行为类型（内容特征，不从 evidence_level 派生）；
#   claim_eligibility      该记录有资格支撑的结论类别（按规则派生，高风险关联需人工审核）。
# 「观测真实」不等于「商业结论支持强度」：API 可核实的 star 数是
# confirmed_source + attention_metric + descriptive_only，永远推不出商业 E5 资格。
# 资格派生只读记录既有字段，不改写 evidence_level、不迁移历史数据；检测到
# 「注意力指标被标 E5」这类跨维度冲突时输出 needs_requalification 标记，
# 原值保持不动，由人工重审。
# ---------------------------------------------------------------------------

MEASUREMENT_INTEGRITY_VALUES = ("confirmed_source", "self_reported", "unverified", "conflicted")
BEHAVIOR_KIND_VALUES = (
    "statement",
    "problem_behavior",
    "solution_acceptance",
    "commercial_intent",
    "commercial_transaction",
    "attention_metric",
)
CLAIM_ELIGIBILITY_VALUES = ("problem", "solution", "commercial", "descriptive_only", "none")

_COMMERCE_TRANSACTION_CONFIRMING = {"verified_purchase", "transaction_linked"}
_COMMERCE_TRANSACTION_WEAKENING = {"vine_free_product", "incentivized_disclosed", "unknown"}
_KICKSTARTER_TRANSACTION_CONFIRMING = {"charged", "fulfilled", "refunded", "dropped"}
_KICKSTARTER_INTENT_STATUSES = {"pledged", "pledge_adjusted"}
_ATTENTION_CONTENT_TYPES = {"tracker_snapshot", "funding_snapshot", "rating_only"}


def _first_field(record: dict[str, Any], *names: str) -> str:
    """Return the first non-empty normalized value among the given field names."""
    for name in names:
        value = str(record.get(name) or "").strip().lower()
        if value:
            return value
    return ""


def _explicit_measurement_integrity(record: dict[str, Any]) -> str:
    explicit = str(record.get("measurement_integrity") or "").strip().lower()
    return explicit if explicit in MEASUREMENT_INTEGRITY_VALUES else ""


def _derive_measurement_integrity(record: dict[str, Any]) -> str:
    """数值/记录真实性：显式人工标注优先，否则按来源特征确定性派生。"""
    explicit = _explicit_measurement_integrity(record)
    if explicit:
        return explicit
    form = _first_field(record, "evidence_form")
    if "self_report" in form:
        return "self_reported"
    commerce_status = _first_field(record, "commerce_transaction_status")
    if commerce_status:
        if commerce_status in _COMMERCE_TRANSACTION_CONFIRMING:
            return "confirmed_source"
        if commerce_status == "unverified":
            return "unverified"
        if commerce_status in _COMMERCE_TRANSACTION_WEAKENING:
            return "self_reported"
    kickstarter_status = _first_field(record, "commercial_status")
    if kickstarter_status:
        if kickstarter_status in _KICKSTARTER_TRANSACTION_CONFIRMING or kickstarter_status == "public_aggregate":
            return "confirmed_source"
        if kickstarter_status in _KICKSTARTER_INTENT_STATUSES:
            return "self_reported"
    # 采集管线带回可回查定位（来源 URL + 采集运行号）→ 来源可核实
    if str(record.get("source_url") or "").strip() and str(record.get("collection_run_id") or "").strip():
        return "confirmed_source"
    return "unverified"


def _derive_behavior_kind(record: dict[str, Any]) -> str:
    """行为类型：从内容特征派生（显式标注优先），不从 evidence_level 派生。"""
    explicit = str(record.get("behavior_kind") or "").strip().lower()
    if explicit in BEHAVIOR_KIND_VALUES:
        return explicit
    claim_type = _first_field(record, "claim_type")
    form = _first_field(record, "evidence_form")
    if claim_type == "attention_metric" or form == "attention_metric":
        return "attention_metric"
    content_type = _first_field(
        record,
        "content_type",
        "source_content_type",
        "commerce_content_type",
        "kickstarter_content_type",
    )
    if content_type in _ATTENTION_CONTENT_TYPES:
        return "attention_metric"
    if claim_type == "commercial_transaction" or form in {"transaction", "purchase"}:
        return "commercial_transaction"
    if commerce_status := _first_field(record, "commerce_transaction_status"):
        if commerce_status in _COMMERCE_TRANSACTION_CONFIRMING:
            return "commercial_transaction"
    if content_type in {"pledge_record", "refund_record", "fulfillment_record"}:
        return "commercial_transaction"
    if claim_type == "commercial_intent" or form == "commercial_intent":
        return "commercial_intent"
    if _first_field(record, "commercial_status") in _KICKSTARTER_INTENT_STATUSES:
        return "commercial_intent"
    if claim_type in {"acceptance", "solution"} or form in {"acceptance", "solution"}:
        return "solution_acceptance"
    if claim_type in {"problem", "need"} or form in {"problem_behavior", "problem"}:
        return "problem_behavior"
    if str(record.get("corpus_role") or "").strip().lower() in {"substitute_rejector"}:
        return "problem_behavior"
    if str(record.get("corpus_role") or "").strip().lower() in {"direct_solution", "post_purchase_support"}:
        return "solution_acceptance"
    return "statement"


def _derive_claim_eligibility(measurement_integrity: str, behavior_kind: str) -> tuple[str, bool]:
    """结论资格（派生）：返回 (claim_eligibility, review_required)。

    高风险关联（商业交易但来源不可核实）不授予 commercial，必须人工审核。
    """
    if measurement_integrity == "conflicted":
        return "none", True
    if behavior_kind == "attention_metric":
        # 注意力指标只能作描述性观测，任何来源真实都不改变这一点
        return ("descriptive_only" if measurement_integrity == "confirmed_source" else "none"), False
    if behavior_kind == "commercial_transaction":
        if measurement_integrity == "confirmed_source":
            return "commercial", False
        # 「已付款」陈述但来源 unverified/self_reported：不得作为商业证据
        return "none", True
    if behavior_kind == "commercial_intent":
        # 意向/锚点/聚合只支撑描述，不授予商业结论资格
        return ("descriptive_only" if measurement_integrity in {"confirmed_source", "self_reported"} else "none"), False
    if behavior_kind == "problem_behavior":
        return ("problem" if measurement_integrity in {"confirmed_source", "self_reported"} else "none"), False
    if behavior_kind == "solution_acceptance":
        return ("solution" if measurement_integrity in {"confirmed_source", "self_reported"} else "none"), False
    # statement：陈述本身可作描述性事实，但不支撑问题/方案/商业结论
    return ("descriptive_only" if measurement_integrity == "confirmed_source" else "none"), False


def qualify_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """对单条 evidence 记录派生三条正交资格属性（只读，不修改记录）。

    返回 measurement_integrity / behavior_kind / claim_eligibility，以及
    needs_requalification（跨维度冲突，例如注意力指标被标 E5——只标记，
    不改写 evidence_level）与 review_required（高风险关联需人工审核）。
    """
    measurement_integrity = _derive_measurement_integrity(record)
    behavior_kind = _derive_behavior_kind(record)
    claim_eligibility, review_required = _derive_claim_eligibility(measurement_integrity, behavior_kind)
    reasons: list[str] = []
    needs_requalification = False
    level = str(record.get("evidence_level") or "").strip().upper()
    if level == "E5" and claim_eligibility != "commercial":
        needs_requalification = True
        reasons.append(
            f"E5 要求已完成商业/持续使用行为，但该记录资格为 {claim_eligibility}"
            f"（{measurement_integrity} / {behavior_kind}）；原值保留，需人工重审"
        )
    explicit_eligibility = str(record.get("claim_eligibility") or "").strip().lower()
    if explicit_eligibility and explicit_eligibility in CLAIM_ELIGIBILITY_VALUES and explicit_eligibility != claim_eligibility:
        needs_requalification = True
        reasons.append(
            f"记录自带 claim_eligibility={explicit_eligibility} 与派生值 {claim_eligibility} 不一致；以派生规则为准，需人工重审"
        )
    if review_required:
        reasons.append("高风险关联（商业行为 × 来源不可核实）：不授予商业资格，需人工审核")
    return {
        "measurement_integrity": measurement_integrity,
        "behavior_kind": behavior_kind,
        "claim_eligibility": claim_eligibility,
        "needs_requalification": needs_requalification,
        "review_required": review_required,
        "reasons": reasons,
    }


def _source_identity_key(record: dict[str, Any]) -> str:
    """同一外部来源的稳定标识：source_url 优先，退化到采集运行号+来源引用。"""
    url = " ".join(str(record.get("source_url") or "").strip().casefold().split())
    if url:
        return f"url:{url}"
    run_id = str(record.get("collection_run_id") or "").strip()
    source_ref = str(record.get("source_ref") or "").strip()
    if run_id or source_ref:
        return f"ref:{run_id}|{source_ref}"
    return f"record:{str(record.get('record_id') or record.get('normalized_text_hash') or id(record))}"


def independent_source_count(records: list[dict[str, Any]]) -> int:
    """独立来源数：按来源标识去重。同一来源复制 N 条只算一个来源。"""
    return len({_source_identity_key(record) for record in records})


def evidence_qualification(records: list[dict[str, Any]]) -> dict[str, Any]:
    """批量资格投影：逐条三属性 + 汇总计数 + 冲突清单 + 独立来源数。"""
    per_record: dict[str, dict[str, Any]] = {}
    integrity_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    eligibility_counts: dict[str, int] = {}
    needs_requalification: list[str] = []
    review_required: list[str] = []
    for record in records:
        record_id = str(record.get("record_id") or "<unknown>")
        info = qualify_evidence(record)
        per_record[record_id] = info
        integrity_counts[info["measurement_integrity"]] = integrity_counts.get(info["measurement_integrity"], 0) + 1
        kind_counts[info["behavior_kind"]] = kind_counts.get(info["behavior_kind"], 0) + 1
        eligibility_counts[info["claim_eligibility"]] = eligibility_counts.get(info["claim_eligibility"], 0) + 1
        if info["needs_requalification"]:
            needs_requalification.append(record_id)
        if info["review_required"]:
            review_required.append(record_id)
    return {
        "records": per_record,
        "counts": {
            "measurement_integrity": dict(sorted(integrity_counts.items())),
            "behavior_kind": dict(sorted(kind_counts.items())),
            "claim_eligibility": dict(sorted(eligibility_counts.items())),
        },
        "needs_requalification": needs_requalification,
        "review_required": review_required,
        "independent_sources": independent_source_count(records),
        "records_total": len(records),
    }


def _plan_observed_levels(node_name: str | None = None) -> set:
    """Which levels count as observed behavior for a node's strength marker.

    Business strength must come from commercial/paid behavior (E4+/E5), never
    from counter-evidence that happens to be E1/E2. Feature/product strength
    must come from acceptance (E3+), not from complaints about substitutes.
    """
    if node_name == "business":
        return {"E4", "E4+", "E5"}
    if node_name in {"feature", "product"}:
        return {"E3", "E4", "E4+", "E5"}
    return set(_PLAN_STRENGTH_OBSERVED)


def _plan_strength(records: list[dict[str, Any]], node_name: str | None = None) -> tuple:
    """Return (marker, label, why) for one node's cited records.

    ● 已观察到 — at least two observed-level records from at least two source
    families; family-name diversity does not prove statistical independence. The observed levels are node-aware:
    scene/user/pain/need accept E2+, feature/product require E3+, and business
    requires E4+/E5 (commercial evidence), so counter-evidence cannot make a
    commercial node look observed.
    ◐ 有线索 — some node-appropriate lead record exists but the ● bar is not met.
    ○ 假设 — no node-appropriate record at all; the statement is still a hypothesis.
    """
    observed_levels = _plan_observed_levels(node_name)
    lead_levels = observed_levels if node_name in {"business", "feature", "product"} else observed_levels | {"E1"}
    observed = [r for r in records if _plan_strength_level(r) in observed_levels]
    leads = [r for r in records if _plan_strength_level(r) in lead_levels]
    observed_families = _plan_strength_families(observed)
    if len(observed) >= 2 and len(observed_families) >= 2:
        return "●", "已观察到", f"多个来源族观察：{len(observed_families)} 个来源族 · 观察记录 {len(observed)} 条；相关性未证明独立"
    if leads:
        lead_families = _plan_strength_families(leads)
        if node_name == "business":
            return "◐", "有商业线索", f"商业线索 {len(leads)} 条 · {len(lead_families)} 个来源族（未达多个来源族观察；相关性未证明独立）"
        return "◐", "有线索", f"单案例或口头线索：线索记录 {len(leads)} 条 · {len(lead_families)} 个来源族（未达多个来源族观察；相关性未证明独立）"
    if node_name == "business":
        return "○", "假设（商业门未验证）", "尚无成交、付费或可核对的商业行为；商业判断仍待验证"
    return "○", "假设（待验证）", "尚无采集到的直接记录"


def _study_labels(study: dict[str, Any]) -> tuple[str, str]:
    """Best-effort human labels for a study without route.json.

    The bundled sample and imported studies may only carry raw domain/stage
    codes. Prefer the domain pack labels so the first line of a delivered plan
    never reads "产品类型：；阶段：".
    """
    domain = str(study.get("product_domain") or "")
    stage = str(study.get("lifecycle_stage") or "")
    domain_label, stage_label = domain, stage
    if domain:
        try:
            pack = load_pack(domain)
            domain_label = str(pack.get("label") or domain)
            stage_data = (pack.get("stages") or {}).get(stage) or {}
            stage_label = str(stage_data.get("label") or stage)
        except (OSError, ValueError, KeyError):
            pass
    return domain_label, stage_label


def _plan_time_span(records: list[dict[str, Any]]) -> str:
    stamps: list[str] = []
    for record in records:
        for field in ("source_time", "collected_at"):
            value = str(record.get(field) or "").strip()
            if value:
                stamps.append(value[:10])
    if not stamps:
        return ""
    return f"{min(stamps)}–{max(stamps)}"


def _plan_source_label(record: dict[str, Any]) -> str:
    family = str(record.get("source_family") or "").strip()
    family = PLAN_SOURCE_LABELS.get(family, family)
    source_ref = str(record.get("source_ref") or "").strip()
    if source_ref:
        return f"{family}（{source_ref[:40]}）" if family else source_ref[:40]
    return family or "未记录来源"


def _plan_basis(records: list[dict[str, Any]]) -> str:
    """Deterministic per-section data basis in business language."""
    if not records:
        return "数据基础：本节判断暂无采集数据支撑（来自导入材料或待验证假设）——这表示还没研究到，不是没有需求。"
    families: list[str] = []
    for record in records:
        family = str(record.get("source_family") or "未记录").strip() or "未记录"
        family = PLAN_SOURCE_LABELS.get(family, family)
        if family not in families:
            families.append(family)
    span = _plan_time_span(records)
    basis = f"数据基础：{len(records)} 条语料 · 来源：{'/'.join(families)}"
    if span:
        basis += f" · 时间：{span}"
    return basis


def _plan_quotes(
    records: list[dict[str, Any]],
    limit: int = 2,
    used: set[str] | None = None,
) -> list[str]:
    """Voices from the corpus in business-report style.

    Prefers verbatim excerpts (原话); falls back to the coded situation fields
    (典型情况) so the section stays concrete without faking a verbatim quote.
    ``used`` carries quote markers already rendered in earlier sections so the
    same voice is not repeated section after section.
    """
    quotes: list[str] = []
    seen: set[str] = set()
    for record in records:
        if len(quotes) >= limit:
            break
        excerpt = str(record.get("text_excerpt") or "").strip()
        kind = "原话"
        text = excerpt
        if len(text) < 8:
            text = str(record.get("friction_cost") or record.get("scene_trigger") or "").strip()
            kind = "典型情况"
        if len(text) < 8:
            continue
        marker = text[:40]
        if marker in seen:
            continue
        if used is not None and marker in used:
            continue
        seen.add(marker)
        if used is not None:
            used.add(marker)
        when = str(record.get("source_time") or record.get("collected_at") or "").strip()
        suffix = f"，{when}" if when else ""
        if kind == "原话":
            quotes.append(f'> {kind}｜“{text}” —— {_plan_source_label(record)}{suffix}')
        else:
            quotes.append(f"> {kind}｜{text} —— {_plan_source_label(record)}{suffix}")
    return quotes


def _plan_node_records(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record_id in node.get("evidence_ids", []) if isinstance(node.get("evidence_ids"), list) else []:
        record = by_id.get(str(record_id))
        if record is not None and str(record_id) not in seen:
            records.append(record)
            seen.add(str(record_id))
    return records


def _plan_section(
    title: str,
    node: dict[str, Any] | None,
    by_id: dict[str, dict[str, Any]],
    field_rows: list[tuple[str, Any]],
    quote_limit: int = 2,
    extra_lines: list[str] | None = None,
    used_quotes: set[str] | None = None,
    qualification: dict[str, Any] | None = None,
) -> list[str]:
    lines: list[str] = [f"## {title}", ""]
    if not isinstance(node, dict) or not node:
        lines.extend(["七节点推理中该环节尚未填写；补齐后再进入本节。", ""])
        return lines
    records = _plan_node_records(node, by_id)
    node_key = {"2": "scene", "3": "user", "4": "pain", "5": "need",
                "6": "feature", "7": "product", "8": "business"}.get(title.split(".")[0].strip())
    marker, strength_label, strength_detail = _plan_strength(records, node_key)
    statement = _gap_or_value(
        node.get("statement"),
        "本节判断不完整，无法据此决策",
        "补写该环节的一句话结论",
        compact=True,
    )
    lines.extend([f"**{marker} {strength_label}｜{statement}**", ""])
    for label, value in field_rows:
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            rendered = "；".join(
                str(item.get("definition") or item.get("criteria") or item) if isinstance(item, dict) else str(item)
                for item in value
            )
        else:
            rendered = str(value)
        if rendered.strip():
            lines.append(f"- {label}：{rendered}")
    if extra_lines:
        lines.extend(extra_lines)
    why = node.get("rationale")
    if why:
        lines.append(f"- 为什么这么判断：{why}")
    lines.append("")
    lines.append(_plan_basis(records))
    metrics = _plan_node_metrics(records)
    if metrics:
        lines.append(metrics)
    lines.append(f"依据强度：{marker} {strength_label} —— {strength_detail}")
    if records:
        counts = web_surface.label_counts(records, qualification)
        lines.append(f"证据类型：事实 {counts.get(web_surface.TAG_FACT, 0)} 条 · 自述 {counts.get(web_surface.TAG_SELF, 0)} 条")
    quotes = _plan_quotes(records, limit=quote_limit, used=used_quotes)
    if quotes:
        lines.append("来自语料的声音：")
        lines.extend(quotes)
    lines.append("")
    return lines


PLAN_STATUS_LABELS = {
    "draft": "草稿",
    "hypothesis": "假设（还没有采集数据）",
    "needs-validation": "待验证（有线索，证据还不够下结论）",
    "validated": "已验证（证据达到结构门槛，仍需人工复核）",
    "decided": "已定（记录的是选择，不等于已经验证）",
    "rejected": "已否决",
    "deprioritized": "暂缓",
}


MONEY_RE = (
    r"(?:[$€£¥]\s?\d[\d,.]*"
    r"|\d[\d,.]*\s?(?:美元|USD|EUR|欧元|万元|万|%|倍)"
    r"|\d[\d,.]*\s?(?:per month|/month|a month|an hour|/hour|per hour))"
)


def _plan_node_metrics(records: list[dict[str, Any]]) -> str:
    """数据读出：把该环节引用的记录变成一句可读的数量事实。"""
    if not records:
        return ""
    total = len(records)
    observed = sum(1 for record in records if str(record.get("evidence_level") or "") in {"E2", "E3", "E4+", "E5"})
    families = {str(record.get("source_family") or "") for record in records if record.get("source_family")}
    money = sum(1 for record in records if re.search(MONEY_RE, str(record.get("text_excerpt") or ""), re.I))
    parts = [f"{total} 条中有 {observed} 条是观察级记录（做过、接受或付过钱）"]
    if families:
        parts.append(f"来自 {len(families)} 个来源族（相关性未证明独立）")
    if money:
        parts.append(f"{money} 条带金额或比例")
    return "数据读出：" + "，".join(parts) + "。"


def _plan_money_evidence(records: list[dict[str, Any]], limit: int = 5) -> list[str]:
    """把带金额或比例的原文摘成短句，供商业与 GTM 一节引用。"""
    snippets: list[str] = []
    seen: set[str] = set()
    for record in records:
        text = str(record.get("text_excerpt") or "").replace("\n", " ")
        match = re.search(MONEY_RE, text, re.I)
        if not match:
            continue
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 50)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if start > 0:
            cut = snippet.find(" ")
            if 0 <= cut < 40:
                snippet = "…" + snippet[cut + 1:]
        if end < len(text):
            cut = snippet.rfind(" ")
            if cut > len(snippet) - 40:
                snippet = snippet[:cut] + "…"
        snippet = snippet.strip(" ,.;:—-，。；：")
        key = re.sub(r"[^0-9a-zA-Z]", "", snippet)[:60]
        if key in seen:
            continue
        seen.add(key)
        snippets.append(snippet)
        if len(snippets) >= limit:
            break
    if not snippets:
        return []
    lines = ["**金额与比例线索**", ""]
    for snippet in snippets:
        lines.append(f"- {snippet}")
    lines.append("")
    return lines


def _plan_narrative(chain: dict[str, Any]) -> list[str]:
    """推理主线：用短字段把七段串成一段业务叙述，不引入新事实。"""
    nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}

    def node(name: str) -> dict[str, Any]:
        value = nodes.get(name, {})
        return value if isinstance(value, dict) else {}

    def text(value: Any, limit: int = 80) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip().rstrip("。；，")
        # Scaffold placeholders are not facts; drop them instead of narrating them.
        if cleaned in {"待填写", "待确认", "tbd", "todo"} or cleaned.startswith(("待填写", "待确认", "tbd:", "todo:")):
            return ""
        return cleaned[:limit]

    scene = node("scene")
    user = node("user")
    pain = node("pain")
    need = node("need")
    feature = node("feature")
    product = node("product")
    business = node("business")
    capabilities = feature.get("capabilities") if isinstance(feature.get("capabilities"), list) else []
    capability = capabilities[0] if capabilities and isinstance(capabilities[0], dict) else {}

    trigger = text(scene.get("trigger")) or text(scene.get("statement"))
    role = text(user.get("role")) or text(user.get("statement"))
    substitute = text(pain.get("current_substitute"), 100)
    friction = text(pain.get("friction_cost"), 100)
    want = text(need.get("desired_outcome")) or text(need.get("statement"))
    name = text(capability.get("name"), 30)
    what = text(capability.get("what"), 100)
    solves = text(capability.get("solves"), 100)
    form = text(product.get("form"), 60)
    revenue = text(business.get("revenue_model"), 60)
    payer = text(business.get("payer"), 40)

    if not any((trigger, role, substitute, friction, want, name, form, revenue)):
        return []
    middle = ""
    if substitute:
        middle = f"现在靠{substitute}"
        if friction:
            middle += f"，代价是{friction}"
    elif friction:
        middle = f"眼下{friction}"
    opening = "，".join(part for part in (f"在{trigger}" if trigger else "", role, middle) if part)
    sentence = f"{opening}。" if opening else ""
    if want:
        sentence += f"他们要的是{want}。"
    if name:
        sentence += f"对应的能力是{name}"
        sentence += f"：{what}。" if what else "。"
        if solves:
            sentence += f"它能成立，是因为{solves}。"
    if form:
        sentence += f"落到产品上，是{form}。"
    if revenue:
        sentence += f"商业上{revenue}"
        sentence += f"，付费者是{payer}。" if payer else "。"
    return ["**推理主线**：" + sentence, ""]


def _plan_chain_records(chain: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Unique records a chain cites across its seven nodes, in node order."""
    nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node_name in REASONING_NODES:
        node = nodes.get(node_name, {})
        if not isinstance(node, dict):
            continue
        for record in _plan_node_records(node, by_id):
            record_id = str(record.get("record_id"))
            if record_id not in seen:
                seen.add(record_id)
                ordered.append(record)
    return ordered


def _plan_conclusion_items(chain: dict[str, Any], chain_records: list[dict[str, Any]]) -> list[str]:
    nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
    product = nodes.get("product", {}) if isinstance(nodes.get("product"), dict) else {}
    feature = nodes.get("feature", {}) if isinstance(nodes.get("feature"), dict) else {}
    gate = business.get("gate", {}) if isinstance(business.get("gate"), dict) else {}
    items: list[str] = []
    families = {str(record.get("source_family") or "") for record in chain_records if record.get("source_family")}
    span = _plan_time_span(chain_records)
    if chain_records:
        basis = f"{len(chain_records)} 条可核对原话 · {len(families)} 类来源" + (f" · 时间窗 {span}" if span else "")
        items.append(f"- **判断依据**：{basis}（每条出处见文末方法档案）")
    what = str(feature.get("statement") or product.get("statement") or "").strip()
    if what:
        items.append(f"- **先做哪一段**：{what}")
    feature_why = str(feature.get("rationale") or "").strip()
    if feature_why:
        items.append(f"- **为什么是这段特性**：{feature_why}")
    product_why = str(product.get("rationale") or "").strip()
    if product_why:
        items.append(f"- **为什么是这个形态**：{product_why}")
    segment = str(business.get("target_segment") or "").strip()
    payer = str(business.get("payer") or "").strip()
    if segment or payer:
        items.append(f"- **先卖给谁**：{segment or '未提供目标人群'}" + (f"（付费者：{payer}）" if payer else ""))
    revenue = str(business.get("revenue_model") or "").strip()
    pricing = str(business.get("pricing_hypothesis") or "").strip()
    if revenue or pricing:
        items.append(f"- **怎么收钱**：{revenue or '未提供收钱方式'}" + (f"；定价方向：{pricing}" if pricing else ""))
    next_test = str(chain.get("next_test") or "").strip()
    if next_test:
        items.append(f"- **30 天内怎么验证**：{next_test}")
    gate_decision = str(gate.get("decision") or "").strip()
    if gate_decision:
        items.append(f"- **什么算过关**：{gate_decision}")
    failure = str(chain.get("failure_condition") or "").strip()
    if failure:
        items.append(f"- **什么算失败**：{failure}")
    non_goals = product.get("non_goals") or ""
    if isinstance(non_goals, list):
        non_goals_text = "；".join(str(item) for item in non_goals if str(item).strip())
    else:
        non_goals_text = str(non_goals).strip()
    if non_goals_text:
        items.append("- **明确不做**：" + non_goals_text)
    status = str(chain.get("status") or "").strip()
    label = PLAN_STATUS_LABELS.get(status, status or "待确认")
    assumptions = business.get("assumptions") or []
    premise = "；".join(str(item) for item in assumptions[:2] if str(item).strip()) if isinstance(assumptions, list) else ""
    strength = f"- **结论强度**：{label}" + (f"；成立的前提：{premise}" if premise else "")
    items.append(strength)
    return items


PLAN_NODE_STATUS_LABELS = {
    "hypothesis": "假设",
    "needs-validation": "待验证",
    "validated": "已验证",
    "rejected": "已否决",
    "deprioritized": "已降级",
}

PLAN_AUDIT_STATUS_LABELS = {
    "pass": "通过",
    "fail": "未通过",
    "not_run": "未运行",
}


def _plan_conclusion_gate(
    chain: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Decide whether a chain may render a formal conclusion.

    A formal conclusion needs a validated business node, at least one
    qualified E4+/E5 commercial record bound to it, and a chain context_key.
    A hand-edited ``validated`` status without commercial evidence stays a
    gap: status is a claim, not evidence. The full-audit requirement is
    applied by the caller because it is per delivery, not per chain.
    """
    nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
    business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
    feature = nodes.get("feature", {}) if isinstance(nodes.get("feature"), dict) else {}
    product = nodes.get("product", {}) if isinstance(nodes.get("product"), dict) else {}
    business_status = str(business.get("status") or "未设置").strip()
    business_records = _plan_node_records(business, by_id)
    commercial_records = [
        record for record in business_records
        if is_qualified_evidence(record)
        and str(record.get("evidence_level") or "") in COMMERCIAL_EVIDENCE_LEVELS
    ]
    gaps: list[str] = []
    if business_status != "validated":
        status_label = PLAN_NODE_STATUS_LABELS.get(business_status, business_status)
        gaps.append(f"商业环节仍处于「{status_label}」状态，未完成验证")
    if not commercial_records:
        bound = f"当前绑定 {len(business_records)} 条记录" if business_records else "当前没有绑定证据"
        gaps.append(f"商业环节缺少合格的商业证据（成交、付费或可核对的商业行为）；{bound}")
    if not str(chain.get("context_key") or "").strip():
        gaps.append("链缺少研究情境标识，无法把商业证据限定在同一研究情境")

    chain_records = _plan_chain_records(chain, by_id)
    families = {
        str(record.get("source_family") or "")
        for record in chain_records
        if record.get("source_family")
    }
    direction = str(feature.get("statement") or product.get("statement") or "").strip()
    support_parts: list[str] = []
    if chain_records:
        support_parts.append(f"{len(chain_records)} 条可核对记录、{len(families)} 类来源")
    if commercial_records:
        support_parts.append(f"其中商业证据 {len(commercial_records)} 条（成交、付费或可核对的商业行为）")
    if direction and chain_records:
        support_parts.append(f"能支持“{direction}”这一产品方向")
    if not support_parts:
        support = "当前没有绑定任何证据，只能把这条链当作待验证的产品假设"
    elif chain_records:
        support = "；".join(support_parts) + "；这些记录不证明成交、定价、市场规模或因果"
    else:
        support = "；".join(support_parts) + "；这只是待验证的产品假设"
    return {
        "qualified": not gaps,
        "support": support,
        "gaps": gaps,
        "business_status": business_status,
        "commercial_count": len(commercial_records),
    }


def _plan_conclusion_next_step(
    chain: dict[str, Any],
    study: dict[str, Any] | None,
    gate: dict[str, Any],
) -> str:
    study_ref = str((study or {}).get("study_id") or "<study>")
    chain_id = str(chain.get("id") or "").strip()
    chain_arg = f" --chain {chain_id}" if chain_id else ""
    commands: list[str] = []
    if not gate["commercial_count"]:
        commands.append(
            "先补充并注册商业证据（成交、付费或可核对的商业行为），再运行 "
            f"`askovo chain-node {study_ref} bind-evidence --node business --evidence <证据ID>{chain_arg}`"
        )
    if gate["business_status"] != "validated":
        commands.append(
            "完成人工语义复核后运行 "
            f"`askovo chain-node {study_ref} set --node business --status validated{chain_arg}`"
        )
    if not str(chain.get("context_key") or "").strip():
        commands.append("在 04-findings/product-reasoning.json 补齐与关联需求判断一致的研究情境标识")
    commands.append(f"最后运行 `askovo check {study_ref} --stage full`；审计通过前不输出正式结论")
    return "；".join(commands) + "。"


def _plan_conclusion_verdict(
    chain: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    audit_status: str,
    study: dict[str, Any] | None,
) -> list[str]:
    """Render a formal conclusion only when evidence and audit both qualify."""
    business = (chain.get("nodes") or {}).get("business", {})
    gate = _plan_conclusion_gate(chain, by_id)
    if gate["qualified"] and audit_status == "pass":
        return [f"**结论：{business.get('statement')}**", ""]
    gaps = list(gate["gaps"])
    if gate["qualified"]:
        heading = "**当前判断：完整检查未通过，不作为正式结论**"
        audit_label = PLAN_AUDIT_STATUS_LABELS.get(audit_status or "not_run", audit_status or "未运行")
        gaps.insert(
            0,
            f"完整检查（`askovo check --stage full`）状态为「{audit_label}」，"
            "结构、证据链与交付新鲜度校验未全部通过",
        )
    else:
        heading = "**当前判断：证据不足**"
    return [
        heading, "",
        f"- **现有证据能支持什么**：{gate['support']}",
        f"- **缺口是什么**：{'；'.join(gaps)}",
        f"- **下一步补证动作**：{_plan_conclusion_next_step(chain, study, gate)}",
        "",
    ]


def _plan_conclusion_lines(
    chains: list[dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    by_id: dict[str, dict[str, Any]] | None = None,
    audit_status: str = "not_run",
    study: dict[str, Any] | None = None,
) -> list[str]:
    """把七段推理收成可执行的决定：做什么、卖给谁、怎么收钱、先验证什么。

    纯投影：只读链上的 product / business 节点与 next_test、failure_condition，
    不产生新判断，也不引入证据编码。多链时先给比较表，再逐链给结论，避免
    只渲染第一条主链、把其他候选链的结论丢掉。正式结论需 business 节点
    validated、绑定合格的 E4+/E5 商业证据，且 full audit 通过；否则输出
    “当前判断 + 缺口 + 下一步补证动作”，不把假设写成结论。
    """
    by_id = by_id or {}
    entries: list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]] = []
    for chain in chains:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
        statement = str(business.get("statement") or "").strip()
        if not statement:
            continue
        chain_records = _plan_chain_records(chain, by_id) if by_id else list(records or [])
        items = _plan_conclusion_items(chain, chain_records)
        if items:
            entries.append((chain, chain_records, items))
    if not entries:
        return []

    intro = ("这一节把后面的七段推理收成可执行的决定：做什么、卖给谁、怎么收钱、先验证什么。"
             "判断的依据、数据基础和用户原话仍在后面各节。"
             "只有商业环节完成验证、绑定合格的商业证据（成交、付费或可核对的商业行为）"
             "且完整检查通过时，才给出正式结论。")
    if len(entries) == 1:
        chain, _, items = entries[0]
        return [
            "## 0. 结论与推进建议", "",
            f"> {intro}", "",
            *_plan_conclusion_verdict(chain, by_id, audit_status, study),
            *_plan_narrative(chain),
            *items,
            "",
        ]

    lines: list[str] = [
        "## 0. 多链结论与推进建议", "",
        f"> {intro} 本节先横向比较各条候选链，再逐链给出结论；正文的七环节只展开优先级最高的一条，其余链路见“其他候选链路”与决策包。",
        "",
        "| 链路 | 状态 | 依据强度 | 先做哪一段 | 下一步验证 | 失败线 | 优先级判断 |",
        "|---|---|---|---|---|---|---|",
    ]
    for chain, chain_records, _ in entries:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        feature = nodes.get("feature", {}) if isinstance(nodes.get("feature"), dict) else {}
        product = nodes.get("product", {}) if isinstance(nodes.get("product"), dict) else {}
        marker, strength, _ = _plan_strength(chain_records)
        priority = str((chain.get("prioritization") or {}).get("rationale") or "未排序").replace("|", "\\|")
        what = _gap_or_value(
            feature.get("statement") or product.get("statement"),
            "无法判断这条链先做什么",
            "补写特性或产品主张",
            compact=True,
        ).replace("|", "\\|")
        next_test = _gap_or_value(
            chain.get("next_test"), "无法安排下一步验证", "补写下一步验证", compact=True
        ).replace("|", "\\|")
        failure = _gap_or_value(
            chain.get("failure_condition"), "无法判断何时止损", "补写失败线", compact=True
        ).replace("|", "\\|")
        status = str(chain.get("status") or "未提供")
        chain_id = str(chain.get("id") or "PR?")
        title_safe = str(chain.get("title") or "").replace("|", "\\|")
        lines.append(
            f"| `{chain_id}` {title_safe} | `{status}` | {marker} {strength} "
            f"| {what} | {next_test} | {failure} | {priority} |"
        )
    lines.append("")
    for chain, _, items in entries:
        lines.extend([
            f"### 结论 · {chain.get('id', 'PR?')} · {chain.get('title', '未命名主线')}", "",
            *_plan_conclusion_verdict(chain, by_id, audit_status, study),
            *_plan_narrative(chain),
            *items,
            "",
        ])
    return lines


PLAN_SOURCE_LABELS = {
    "hackernews": "Hacker News",
    "reddit_arctic_shift": "Reddit（历史归档）",
    "reddit": "Reddit",
    "stackexchange": "Stack Exchange",
}


PLAN_ROLE_LABELS = {
    "open_scene": "场景与问题自述",
    "direct_solution": "解法使用与接受",
    "substitute_rejector": "替代、放弃与拒绝",
    "post_purchase_support": "已购后的使用与维护",
    "control": "对照与不认同",
}


def _capture_provenance_lines(records: list[dict[str, Any]], heading: str = "###") -> list[str]:
    """Project reviewed capture back-links without rendering OCR as a conclusion."""
    captures = [record for record in records
                if str(record.get("source_family") or "") == "capture"]
    if not captures:
        return []

    def cell(value: Any) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    lines = [
        f"{heading} 审核导入材料：来源回链", "",
        "| 证据 | 人工审核 | 来源 URL | Capture / 截图 | 来源哈希 |",
        "|---|---|---|---|---|",
    ]
    for record in captures:
        capture_ref = str(record.get("source_ref") or "")
        screenshot_ref = str(record.get("capture_screenshot_ref") or "")
        hashes = (
            f"page={record.get('capture_text_sha256') or '未记录'}; "
            f"OCR={record.get('capture_ocr_text_sha256') or '未记录'}; "
            f"screenshot={record.get('capture_screenshot_sha256') or '未记录'}"
        )
        review = f"{record.get('reviewed_by') or '未记录'} / {record.get('reviewed_at') or '未记录'}"
        source_links = f"capture: `{capture_ref}`; screenshot: `{screenshot_ref}`"
        lines.append(
            f"| `{cell(record.get('record_id'))}` | {cell(review)} | {cell(record.get('source_url'))} "
            f"| {cell(source_links)} | {cell(hashes)} |"
        )
    lines.extend([
        "",
        "这些回链只证明哪份候选经谁审核进入证据；OCR 文本不自动成为需求、七节点或做/缓做/不做结论。",
        "",
    ])
    return lines


def _plan_corpus_profile(records: list[dict[str, Any]]) -> list[str]:
    """语料画像：来源、年份、用途三类分布，只描述“看了多少”，不推人群比例。"""
    if not records:
        return []
    families: dict[str, int] = {}
    years: dict[str, int] = {}
    roles: dict[str, int] = {}
    for record in records:
        family = str(record.get("source_family") or "").strip() or "未记录"
        family = PLAN_SOURCE_LABELS.get(family, family)
        families[family] = families.get(family, 0) + 1
        year = _record_time(record)[:4]
        if year.isdigit():
            years[year] = years.get(year, 0) + 1
        role = str(record.get("corpus_role") or "").strip()
        label = PLAN_ROLE_LABELS.get(role, "其他")
        roles[label] = roles.get(label, 0) + 1
    lines: list[str] = ["### 语料画像", ""]
    lines.append("- 来源构成：" + " · ".join(f"{name} {count} 条" for name, count in sorted(families.items(), key=lambda item: -item[1])))
    if years:
        lines.append("- 年份分布：" + " · ".join(f"{year} 年 {count} 条" for year, count in sorted(years.items())))
    lines.append("- 用途构成：" + " · ".join(f"{label} {count} 条" for label, count in sorted(roles.items(), key=lambda item: -item[1])))
    lines.append("- 读法：这些数字说明“看了多少、看到哪几类人”，不代表人群比例，也不能外推市场规模。")
    lines.append("")
    return lines


def _plan_capability_lines(feature: dict[str, Any]) -> list[str]:
    """逐条特性：每个能力做什么、为什么能解决对应痛点、依据是什么。"""
    capabilities = feature.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return []
    lines: list[str] = ["", "**逐条特性**", ""]
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        name = str(capability.get("name") or "").strip()
        what = str(capability.get("what") or "").strip()
        solves = str(capability.get("solves") or "").strip()
        proof = str(capability.get("proof") or "").strip()
        if not name:
            continue
        text = f"- **{name}**：{what}" if what else f"- **{name}**"
        if what and not what.endswith(("。", "；", "！", "？")):
            text += "。"
        if solves:
            text += f"为什么能解决：{solves}"
            if not solves.endswith(("。", "；", "！", "？")):
                text += "。"
        if proof:
            text += f"（依据：{proof}）"
        lines.append(text)
    lines.append("")
    return lines if len(lines) > 2 else []


def _plan_lines(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any],
    audit_status: str = "not_run",
) -> list[str]:
    """业务方案 Business Plan：同一条七节点推理链的业务用户视图。

    正文只使用业务语言：每个环节给一句话结论与业务字段，判断的支撑以
    “数据基础”（来源/语料量/时间窗）与“用户之声”（原话引语）呈现；
    证据分级与状态枚举只进入文末的研究方法档案。本函数是纯投影：
    全部内容来自 study.json / 04-findings / 02-data，不产生新事实。
    """
    route = study.get("route") or {}
    decision = study.get("decision") or {}
    records = evidence.get("records", [])
    by_id = {str(record.get("record_id")): record for record in records}
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [chain for chain in chains if isinstance(chain, dict)]
    qualification = evidence.get("qualification") if isinstance(evidence.get("qualification"), dict) else {}
    lines: list[str] = [
        f"# 业务方案 Business Plan：{study.get('title', '')}",
        "",
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label') or _study_labels(study)[0]}；"
        f"阶段：{route.get('stage_label') or _study_labels(study)[1]}。",
        "",
        "> 读法：每个判断都标注**依据强度**——● 已观察到（多个来源族观察；相关性未证明独立）· ◐ 有线索（单案例或口头线索）· ○ 假设（尚无采集记录，待验证）——"
        "以及**数据基础**（来源、语料量、时间窗）与**来自语料的声音**（用户原话或典型情况）。"
        "“暂无采集数据”表示还没研究到这一步，不等于没有需求。",
        "",
        "> 时间分层：数字与图表截至最新输入时间，判断文字形成于判断链最后一次写入。"
        "两者不一致时以数字和图表的生成时间为准，并重跑 `askovo deliver <study> --kind plan` 重新生成判断。",
        "",
    ]
    if audit_status != "pass":
        lines.extend([
            "> **审计未通过：本方案不能作为已审核结论或签收依据。** "
            "请先运行 `askovo check --stage full` 并修复失败项。",
            "",
        ])

    conclusion = _plan_conclusion_lines(chains, records, by_id, audit_status, study)
    if conclusion:
        lines.extend(conclusion)

    # ── 1. 方案导读 ────────────────────────────────────────────
    lines.extend(["## 1. 方案导读", ""])
    lines.append(
        f"- 研究问题：{_gap_or_value(decision.get('question') or study.get('title'), '读者不知道这份方案回答什么', '补写决策问题或给研究命名', compact=True)}"
    )
    lines.append(
        f"- 负责人：{_gap_or_value(decision.get('owner'), '无法确定谁对结论负责', '补写决策负责人', compact=True)}；"
        f"截止：{_gap_or_value(decision.get('deadline'), '无法判断什么时候必须拍板', '补写截止时间', compact=True)}"
    )
    overall = _plan_basis(records)
    lines.append(f"- {overall}")
    lines.append("")
    if not chains:
        lines.extend([
            "尚未建立七节点推理（场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业）。"
            "先用 `askovo do` 建立研究框架并采集数据，再输出业务方案。",
            "",
        ])
    for chain in chains:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        chain_records: list[dict[str, Any]] = []
        chain_seen: set[str] = set()
        for node_name in REASONING_NODES:
            node = nodes.get(node_name, {})
            if not isinstance(node, dict):
                continue
            for record in _plan_node_records(node, by_id):
                record_id = str(record.get("record_id"))
                if record_id not in chain_seen:
                    chain_records.append(record)
                    chain_seen.add(record_id)
        chain_marker, chain_strength, _ = _plan_strength(chain_records)
        lines.append(f"**{chain.get('id', 'PR?')} · {chain.get('title', '未命名主线')}**"
                     f"（整体依据强度：{chain_marker} {chain_strength}）")
        lines.append("")
        lines.append("| 环节 | 结论（一句话） | 依据强度 | 数据基础 |")
        lines.append("|---|---|---|---|")
        for node_name in REASONING_NODES:
            node = nodes.get(node_name, {})
            if not isinstance(node, dict):
                continue
            node_records = _plan_node_records(node, by_id)
            basis = f"{len(node_records)} 条语料" if node_records else "暂无采集数据"
            node_marker, node_strength, _ = _plan_strength(node_records, node_name)
            statement = _gap_or_value(
                node.get("statement"),
                "本节判断不完整，无法据此决策",
                "补写该环节的一句话结论",
                compact=True,
            ).replace("|", "\\|")
            lines.append(
                f"| {REASONING_NODE_LABELS.get(node_name, node_name)} | {statement} "
                f"| {node_marker} {node_strength} | {basis} |"
            )
        lines.append("")

    profile = _plan_corpus_profile(records)
    if profile:
        lines.extend(profile)
    if len(chains) > 1:
        lines.extend([
            "> 多链说明：第 2–8 节只展开优先级最高的一条主线；其余候选链路的状态、下一步与失败线见第 0 节比较表和第 9 节，完整七环节见决策包或 `04-findings/product-reasoning.json`。",
            "",
        ])

    # ── 2–8. 七节点正文（逐链展开，业务语言） ──────────────────
    detail_chains = chains if len(chains) == 1 else chains[:1]
    for index, chain in enumerate(detail_chains, start=1):
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        chain_records: list[dict[str, Any]] = []
        chain_seen: set[str] = set()
        # One voice per document: quotes already shown in an earlier section
        # are not repeated by a later section citing the same records.
        used_quotes: set[str] = set()
        for node_name in REASONING_NODES:
            candidate = nodes.get(node_name, {})
            if not isinstance(candidate, dict):
                continue
            for record in _plan_node_records(candidate, by_id):
                record_id = str(record.get("record_id"))
                if record_id not in chain_seen:
                    chain_seen.add(record_id)
                    chain_records.append(record)
        if len(chains) > 1:
            lines.extend([f"### 方案主线 {index}：{chain.get('title', '未命名主线')}", ""])
        scene = nodes.get("scene", {}) if isinstance(nodes.get("scene"), dict) else {}
        lines.extend(_plan_section("2. 目标场景：哪些场景值得做", scene, by_id, [
            ("什么时候发生（触发）", scene.get("trigger")),
            ("在什么环境下", scene.get("environment")),
            ("用户当时在做什么（任务背景）", scene.get("task_context")),
        ], used_quotes=used_quotes, qualification=qualification))
        user = nodes.get("user", {}) if isinstance(nodes.get("user"), dict) else {}
        segments = []
        business_node = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
        for segment in business_node.get("segments", []) if isinstance(business_node.get("segments"), list) else []:
            if isinstance(segment, dict):
                payer_text = _gap_or_value(
                    segment.get("payer"), "无法判断这一层谁掏钱", "补写这一层的付费者", compact=True
                )
                segments.append(f"{segment.get('id', '分层')}：{segment.get('criteria', '')}（付费者：{payer_text}）")
        lines.extend(_plan_section("3. 目标用户：谁有这个需求", user, by_id, [
            ("角色", user.get("role")),
            ("现状", user.get("state")),
            ("在决策中的角色", user.get("decision_role")),
            ("用户分层", segments or None),
        ], used_quotes=used_quotes, qualification=qualification))
        pain = nodes.get("pain", {}) if isinstance(nodes.get("pain"), dict) else {}
        lines.extend(_plan_section("4. 痛点：现在怎么办、痛在哪", pain, by_id, [
            ("现在的替代做法", pain.get("current_substitute")),
            ("代价", pain.get("friction_cost")),
            ("不解决的后果", pain.get("consequence")),
        ], used_quotes=used_quotes, qualification=qualification))
        need = nodes.get("need", {}) if isinstance(nodes.get("need"), dict) else {}
        lines.extend(_plan_section("5. 需求：他们要的到底是什么", need, by_id, [
            ("期望的结果", need.get("desired_outcome")),
            ("约束", need.get("constraints")),
            ("怎么衡量做好了", need.get("measure")),
        ], used_quotes=used_quotes, qualification=qualification))
        feature = nodes.get("feature", {}) if isinstance(nodes.get("feature"), dict) else {}
        lines.extend(_plan_section("6. 产品特性：哪些特性能满足", feature, by_id, [
            ("特性", feature.get("capability")),
            ("生效条件与验收", feature.get("acceptance_conditions")),
            ("考虑过的替代做法", feature.get("alternatives_considered")),
        ], quote_limit=1, used_quotes=used_quotes, extra_lines=_plan_capability_lines(feature),
            qualification=qualification))
        product = nodes.get("product", {}) if isinstance(nodes.get("product"), dict) else {}
        lines.extend(_plan_section("7. 产品形态：推演出的产品", product, by_id, [
            ("形态", product.get("form")),
            ("范围", product.get("scope")),
            ("明确不做", product.get("non_goals")),
            ("上线验收", product.get("acceptance_criteria")),
        ], quote_limit=0, qualification=qualification))
        gate = business_node.get("gate", {}) if isinstance(business_node.get("gate"), dict) else {}
        success_metrics = []
        for metric in business_node.get("success_metrics", []) if isinstance(business_node.get("success_metrics"), list) else []:
            if isinstance(metric, dict):
                success_metrics.append(
                    f"{metric.get('metric_id', '指标')}：{metric.get('definition', '')}"
                    f"（口径：{metric.get('numerator', '—')}/{metric.get('denominator', '—')}，"
                    f"窗口：{_gap_or_value(metric.get('window'), '无法判断指标统计哪段时间', '补写统计窗口', compact=True)}，"
                    f"护栏：{_gap_or_value(metric.get('guardrail'), '无法判断指标恶化时谁叫停', '补写护栏指标', compact=True)}）"
                )
        pricing_points = []
        for price in business_node.get("pricing", []) if isinstance(business_node.get("pricing"), list) else []:
            if isinstance(price, dict):
                parts = [
                    str(price.get(field))
                    for field in ("model", "amount", "currency", "unit", "term", "note")
                    if price.get(field) is not None and str(price.get(field)).strip()
                ]
                pricing_points.append("，".join(parts) if parts else "记录未含金额（见方法档案）")
            else:
                pricing_points.append(str(price))
        lines.extend(_plan_section("8. 商业与 GTM：怎么走向市场", business_node, by_id, [
            ("市场边界", business_node.get("market_definition")),
            ("区域与时间窗", f"{_gap_or_value(business_node.get('geographies'), '无法判断结论适用于哪些地区', '列出覆盖区域', compact=True)}；{_gap_or_value(business_node.get('time_window'), '无法判断数据对应哪段时间', '写明起止时间', compact=True)}"),
            ("目标人群", business_node.get("target_segment")),
            ("付费者", business_node.get("payer")),
            ("定位", business_node.get("positioning")),
            ("渠道", business_node.get("channels")),
            ("定价方向", business_node.get("pricing_hypothesis")),
            ("已验证的价格点", pricing_points or "待验证（尚无成交数据）"),
            ("成本结构", business_node.get("cost_drivers")),
            ("成功指标", success_metrics or None),
            ("资源门禁", f"{gate.get('stage', 'G0')}：{_gap_or_value(gate.get('decision'), '无法判断这一关怎么过', '补写门禁结论', compact=True)}（负责人：{_gap_or_value(gate.get('owner'), '无法确定谁对投入负责', '补写负责人', compact=True)}；复审条件：{_gap_or_value(gate.get('revisit_trigger'), '无法知道何时重新评审', '补写复审触发条件', compact=True)}）" if gate else None),
        ], quote_limit=0, extra_lines=_plan_money_evidence(chain_records), qualification=qualification))

    # ── 9. 风险与下一步 ────────────────────────────────────────
    lines.extend(["## 9. 风险与下一步", ""])
    for chain in chains:
        if len(chains) > 1:
            lines.append(f"**{chain.get('id', 'PR?')} · {chain.get('title', '')}**")
            lines.append("")
        alternatives = chain.get("alternative_explanations", [])
        if isinstance(alternatives, list) and alternatives:
            lines.append("换个角度怎么看（还没被排除的替代解释）：")
            for item in alternatives:
                lines.append(f"- {item}")
            lines.append("")
        counter_ids = chain.get("counter_evidence_ids", [])
        if isinstance(counter_ids, list) and counter_ids:
            lines.append("数据里已经亮红灯的方向（反面信号）：")
            for record_id in counter_ids:
                record = by_id.get(str(record_id))
                if record is None:
                    continue
                excerpt = str(record.get("text_excerpt") or record.get("evidence_basis") or "").strip()
                lines.append(f"- {_plan_source_label(record)}：{excerpt[:100]}")
            lines.append("")
        if chain.get("next_test"):
            lines.append(f"- 下一步最便宜、最能改变决策的验证：{chain.get('next_test')}")
        if chain.get("failure_condition"):
            lines.append(f"- 什么情况说明这个方向错了：{chain.get('failure_condition')}")
        gaps = chain.get("gaps", [])
        if isinstance(gaps, list) and gaps:
            lines.append("- 待补的研究缺口：")
            for item in gaps:
                lines.append(f"  - {item}")
        lines.append("")
    if not chains:
        lines.append("（建立七节点推理后，本节给出替代解释、反面信号与下一步验证。）")
        lines.append("")

    # ── 附录：研究方法档案（引擎词汇只出现在这里） ─────────────
    lines.extend(["## 附录：研究方法档案", ""])
    family_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    for record in records:
        family = str(record.get("source_family") or "未记录")
        family_counts[family] = family_counts.get(family, 0) + 1
        review = str(record.get("human_review_status") or "未记录")
        review_counts[review] = review_counts.get(review, 0) + 1
        level = str(record.get("evidence_level") or "unclassified")
        level_counts[level] = level_counts.get(level, 0) + 1
    lines.append("| 来源 | 条数 |")
    lines.append("|---|---|")
    for family in sorted(family_counts):
        lines.append(f"| {family} | {family_counts[family]} |")
    lines.append("")
    lines.append(f"- 样本量：{len(records)} 条语料；时间窗：{_plan_time_span(records) or '未记录'}")
    lines.append(f"- 证据等级分布：{json.dumps(level_counts, ensure_ascii=False)}；人工复核状态：{json.dumps(review_counts, ensure_ascii=False)}")
    lines.append("- 依据强度规则（确定性，从各环节引用记录计算，非人工指定）：● = 观察级记录（E2/E3/E4+/E5："
                 "行为、接受或付费）≥2 条且来自 ≥2 个来源族；◐ = 存在 E1 及以上记录但未达 ●；"
                 "○ = 无 E1 及以上记录。E4-（拒绝/退订等反向行为）计入反面信号，不计入强度。"
                 "多个来源族只表示 source_family 字符串不同，相关性未证明独立；强度是阅读辅助，不证明总体比例、市场规模或因果。")
    chain_states = "；".join(f"{chain.get('id', 'PR?')}={chain.get('status', '')}" for chain in chains) or "未建立"
    lines.append(f"- 链/判定状态（原始口径）：{chain_states}")
    lines.append(f"- 结构审计：{audit_status}（`askovo check --stage full`）")
    prohibited = (study.get("scope") or {}).get("prohibited_inferences", [])
    if isinstance(prohibited, list) and prohibited:
        lines.append("- 本方案禁止的推断：")
        for item in prohibited:
            lines.append(f"  - {item}")
    lines.append("")
    lines.extend(_capture_provenance_lines(records))

    lines.extend([
        "## 边界",
        "",
        "本方案是七节点推理链的业务视图，不证明总体比例、市场规模或因果；"
        "“暂无采集数据”的判断待数据补齐后更新；最终产品与商业决定由负责人做出并留痕。",
    ])
    return lines



def _collection_summary(study_dir: Path) -> dict[str, Any]:
    """Optional researcher-written funnel totals for multi-wave/multi-study corpora."""
    path = study_dir / "01-sources" / "collection-summary.json"
    if not path.is_file():
        return {}
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _analysis_lines(study: dict[str, Any], reasoning: dict[str, Any] | None, evidence: dict[str, Any], study_dir: Path) -> list[str]:
    """语料分析：采集漏斗、来源与时间、用途、判断覆盖、集中度与反证。

    只做确定性统计，不推断人群比例、市场规模或因果。数字来自 02-data 与
    04-findings，任何缺项都如实显示为 0 或“未采集”。
    """
    records = evidence.get("records", []) if isinstance(evidence, dict) else []
    by_id = {str(record.get("record_id")): record for record in records}
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [chain for chain in chains if isinstance(chain, dict)]
    lines: list[str] = [
        f"# 语料分析：{study.get('title', '')}",
        "",
        "> 这份报告只描述采集到什么、覆盖到谁，不推算人群比例或市场规模；判断是否成立仍以证据链与人工复核为准。",
        "",
    ]

    # 1. 漏斗
    raw_ids: set[str] = set()
    raw_total = 0
    raw_files = sorted((study_dir / "02-data" / "raw").glob("**/*.jsonl"))
    for path in raw_files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw_total += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = str(item.get("id") or item.get("record_id") or item.get("objectID") or "")
                if key:
                    raw_ids.add(key)
        except OSError:
            continue
    raw_lines = len(raw_ids) or raw_total
    funnel_source = "02-data/raw 去重后的条数（跨波次重复已合并）"
    summary = _collection_summary(study_dir)
    if summary.get("raw_records"):
        try:
            raw_lines = int(summary["raw_records"])
            funnel_source = "01-sources/collection-summary.json 登记的五波累计口径"
        except (TypeError, ValueError):
            pass
    screened_ids: set[str] = set()
    for path in sorted((study_dir / "02-data").glob("screened-*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    screened_ids.add(str(json.loads(line).get("id") or ""))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    judged: set[str] = set()
    judgments = load_json(study_dir / "04-findings" / "demand-judgments.json")
    if isinstance(judgments, list):
        for judgment in judgments:
            if not isinstance(judgment, dict):
                continue
            for key in ("problem_evidence_ids", "solution_evidence_ids", "commercial_evidence_ids", "counter_evidence_ids"):
                for value in judgment.get(key) or []:
                    judged.add(str(value))
    screened_count = len([value for value in screened_ids if value])
    if summary.get("screened_records"):
        try:
            screened_count = int(summary["screened_records"])
        except (TypeError, ValueError):
            pass
    lines.extend([
        "## 1. 采集漏斗", "",
        "| 阶段 | 数量 | 口径 |",
        "|---|---|---|",
        f"| 原始记录 | {raw_lines} | {funnel_source} |",
        f"| 关键词筛选 | {screened_count} | screened-*.jsonl 去重后的条数 |",
        f"| 编码证据 | {len(records)} | 02-data/evidence.jsonl 的条数 |",
        f"| 进入判断 | {len(judged)} | 需求判断引用的唯一条数 |",
        "",
    ])

    # 2. 来源与时间
    families: dict[str, int] = {}
    years: dict[str, int] = {}
    channels: dict[str, int] = {}
    for record in records:
        family = str(record.get("source_family") or "未记录").strip() or "未记录"
        families[family] = families.get(family, 0) + 1
        year = _record_time(record)[:4]
        if year.isdigit():
            years[year] = years.get(year, 0) + 1
        channel = str(record.get("source_channel") or "").strip()
        if channel:
            channels[channel] = channels.get(channel, 0) + 1
    total = len(records) or 1
    lines.extend(["## 2. 来源与时间", "", "| 来源 | 条数 | 占比 |", "|---|---|---|"])
    for name, count in sorted(families.items(), key=lambda item: -item[1]):
        lines.append(f"| {PLAN_SOURCE_LABELS.get(name, name)} | {count} | {count / total:.0%} |")
    lines.append("")
    if years:
        lines.append("- 年份分布：" + " · ".join(f"{year} 年 {count} 条" for year, count in sorted(years.items())))
    span = _plan_time_span(records)
    if span:
        lines.append(f"- 时间窗：{span}")
    lines.append("")

    # 3. 用途与强度
    roles: dict[str, int] = {}
    observed = 0
    rejected = 0
    for record in records:
        role = str(record.get("corpus_role") or "").strip()
        label = PLAN_ROLE_LABELS.get(role, "其他")
        roles[label] = roles.get(label, 0) + 1
        level = str(record.get("evidence_level") or "").strip()
        if level in {"E2", "E3", "E4+", "E5"}:
            observed += 1
        if level == "E4-":
            rejected += 1
    lines.extend(["## 3. 语料用途", "", "| 用途 | 条数 | 占比 |", "|---|---|---|"])
    for name, count in sorted(roles.items(), key=lambda item: -item[1]):
        lines.append(f"| {name} | {count} | {count / total:.0%} |")
    lines.append("")
    lines.append(f"- 观察级记录（做过、接受或付费）：{observed} 条；拒绝与反向行为：{rejected} 条。")
    top_families = [name for name, _ in sorted(families.items(), key=lambda item: -item[1])[:3]]
    if top_families:
        lines.extend(["", "### 来源 × 用途", "", "| 用途 | " + " | ".join(PLAN_SOURCE_LABELS.get(name, name) for name in top_families) + " |", "|---|" + "---|" * len(top_families)])
        for role_name, _ in sorted(roles.items(), key=lambda item: -item[1]):
            cells = []
            for family in top_families:
                count = 0
                for record in records:
                    record_role = PLAN_ROLE_LABELS.get(str(record.get("corpus_role") or "").strip(), "其他")
                    record_family = str(record.get("source_family") or "未记录").strip() or "未记录"
                    if record_role == role_name and record_family == family:
                        count += 1
                cells.append(str(count))
            lines.append(f"| {role_name} | " + " | ".join(cells) + " |")
        lines.append("")
    lines.append("")

    # 4. 判断覆盖
    lines.extend(["## 4. 判断覆盖", "", "| 环节 | 引用条数 | 观察条数 | 平台数 | 依据强度 |", "|---|---|---|---|---|"])
    empty_nodes: list[str] = []
    for chain in chains:
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        for node_name in REASONING_NODES:
            node = nodes.get(node_name, {}) if isinstance(nodes.get(node_name), dict) else {}
            node_records = _plan_node_records(node, by_id)
            if not node_records:
                empty_nodes.append(REASONING_NODE_LABELS.get(node_name, node_name))
            marker, strength, _ = _plan_strength(node_records, node_name)
            observed_levels = _plan_observed_levels(node_name)
            observed_count = sum(1 for record in node_records if str(record.get("evidence_level") or "") in observed_levels)
            platforms = {str(record.get("source_family") or "") for record in node_records if record.get("source_family")}
            lines.append(
                f"| {REASONING_NODE_LABELS.get(node_name, node_name)} | {len(node_records)} | {observed_count} | {len(platforms)} | {marker} {strength} |"
            )
    lines.append("")
    if empty_nodes:
        lines.append("- 尚未有证据的环节：" + "、".join(empty_nodes) + "。")
    lines.append("")

    # 5. 集中度与重复
    top_family = max(families.items(), key=lambda item: item[1]) if families else ("", 0)
    top_channel = max(channels.items(), key=lambda item: item[1]) if channels else ("", 0)
    hashes: dict[str, int] = {}
    for record in records:
        value = str(record.get("normalized_text_hash") or "")
        if value:
            hashes[value] = hashes.get(value, 0) + 1
    duplicates = sum(1 for count in hashes.values() if count > 1)
    lines.extend(["## 5. 集中度与重复", ""])
    if top_family[0]:
        lines.append(f"- 最大来源：{PLAN_SOURCE_LABELS.get(top_family[0], top_family[0])}，占 {top_family[1] / total:.0%}。")
    if top_channel[0]:
        lines.append(f"- 最大渠道/子版：{top_channel[0]}，{top_channel[1]} 条。")
    lines.append(f"- 重复文本：{duplicates} 组。")
    if top_family[1] / total > 0.65:
        lines.append("- 提示：单一来源超过三分之二，结论只能算这个平台的观察，不能外推。")
    lines.append("")

    # 6. 反证
    counter_ids: set[str] = set()
    for chain in chains:
        for value in chain.get("counter_evidence_ids") or []:
            counter_ids.add(str(value))
    counter_records = [by_id[value] for value in counter_ids if value in by_id]
    lines.extend(["## 6. 反证", ""])
    lines.append(f"- 链上登记的反证：{len(counter_records)} 条。")
    for record in counter_records[:8]:
        excerpt = str(record.get("text_excerpt") or record.get("evidence_basis") or "").strip()
        lines.append(f"  - {PLAN_SOURCE_LABELS.get(str(record.get('source_family') or ''), str(record.get('source_family') or ''))}：{excerpt[:80]}")
    gaps: list[str] = []
    for chain in chains:
        for item in chain.get("gaps") or []:
            gaps.append(str(item))
    if gaps:
        lines.append("- 已登记的缺口：")
        for item in gaps[:8]:
            lines.append(f"  - {item}")
    lines.append("")

    # 7. 能回答与不能回答
    lines.extend([
        "## 7. 这份数据能回答什么",
        "",
        "- 能回答：谁在什么场景遇到什么问题、他们现在怎么做、哪些做法被反复判无效、这些说法出现在哪个平台。",
        "- 不能回答：这类人占多大比例、市场规模多大、他们愿意为本品付多少钱；最后一条只能靠真实报价与成交来验。",
        "",
    ])
    # 8. 候选主题、机制与重复归并（确定性统计，不改变证据边界）
    stop = set("the and for with that this from are was were you your our not but have has had will can could should about into over under more most some such than then them they their there here what when where which who whom why how all any both each few other own same so too very just also".split())
    topics = _analysis_topics(records, stop)
    if topics:
        lines.extend(["## 8. 候选主题（共现聚合）", ""])
        for index, topic in enumerate(topics, start=1):
            lines.append(
                f"{index}. **{' / '.join(topic['terms'])}**（{topic['record_count']} 条）"
                f" · 例：{', '.join(topic['example_record_ids'])}")
        lines.append("> 共现聚合只是候选主题，不是总体主题比例；需要人工命名与复核。")
        lines.append("")
    mechanisms = _analysis_mechanisms(records)
    if mechanisms:
        lines.extend(["## 9. 机制与转折句（候选）", ""])
        for item in mechanisms[:12]:
            lines.append(
                f"- [{item['kind']}] `{item['record_id']}`（{item['platform']} / {item['evidence_level']}）：{item['text']}")
        lines.append("> 含因果/转折词的句子是候选机制或反证线索，不等于已验证因果。")
        lines.append("")
    duplicates = _analysis_duplicates(records)
    lines.extend([
        "## 10. 重复与独立记录", "",
        f"- 重复组：{len(duplicates['duplicate_groups'])}；重复记录：{duplicates['duplicate_records']}；去重后独立记录：{duplicates['unique_records']}",
        f"> {duplicates['note']}",
        "",
    ])
    lines.extend(_capture_provenance_lines(records, heading="## 11."))
    lines.extend([
        "## 边界",
        "",
        "本报告是语料的描述性统计，不证明总体比例、市场规模或因果；样本来自公开社区，说话的人不等于目标人群，条数不等于需求强度。",
        "",
    ])
    return lines


def _report_risk_lines(reasoning: dict[str, Any] | None, by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Fill the combined report's counter-evidence / gap / next-step section."""
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [chain for chain in chains if isinstance(chain, dict)]
    lines = [
        "## 反证、缺口与下一步", "",
        "> 这一节只列已登记的替代解释、反面信号、缺口与验证动作；没有记录的方向写“未登记”，不补假设。", "",
    ]
    if not chains:
        lines.extend(["（尚未建立七节点链，暂无反证与缺口。）", ""])
        return lines
    for chain in chains:
        lines.extend([f"### {chain.get('id', 'PR?')} · {chain.get('title', '')}", ""])
        alternatives = chain.get("alternative_explanations") or []
        lines.append("**替代解释**")
        if isinstance(alternatives, list) and alternatives:
            for item in alternatives:
                lines.append(f"- {item}")
        else:
            lines.append("- 未登记")
        lines.append("")
        lines.append("**反面信号**")
        counter_ids = chain.get("counter_evidence_ids") or []
        printed = 0
        for record_id in counter_ids if isinstance(counter_ids, list) else []:
            record = by_id.get(str(record_id))
            if record is None:
                continue
            excerpt = _evidence_text(record)[:110]
            lines.append(f"- `{record_id}` · {_plan_source_label(record)}：{excerpt}")
            printed += 1
            if printed >= 5:
                lines.append(f"- 其余 {max(0, len(counter_ids) - printed)} 条见 `02-data/evidence.jsonl`")
                break
        if not printed:
            lines.append("- 未登记")
        lines.append("")
        lines.append("**缺口**")
        gaps = chain.get("gaps") or []
        if isinstance(gaps, list) and gaps:
            for item in gaps:
                lines.append(f"- {item}")
        else:
            lines.append("- 未登记")
        lines.append("")
        if chain.get("next_test"):
            lines.append(f"**下一验证**：{chain.get('next_test')}")
            lines.append("")
        if chain.get("failure_condition"):
            lines.append(f"**失败线**：{chain.get('failure_condition')}")
            lines.append("")
    return lines


def _report_decision_lines(reasoning: dict[str, Any] | None, by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Fill the combined report's decision section instead of leaving placeholders."""
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [chain for chain in chains if isinstance(chain, dict)]
    lines = ["## 2. 产品决策", ""]
    decided = [chain for chain in chains if str(chain.get("status") or "") == "decided"]
    if not decided:
        lines.extend([
            "> 没有任何链达到 `decided`。以下是待验证建议与缺口，不是产品/商业决定记录；"
            "“先做哪条”是当前证据下的排序建议，不证明需求、付费或因果。",
            "",
        ])
    else:
        lines.extend([f"> 已记录的 `decided` 链：{', '.join(str(chain.get('id')) for chain in decided)}。"
                      "`decided` 只记录产品/商业选择，不等于发布就绪或商业成功。", ""])
    lines.extend([
        "| 链路 | 状态 | 依据强度 | 建议 | 下一步验证 | 失败线 |",
        "|---|---|---|---|---|---|",
    ])
    for chain in chains:
        chain_records = _plan_chain_records(chain, by_id)
        marker, strength, _ = _plan_strength(chain_records)
        priority = str((chain.get("prioritization") or {}).get("rationale") or "未排序").replace("|", "\\|")
        next_test = str(chain.get("next_test") or "待补").replace("|", "\\|")
        failure = str(chain.get("failure_condition") or "待补").replace("|", "\\|")
        title = str(chain.get("title") or "").replace("|", "\\|")
        lines.append(
            f"| `{chain.get('id', 'PR?')}` {title} | `{chain.get('status', 'unknown')}` | {marker} {strength} "
            f"| {priority} | {next_test} | {failure} |"
        )
    lines.append("")
    gaps = []
    for chain in chains:
        for gap in chain.get("gaps", []) if isinstance(chain.get("gaps"), list) else []:
            gaps.append(f"- {chain.get('id', 'PR?')}：{gap}")
    if gaps:
        lines.extend(["**待补缺口**", "", *gaps, ""])
    lines.extend([
        "**决定前的最低动作**：先完成上一节各链的 `next_test`；任何声称“已验证”的结论都需要 E3（方案接受）与 E4+/E5（付费/采购）证据，且证据与判断共享同一 `context_key`。",
        "",
    ])
    return lines


FORMAL_DELIVERY_KINDS = frozenset({
    "memo", "report", "mrd", "prd", "brd", "ops", "decision", "signoff",
    "plan", "needs", "analysis", "web", "role",
})
EVIDENCE_GATE_VERSION = "askovo-evidence-gate/1"
_EVIDENCE_SOURCE_PREFIXES = (
    "01-sources/", "02-data/", "03-analysis/", "04-findings/", "05-audit/", "06-report/",
)


def _study_source_problem(study_dir: Path, source_ref: str) -> str:
    """Return why a study-relative source reference is unreadable, else ''.

    URLs, platform ids and free-text references are not files; only a
    study-relative path can be re-opened and compared with the reviewed record.
    """
    if not source_ref or "://" in source_ref or not source_ref.startswith(_EVIDENCE_SOURCE_PREFIXES):
        return ""
    path = study_dir / source_ref
    try:
        if not path.is_file():
            return "missing"
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return str(exc)[:160]
    return ""


def evidence_delivery_gate(study_dir: Path, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide whether a formal deliverable may be rendered from this evidence store.

    Delivery is the moment a report can look authoritative. Zero registered
    evidence, a registered record whose reviewed source file can no longer be
    read, or a store with no decision-grade record (E1+) must stop formal
    deliverables: the honest output is an evidence-gap note, never a
    conclusion-shaped report (review 2026-11-20, P0-A).
    """
    study_dir = Path(study_dir).resolve()
    evidence = evidence if evidence is not None else _evidence_summary(study_dir)
    records = [record for record in evidence.get("records", []) if isinstance(record, dict)]
    level_counts: dict[str, int] = {}
    unreadable: list[dict[str, str]] = []
    for record in records:
        level = str(record.get("evidence_level") or "unknown")
        level_counts[level] = level_counts.get(level, 0) + 1
        source_ref = str(record.get("source_ref") or "").strip()
        problem = _study_source_problem(study_dir, source_ref)
        if problem:
            unreadable.append({
                "record_id": str(record.get("record_id") or "<unknown>"),
                "source_ref": source_ref,
                "problem": problem,
            })
    decision_grade = sum(count for level, count in level_counts.items() if level != "E0")
    gate: dict[str, Any] = {
        "gate_version": EVIDENCE_GATE_VERSION,
        "checked_at": now(),
        "evidence_count": len(records),
        "collected_count": int(evidence.get("collected_count") or 0),
        "level_counts": dict(sorted(level_counts.items())),
        "decision_grade_count": decision_grade,
        "unreadable_sources": unreadable,
        "gaps": [],
        "reason_code": "",
        "reason": "",
        "next_required_action": "",
    }
    if not records:
        gate["reason_code"] = "EVIDENCE_EMPTY"
        gate["reason"] = (
            "02-data/evidence.jsonl 中没有已登记证据；采集库存"
            f"（{gate['collected_count']} 条）不计入依据。"
        )
        gate["gaps"].append("没有任何已登记（人工审核）证据记录")
        gate["next_required_action"] = (
            "先采集并人工核级证据（`askovo capture` / `askovo import`），"
            "再运行 `askovo check --stage full`。"
        )
    elif unreadable:
        gate["reason_code"] = "EVIDENCE_SOURCE_UNREADABLE"
        gate["reason"] = (
            f"{len(unreadable)} 条已登记证据的原始来源文件缺失或不可读，"
            "无法证明交付依据仍是人工审核过的那一份。"
        )
        gate["gaps"].extend(
            f"`{item['record_id']}` 的来源 `{item['source_ref']}` 不可读（{item['problem']}）"
            for item in unreadable
        )
        gate["next_required_action"] = (
            "恢复或重新采集这些来源，重新执行人工审核（`askovo capture accept`），"
            "再运行 `askovo check --stage full`。"
        )
    elif decision_grade == 0:
        gate["reason_code"] = "EVIDENCE_UNQUALIFIED"
        gate["reason"] = (
            f"{len(records)} 条已登记证据全部为 E0（背景/陈述），没有任何 E1+ 可决策证据。"
        )
        gate["gaps"].append("全部证据为 E0；缺少至少一条 E1+（自述/行为/接受/付费/留存）证据")
        gate["next_required_action"] = (
            "补充或升级到至少 E1+ 证据（`askovo capture accept --observation ...`、"
            "`askovo import`），再运行 `askovo check --stage full`。"
        )
    gate["ok"] = not gate["reason_code"]
    return gate


def _write_evidence_gap(study_dir: Path, kind: str, gate: dict[str, Any]) -> Path:
    """Write the only honest artifact when the evidence gate blocks delivery."""
    out_dir = Path(study_dir) / "06-report"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "evidence-gap.md"
    levels = "、".join(f"{level}×{count}" for level, count in gate["level_counts"].items()) or "无"
    lines = [
        "# 证据缺口说明（不是结论）",
        "",
        f"> 交付请求：`{kind}`。状态：**blocked** — 未生成正式交付物。",
        f"> 证据门：`{gate['gate_version']}`；检查时间：{gate['checked_at']}；原因码：`{gate['reason_code']}`。",
        "",
        "## 为什么没有生成交付物",
        "",
        gate["reason"],
        "",
        "## 证据概况",
        "",
        f"- 已登记证据：{gate['evidence_count']} 条（等级分布：{levels}）",
        f"- 可决策证据（E1+）：{gate['decision_grade_count']} 条",
        f"- 仅采集未评级：{gate['collected_count']} 条（采集 ≠ 证据，不计入依据）",
        "",
        "## 缺口",
        "",
        *[f"- {item}" for item in gate["gaps"]],
        "",
        "## 合法下一动作",
        "",
        gate["next_required_action"],
        "",
        "## 边界",
        "",
        "本文件只说明证据缺口，不构成市场、需求、产品、商业、发布或合规结论；"
        "补齐证据并重新运行 `askovo check --stage full` 与 `askovo deliver` 后，才会生成正式交付物。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _deliver_artifact(
    study_dir: Path,
    kind: str = "memo",
    audit: Any | None = None,
    role_id: str | None = None,
    industry: str | None = None,
    deliverable_id: str | None = None,
    chain_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    baseline: str | Path | None = None,
) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    route = study.get("route") or {}
    evidence = evidence if evidence is not None else _evidence_summary(study_dir)
    by_id = {str(record.get("record_id")): record for record in evidence.get("records", [])}
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
    if kind in FORMAL_DELIVERY_KINDS:
        gate = evidence_delivery_gate(study_dir, evidence=evidence)
        if not gate["ok"]:
            gap_path = _write_evidence_gap(study_dir, kind, gate)
            return {
                "status": "blocked",
                "kind": kind,
                "audit_status": audit_status,
                "reason_code": gate["reason_code"],
                "reason": gate["reason"],
                "evidence_count": gate["evidence_count"],
                "level_counts": gate["level_counts"],
                "gap_path": str(gap_path),
                "next_required_action": gate["next_required_action"],
                "boundary": "证据门只阻断正式交付物，不评价已有证据质量，也不构成任何结论。",
                "gate": gate,
            }
    if kind == "lifecycle":
        workplan_path = study_dir / "01-sources" / "role-workbench" / "workplan.json"
        workplan = load_json(workplan_path) if workplan_path.is_file() else None
        projection = role_catalog.project_lifecycle(study, reasoning, workplan, audit_status)
        path = out_dir / "lifecycle-board.md"
        path.write_text(projection["markdown"], encoding="utf-8")
        return {
            "status": "written", "path": str(path), "kind": kind,
            "audit_status": audit_status,
            "audit_generated_at": audit_info.get("generated_at", ""),
            "workplan_bound": projection["workplan_bound"],
            "catalog_sha256": projection["catalog_sha256"],
            "assignment_count": projection["assignment_count"],
            "handoff_edge_count": projection["handoff_edge_count"],
            "work_status_counts": projection["work_status_counts"],
            "canonical_projection": True,
        }
    if kind == "role":
        if not role_id:
            return {"status": "blocked", "kind": kind, "audit_status": audit_status, "reason": "--role is required for a role projection"}
        if reasoning is None:
            return {"status": "blocked", "kind": kind, "audit_status": audit_status, "reason": "no canonical product-reasoning chain exists; role delivery cannot author one"}
        workplan_path = study_dir / "01-sources" / "role-workbench" / "workplan.json"
        workplan = load_json(workplan_path) if workplan_path.is_file() else None
        projection = role_catalog.project_role_deliverable(
            study, reasoning, evidence, role_id, industry, deliverable_id, audit_status,
            workplan=workplan, chain_id=chain_id,
        )
        path = out_dir / f"role-{projection['deliverable_id']}.md"
        path.write_text(projection["markdown"], encoding="utf-8")
        return {
            "status": "written",
            "path": str(path),
            "kind": kind,
            "audit_status": audit_status,
            "audit_generated_at": audit_info.get("generated_at", ""),
            "evidence_count": evidence["count"],
            "role_id": projection["role_id"],
            "deliverable_id": projection["deliverable_id"],
            "industry_id": projection["industry_id"],
            "projected_chain_ids": projection["projected_chain_ids"],
            "chain_id": chain_id or (projection["projected_chain_ids"][0] if len(projection["projected_chain_ids"]) == 1 else None),
            "catalog_sha256": projection["catalog_sha256"],
            "workplan_bound": projection["workplan_bound"],
            "workplan": str(workplan_path) if workplan is not None else None,
            "canonical_projection": True,
            "work_notes_separate": True,
        }
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

    if kind == "web":
        delta_status: dict[str, Any] | None = None
        try:
            import research_delta
            delta_status = research_delta.status(study_dir)
        except (OSError, ValueError, ImportError):
            delta_status = None
        rendered = web_surface.render(
            study_dir,
            study=study,
            reasoning=reasoning,
            evidence=evidence,
            audit_info=audit_info,
            delta_status=delta_status,
            funnel=_collection_summary(study_dir),
            helpers={
                "strength": _plan_strength,
                "basis": _plan_basis,
                "source_label": _plan_source_label,
                "time_span": _plan_time_span,
            },
        )
        return {
            "status": "written",
            "path": rendered["path"],
            "kind": kind,
            "audit_status": audit_status,
            "audit_generated_at": audit_info.get("generated_at", ""),
            "evidence_count": evidence["count"],
            "product_reasoning": product_reasoning_summary(reasoning),
            "assets_copied": len(rendered["assets"]),
            "warnings": rendered["warnings"],
            "number_stale": rendered["layers"]["number_stale"],
        }
    titles = {"memo": "决策备忘", "report": "产品推理报告", "mrd": "MRD 市场需求文档", "prd": "PRD 产品需求文档", "brd": "BRD 商业需求文档", "ops": "用户运营交付", "decision": "决策包 Decision Package", "signoff": "干系人签收页", "plan": "业务方案 Business Plan", "analysis": "语料分析 Corpus Analysis"}
    title = titles.get(kind, "交付物")
    if kind == "needs":
        baseline_reasoning = None
        baseline_ref = ""
        if baseline:
            baseline_reasoning, baseline_ref = needs_delivery.load_baseline(baseline)
        comparison = (
            needs_delivery.compare(reasoning, baseline_reasoning)
            if baseline_reasoning is not None else None
        )
        path = out_dir / "needs.md"
        path.write_text(
            needs_delivery.render(
                study, reasoning, evidence, audit_status,
                baseline=baseline_reasoning, baseline_ref=baseline_ref,
            ),
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
            "baseline": baseline_ref or None,
            "comparison": comparison,
        }
    if kind == "plan":
        path = out_dir / "plan.md"
        path.write_text(
            "\n".join(_plan_lines(study, reasoning, evidence, audit_status)) + "\n",
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
    if kind == "analysis":
        path = out_dir / "analysis.md"
        path.write_text(
            "\n".join(_analysis_lines(study, reasoning, evidence, study_dir)) + "\n",
            encoding="utf-8",
        )
        return {
            "status": "written",
            "path": str(path),
            "kind": kind,
            "audit_status": audit_status,
            "evidence_count": evidence["count"],
        }
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
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label') or _study_labels(study)[0]}；"
        f"阶段：{route.get('stage_label') or _study_labels(study)[1]}。",
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
        funnel = _collection_summary(study_dir)
        methods = ", ".join(study.get("selected_methods", [])) or "未登记"
        sample_bits = []
        if funnel.get("raw_records"):
            sample_bits.append(f"原始 {funnel.get('raw_records')} 条")
        if funnel.get("screened_records"):
            sample_bits.append(f"筛选 {funnel.get('screened_records')} 条")
        sample_bits.append(f"编码 {evidence.get('count', 0)} 条")
        lines.extend(
            [
                "## 研究方法与样本（支撑层）",
                "",
                f"- 方法：{methods}",
                f"- 样本与流失：{' → '.join(sample_bits)}（漏斗与偏差见 `06-report/analysis.md`）",
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
    elif kind == "prd" and reasoning is not None:
        lines.extend(_prd_lines(reasoning))
    elif kind == "ops" and reasoning is not None:
        lines.extend(_user_ops_lines(reasoning))
    elif kind == "report" and reasoning is not None:
        lines.extend(_report_decision_lines(reasoning, by_id))
    else:
        if reasoning is not None:
            chains = reasoning.get("chains", [])
            first = next((item for item in chains if isinstance(item, dict)), {}) if isinstance(chains, list) else {}
            nodes = first.get("nodes", {}) if isinstance(first.get("nodes"), dict) else {}
            product = nodes.get("product", {}) if isinstance(nodes.get("product"), dict) else {}
            business = nodes.get("business", {}) if isinstance(nodes.get("business"), dict) else {}
            lines.extend(
                [
                    "## 2. 产品决策",
                    "",
                    f"- 产品判断：{_gap_or_value(product.get('statement'), '无法判断这次交付什么', '补写产品节点的一句话结论', compact=True)}",
                    f"- 商业判断：{_gap_or_value(business.get('statement'), '无法判断是否值得投入', '补写商业节点的一句话结论', compact=True)}",
                    "- 取舍与代价：以第 1 节推理链与文末的替代解释、缺口为准，本节不另拟结论。",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "## 2. 产品决策",
                    "",
                    "本次交付没有可投影的七节点推理链，因此本节不生成建议。"
                    "先建立 `04-findings/product-reasoning.json` 的场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业，再交付决策建议。",
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
            or _evidence_text(record)
            or ""
        )[:120].replace("|", "\\|")
        lines.append(
            f"| `{record.get('record_id')}` | {_evidence_claim(record)} | "
            f"{_evidence_form(record)} | {basis} |"
        )
    if not evidence["records"]:
        lines.append("| — | — | — | 尚无导入证据 |")
    unresolved = _unresolved_chain_references(reasoning, evidence)
    if unresolved:
        lines.append("")
        lines.append(
            "链条引用了未评级/未登记的记录（仅存在于采集库或不存在），不得计入依据："
            + ", ".join(f"`{value}`" for value in unresolved)
        )
    if reasoning is not None:
        lines.extend(_report_risk_lines(reasoning, by_id))
    else:
        lines.extend(
            [
                "",
                "## 反证、缺口与下一步",
                "",
                "尚未建立推理主链，暂无已登记的反证、缺口与下一验证；先补齐七环节，再回到本节。",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## 附录：证据概况",
            "",
            f"- 记录数：{evidence['count']}",
            f"- 采集未评级记录数：{evidence.get('collected_count', 0)}（采集 ≠ 证据，不计入依据）",
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


def _delivery_audit_info(audit: Any | None) -> dict[str, Any]:
    if audit is not None and hasattr(audit, "as_dict"):
        return audit.as_dict()
    if isinstance(audit, dict):
        return audit
    return {"status": "not_run", "generated_at": "", "checks": []}


def _with_chat_summary(
    study_dir: Path,
    kind: str,
    result: dict[str, Any],
    audit: Any | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach one canonical, structured and readable projection to every result."""
    study_dir = Path(study_dir).resolve()
    try:
        study = load_json(study_dir / "study.json")
        if not isinstance(study, dict):
            study = {}
    except (OSError, json.JSONDecodeError, ValueError):
        study = {}
    try:
        reasoning = load_product_reasoning(study_dir)
    except (OSError, json.JSONDecodeError, ValueError):
        reasoning = None
    if evidence is None:
        try:
            evidence = _evidence_summary(study_dir)
        except (OSError, ValueError):
            evidence = {"count": 0, "records": [], "collected_count": 0, "collected_records": [], "by_form": {}, "by_claim": {}}
    result["chat_summary"] = delivery_projection.build_chat_summary(
        study_dir,
        kind,
        result,
        study=study,
        reasoning=reasoning,
        evidence=evidence,
        audit_info=_delivery_audit_info(audit),
    )
    return result


def deliver(
    study_dir: Path,
    kind: str = "memo",
    audit: Any | None = None,
    role_id: str | None = None,
    industry: str | None = None,
    deliverable_id: str | None = None,
    chain_id: str | None = None,
    baseline: str | Path | None = None,
) -> dict[str, Any]:
    # One delivery run, one evidence-store read: the artifact and its chat
    # summary must see the same snapshot even if files change mid-run.
    evidence = _evidence_summary(Path(study_dir).resolve())
    result = _deliver_artifact(
        study_dir, kind, audit=audit, role_id=role_id, industry=industry, deliverable_id=deliverable_id, chain_id=chain_id,
        evidence=evidence, baseline=baseline,
    )
    return _with_chat_summary(study_dir, kind, result, audit, evidence=evidence)


def delivery_error(study_dir: Path, kind: str, error: Exception) -> dict[str, Any]:
    """Return an honest no-artifact projection for CLI/MCP execution failures."""
    result = {
        "status": "error",
        "kind": kind,
        "reason": f"{type(error).__name__}: {error}",
    }
    return _with_chat_summary(
        Path(study_dir), kind, result,
        {"status": "error", "generated_at": "", "checks": [
            {"id": "delivery", "status": "fail", "detail": result["reason"]},
        ]},
    )


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
    role_errors = role_catalog.validate_catalog()
    checks.append((
        "role-catalog",
        not role_errors,
        "80 roles; 10 lifecycles; 11 industries" if not role_errors else "; ".join(role_errors[:5]),
    ))
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
    try:
        notes = field_notes_catalog()["notes"]
        problems = field_note_problems()
        checks.append((
            "platform-field-notes",
            not problems,
            f"{len(notes)} notes" if not problems else "; ".join(problems[:3]),
        ))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("platform-field-notes", False, str(exc)))
    try:
        strategies = strategy_catalog()
        strategy_issues = strategy_problems()
        checks.append((
            "collection-strategies",
            not strategy_issues,
            f"{len(strategies)} strategies" if not strategy_issues else "; ".join(strategy_issues[:3]),
        ))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        checks.append(("collection-strategies", False, str(exc)))
    try:
        policy_issues = runtime_policy_problems()
        cdp_count = sum(1 for item in platform_index().values() if item.get("cdp"))
        checks.append((
            "cdp-runtime-policies",
            not policy_issues,
            f"{cdp_count} CDP platforms" if not policy_issues else "; ".join(policy_issues[:3]),
        ))
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        checks.append(("cdp-runtime-policies", False, str(exc)))
    try:
        collection_issues = collection_policy_problems()
        collection_count = len(collection_policy_catalog())
        checks.append((
            "collection-policies",
            not collection_issues,
            f"{collection_count} platforms" if not collection_issues
            else "; ".join(collection_issues[:3]),
        ))
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        checks.append(("collection-policies", False, str(exc)))
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


# ---------------------------------------------------------------------------
# Platform field notes: operational experience as data
#
# The campaign-tested restrictions and solutions live in one machine-readable
# registry (assets/platform-field-notes.json) so planning, doctor and every
# projection read the same experience instead of a prose document drifting
# beside the catalog. Access permission stays in platform-catalog.json: a field
# note records what happened in the field, never that a route is approved.

FIELD_NOTES_PATH = ASSETS / "platform-field-notes.json"
FIELD_NOTE_REQUIRED = (
    "id", "platform", "channel", "restriction", "symptom", "solution",
    "artifact", "verification", "cdp",
)


def _registry_artifact_path(artifact: Any) -> Path:
    """Resolve a registry artifact path in both checkout and installed runtime.

    Registry entries use repo-relative paths (`skills/askovo/...`) because the
    skill folder is what ships. A wheel installs that folder as
    `askovo/runtime/`, so `REPO_ROOT / artifact` does not exist there; the
    prefix maps onto ``SKILL_ROOT`` instead of failing the doctor.
    """
    raw = Path(str(artifact))
    if raw.is_absolute():
        return raw
    candidate = REPO_ROOT / raw
    if candidate.exists():
        return candidate
    parts = raw.parts
    if len(parts) >= 3 and parts[0] == "skills" and parts[1] == "askovo":
        mapped = SKILL_ROOT.joinpath(*parts[2:])
        if mapped.exists():
            return mapped
    return candidate


def field_notes_catalog() -> dict[str, Any]:
    data = load_json(FIELD_NOTES_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        raise ValueError(f"invalid platform field notes: {FIELD_NOTES_PATH}")
    return data


def field_note_problems() -> list[str]:
    """Structural problems in the field-notes registry (empty means consistent).

    Checks the parts that would silently rot: required fields, unique ids,
    verification status from the legend, artifact paths that exist, helper
    references that resolve, and — for catalog platforms — a ``cdp`` flag that
    matches the platform catalog. A note may describe a source type that is not
    a catalog platform (``source_types``) or cross-platform practice (``*``);
    neither may claim a catalog route.
    """
    problems: list[str] = []
    try:
        data = field_notes_catalog()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]
    catalog_ids = set(platform_index())
    source_types = data.get("source_types") or {}
    legend = set((data.get("verification_legend") or {}).keys())
    if not isinstance(source_types, dict):
        problems.append("source_types must be an object")
        source_types = {}
    allowed = catalog_ids | set(source_types) | {"*"}
    seen: set[str] = set()
    for index, note in enumerate(data["notes"]):
        if not isinstance(note, dict):
            problems.append(f"note[{index}] is not an object")
            continue
        missing = [key for key in FIELD_NOTE_REQUIRED if note.get(key) in (None, "", [])]
        if missing:
            problems.append(f"note[{index}] missing {', '.join(missing)}")
            continue
        note_id = str(note["id"])
        if note_id in seen:
            problems.append(f"duplicate note id: {note_id}")
        seen.add(note_id)
        platform = str(note["platform"])
        if platform not in allowed:
            problems.append(f"{note_id}: platform {platform!r} is neither a catalog platform, a source type, nor '*'")
        verification = note.get("verification")
        if not isinstance(verification, dict):
            problems.append(f"{note_id}: verification must be an object")
        else:
            status = str(verification.get("status") or "")
            if legend and status not in legend:
                problems.append(f"{note_id}: verification status {status!r} not in the legend")
            if not verification.get("date"):
                problems.append(f"{note_id}: verification.date is required")
        artifact = _registry_artifact_path(note["artifact"])
        if not artifact.is_file():
            problems.append(f"{note_id}: artifact not found: {note['artifact']}")
        helper_problem = _resolve_helper_problem(note_id, note.get("helper"))
        if helper_problem:
            problems.append(helper_problem)
        if platform in catalog_ids:
            entry = platform_index()[platform]
            if bool(note.get("cdp")) != bool(entry.get("cdp")):
                problems.append(
                    f"{note_id}: cdp={bool(note.get('cdp'))} disagrees with the platform catalog "
                    f"({platform} cdp={bool(entry.get('cdp'))})"
                )
    return problems


def field_notes_index() -> dict[str, list[dict[str, Any]]]:
    """Notes grouped by platform; ``*`` holds cross-platform practice."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for note in field_notes_catalog()["notes"]:
        if not isinstance(note, dict):
            continue
        grouped.setdefault(str(note.get("platform") or "*"), []).append(note)
    return grouped


def field_notes_for(platforms: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Field notes for the given platforms plus the cross-platform practice.

    ``None`` returns every note. Cross-platform notes lead: they apply to any
    CDP run and are the ones a planner most often needs before a channel.
    """
    grouped = field_notes_index()
    wanted = list(platforms or [])
    if not wanted:
        return [note for notes in grouped.values() for note in notes]
    selected = list(grouped.get("*", []))
    for platform in wanted:
        for note in grouped.get(platform, []):
            if note not in selected:
                selected.append(note)
    return selected


def field_notes_markdown(notes: list[dict[str, Any]] | None = None,
                         platform: str | None = None) -> str:
    """Render field notes as the human-facing restriction/solution table."""
    selected = field_notes_for([platform] if platform else None) if notes is None else notes
    title = "# Askovo 平台实战笔记"
    if platform:
        title += f"：{platform}"
    lines = [
        title,
        "",
        "> 记录的是**实战限制与解法**，不是访问许可：能否采集仍由平台目录、study scope 与"
        "Design gate 决定（见 `askovo platforms` / `docs/connectors.md`）。",
        "",
        "| 平台 | 通道 | 限制 | 解法 | 验证 | 产物 |",
        "|---|---|---|---|---|---|",
    ]
    for note in selected:
        verification = note.get("verification") or {}
        lines.append(
            f"| `{note.get('platform')}` | {note.get('channel')} | "
            f"{note.get('restriction')} | {note.get('solution')} | "
            f"{verification.get('status', '')}（{verification.get('date', '')}） | "
            f"`{note.get('artifact')}` |"
        )
    lines.extend([
        "",
        "## 怎么用",
        "",
        "- 规划前：`askovo platforms \"<需求>\" --field-notes` 看推荐平台的已知坑；",
        "- 采集时：限制命中先按「解法」走；挑战页只被动等待或人工完成，不绕过；",
        "- 收尾时：新的限制/解法补进 `skills/askovo/assets/platform-field-notes.json`"
        "（`askovo doctor` 会校验必填字段、产物路径与 cdp 一致性）。",
        "",
    ])
    return "\n".join(lines)


STRATEGY_REQUIRED = (
    "id", "name", "when", "invariant", "mechanism", "platforms", "artifacts",
    "verification", "enforcement",
)

COLLECTION_POLICY_REQUIRED = ("access_modes", "budget", "signals", "stop_rules", "sources")
COLLECTION_SIGNAL_LEVELS = ("block", "throttle", "watch")
COLLECTION_SOURCE_GRADES = ("official", "craft", "lead")
COLLECTION_OBSERVED_CONFIDENCE = ("high", "medium", "low")
COLLECTION_PRIORITY_PLATFORMS = ("reddit", "amazon", "kickstarter", "instagram", "youtube")


def _resolve_helper_problem(note_id: str, helper: Any) -> str | None:
    """Validate a ``connectors.<module>.<attr>`` reference, or return None."""
    if not helper:
        return None
    module_name, _, attr = str(helper).rpartition(".")
    module_path = SKILL_ROOT / "scripts" / (module_name.replace(".", "/") + ".py")
    if not module_name or not module_path.is_file():
        return f"{note_id}: helper module not found: {helper}"
    if attr:
        source = module_path.read_text(encoding="utf-8")
        if (
            f"def {attr}(" not in source
            and f"class {attr}(" not in source
            and f"class {attr}:" not in source
        ):
            return f"{note_id}: helper {attr!r} not defined in {module_name}"
    return None


def strategy_catalog() -> list[dict[str, Any]]:
    """Cross-platform operating strategies (rotation, lanes, quota, cooldowns)."""
    data = field_notes_catalog()
    strategies = data.get("strategies")
    if strategies is None:
        return []
    if not isinstance(strategies, list):
        raise ValueError(f"invalid strategy layer in {FIELD_NOTES_PATH}")
    return [item for item in strategies if isinstance(item, dict)]


def strategy_problems() -> list[str]:
    """Structural problems in the strategy layer (empty means consistent)."""
    problems: list[str] = []
    try:
        data = field_notes_catalog()
        strategies = strategy_catalog()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]
    allowed = set(platform_index()) | set((data.get("source_types") or {}).keys()) | {"*"}
    legend = set((data.get("verification_legend") or {}).keys())
    seen: set[str] = set()
    for index, strategy in enumerate(strategies):
        missing = [key for key in STRATEGY_REQUIRED if strategy.get(key) in (None, "", [])]
        if missing:
            problems.append(f"strategy[{index}] missing {', '.join(missing)}")
            continue
        strategy_id = str(strategy["id"])
        if strategy_id in seen:
            problems.append(f"duplicate strategy id: {strategy_id}")
        seen.add(strategy_id)
        platforms = strategy.get("platforms")
        if not isinstance(platforms, list) or not platforms:
            problems.append(f"{strategy_id}: platforms must be a non-empty list")
        else:
            unknown = sorted({str(item) for item in platforms} - allowed)
            if unknown:
                problems.append(f"{strategy_id}: unknown platform(s) {', '.join(unknown)}")
        artifacts = strategy.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            problems.append(f"{strategy_id}: artifacts must be a non-empty list")
        else:
            for artifact in artifacts:
                if not _registry_artifact_path(artifact).is_file():
                    problems.append(f"{strategy_id}: artifact not found: {artifact}")
        helper_problem = _resolve_helper_problem(strategy_id, strategy.get("helper"))
        if helper_problem:
            problems.append(helper_problem)
        verification = strategy.get("verification")
        if not isinstance(verification, dict):
            problems.append(f"{strategy_id}: verification must be an object")
        else:
            status = str(verification.get("status") or "")
            if legend and status not in legend:
                problems.append(f"{strategy_id}: verification status {status!r} not in the legend")
            if not verification.get("date"):
                problems.append(f"{strategy_id}: verification.date is required")
    return problems


def strategy_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in strategy_catalog() if item.get("id")}


def runtime_policy_problems() -> list[str]:
    """Policy layer ↔ runtime code consistency (empty means consistent).

    The registry declares which invariants the runtime enforces
    (``enforcement: runtime``), the helper that enforces each one and the
    per-platform budgets. This gate fails when a declared guard does not
    resolve, when a runtime strategy has no guard, when an operator strategy
    falsely claims one, or when a CDP platform cannot build a policy.
    """
    problems: list[str] = []
    try:
        data = field_notes_catalog()
        strategy = _cdp_strategy()
        strategies = strategy_index()
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return [str(exc)]
    section = data.get("runtime_policies")
    if not isinstance(section, dict):
        return ["runtime_policies section is required (see cdp_strategy.policy_problems)"]
    known = sorted(set(platform_index()) | set((data.get("source_types") or {}).keys()))
    problems.extend(strategy.policy_problems(section, known_platforms=known))
    guards = section.get("guards") if isinstance(section.get("guards"), dict) else {}
    for strategy_id, helper in guards.items():
        record = strategies.get(str(strategy_id))
        if record is None:
            problems.append(f"runtime guard {strategy_id!r} is not a declared strategy")
        elif record.get("enforcement") != "runtime":
            problems.append(
                f"{strategy_id}: guarded but enforcement is {record.get('enforcement')!r}"
            )
        helper_problem = _resolve_helper_problem(f"runtime guard {strategy_id}", helper)
        if helper_problem:
            problems.append(helper_problem)
    for strategy_id, record in strategies.items():
        enforcement = record.get("enforcement")
        if enforcement not in ("runtime", "operator"):
            problems.append(f"{strategy_id}: enforcement must be 'runtime' or 'operator'")
        elif enforcement == "runtime" and strategy_id not in guards:
            problems.append(f"{strategy_id}: runtime strategy has no guard in runtime_policies.guards")
        elif enforcement == "operator" and strategy_id in guards:
            problems.append(f"{strategy_id}: operator strategy must not claim a runtime guard")
    for platform, entry in platform_index().items():
        if not entry.get("cdp"):
            continue
        try:
            policy = strategy.policy_for(platform)
        except (ValueError, RuntimeError) as exc:
            problems.append(f"{platform}: cannot build a runtime policy ({exc})")
            continue
        if policy.platform != platform:
            problems.append(f"{platform}: policy platform mismatch ({policy.platform})")
    for name in ("collect_cdp_discord.py", "collect_cdp_kickstarter.py"):
        path = HERE / "connectors" / name
        if not path.is_file():
            problems.append(f"CDP collector missing: {name}")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"{name}: cannot read ({exc})")
            continue
        if "cdp_strategy" not in source or "SessionGuard" not in source:
            problems.append(f"{name}: CDP runtime policy is not applied (no cdp_strategy.SessionGuard)")
    return problems


# ---------------------------------------------------------------------------
# Collection policy: what one data-collection run may spend per platform
#
# The operating strategies say how to rotate; collection policies say what a
# run may cost: allowed access modes, cadence, session and volume budget, the
# signals that force a stop, and the dated sources behind every claim. They sit
# in the same registry as the field notes so planning, doctor and every
# projection read one copy. A policy is a budget, never a permission: the
# access decision stays in platform-catalog.json.


def _policy_day(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def collection_policy_section() -> dict[str, Any]:
    """The collection-policy layer, or ``{}`` when the registry has none."""
    data = field_notes_catalog()
    section = data.get("collection_policies")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"invalid collection_policies section in {FIELD_NOTES_PATH}")
    return section


def collection_policy_catalog() -> dict[str, dict[str, Any]]:
    """Platform id -> collection policy entry."""
    platforms = collection_policy_section().get("platforms")
    if platforms is None:
        return {}
    if not isinstance(platforms, dict):
        raise ValueError(f"invalid collection_policies.platforms in {FIELD_NOTES_PATH}")
    catalog: dict[str, dict[str, Any]] = {}
    for key, value in platforms.items():
        if not isinstance(value, dict):
            raise ValueError(f"collection_policies.platforms[{key!r}] must be an object")
        catalog[str(key)] = value
    return catalog


def collection_policy_for(platform: str, section: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One platform's policy with the layer's dates attached (``None`` if absent)."""
    section = collection_policy_section() if section is None else section
    platforms = section.get("platforms") if isinstance(section, dict) else None
    if not isinstance(platforms, dict):
        return None
    entry = platforms.get(str(platform))
    if not isinstance(entry, dict):
        return None
    enriched = dict(entry)
    enriched["platform"] = str(platform)
    enriched["generated_at"] = section.get("generated_at")
    enriched["review_by"] = section.get("review_by")
    return enriched


def collection_policy_problems() -> list[str]:
    """Collection-policy consistency (empty means consistent).

    The layer must not invent access: platform ids resolve to the catalog or a
    declared source type, access modes stay inside the catalog's list, every
    blocked platform is excluded with a reason, and no budget may be looser
    than the runtime policy the connectors actually enforce.
    """
    problems: list[str] = []
    try:
        section = collection_policy_section()
        data = field_notes_catalog()
        catalog = platform_index()
        runtime = _cdp_strategy()
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return [str(exc)]
    if not section:
        return [f"collection_policies section is missing from {FIELD_NOTES_PATH.name}"]
    if str(section.get("schema_version")) != "1.0":
        problems.append("collection_policies.schema_version must be '1.0'")
    generated = _policy_day(section.get("generated_at"))
    review = _policy_day(section.get("review_by"))
    if generated is None:
        problems.append("collection_policies.generated_at must be YYYY-MM-DD")
    if review is None:
        problems.append("collection_policies.review_by must be YYYY-MM-DD")
    elif generated is not None and review <= generated:
        problems.append("collection_policies.review_by must be later than generated_at")
    levels = section.get("levels")
    if not isinstance(levels, dict):
        problems.append("collection_policies.levels must be an object")
    else:
        unlabelled = [
            level for level in COLLECTION_SIGNAL_LEVELS
            if not str(levels.get(level) or "").strip()
        ]
        if unlabelled:
            problems.append(f"collection_policies.levels missing {', '.join(unlabelled)}")

    blocked = {pid for pid, item in catalog.items() if item.get("decision") == "blocked"}
    excluded = section.get("excluded")
    excluded_ids: set[str] = set()
    if not isinstance(excluded, list):
        problems.append("collection_policies.excluded must be a list")
    else:
        for index, item in enumerate(excluded):
            if not isinstance(item, dict):
                problems.append(f"collection_policies.excluded[{index}] must be an object")
                continue
            pid = str(item.get("platform") or "")
            if not pid:
                problems.append(f"collection_policies.excluded[{index}] missing platform")
                continue
            excluded_ids.add(pid)
            if not str(item.get("reason") or "").strip():
                problems.append(f"collection_policies.excluded[{index}] ({pid}) missing reason")
            if pid not in blocked:
                problems.append(
                    f"collection_policies.excluded {pid} is not blocked in the platform catalog"
                )
    uncovered = sorted(blocked - excluded_ids)
    if uncovered:
        problems.append(
            "blocked platforms have no exclusion note: " + ", ".join(uncovered)
        )

    platforms = section.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        problems.append("collection_policies.platforms must be a non-empty object")
        return problems
    declared = set((data.get("source_types") or {}).keys())
    known = set(catalog) | declared
    for platform, entry in platforms.items():
        pid = str(platform)
        label = f"collection_policies.platforms[{pid!r}]"
        if pid not in known:
            problems.append(f"{label} is not a catalog platform or source type")
        if not isinstance(entry, dict):
            problems.append(f"{label} must be an object")
            continue
        missing = [key for key in COLLECTION_POLICY_REQUIRED if entry.get(key) in (None, "", [], {})]
        if missing:
            problems.append(f"{label} missing {', '.join(missing)}")
            continue
        catalog_entry = catalog.get(pid) or {}
        allowed_modes = {str(mode) for mode in catalog_entry.get("access_modes", [])}
        modes = entry.get("access_modes")
        if not isinstance(modes, list) or not modes:
            problems.append(f"{label}: access_modes must be a non-empty list")
        else:
            unknown = sorted({str(mode) for mode in modes} - allowed_modes)
            if unknown:
                problems.append(
                    f"{label}: access_modes outside the platform catalog: {', '.join(unknown)}"
                )
        budget = entry.get("budget")
        numbers: dict[str, float] = {}
        if not isinstance(budget, dict):
            problems.append(f"{label}: budget must be an object")
        else:
            for key in ("cadence_seconds", "session_minutes", "budget_fraction"):
                value = budget.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.append(f"{label}: budget.{key} must be a number")
                    continue
                numbers[key] = float(value)
            if "cadence_seconds" in numbers and numbers["cadence_seconds"] < 1:
                problems.append(f"{label}: budget.cadence_seconds must be >= 1")
            if "session_minutes" in numbers and numbers["session_minutes"] < 1:
                problems.append(f"{label}: budget.session_minutes must be >= 1")
            if "budget_fraction" in numbers and not 0 < numbers["budget_fraction"] <= 1:
                problems.append(f"{label}: budget.budget_fraction must be in (0, 1]")
            if len(numbers) == 3:
                try:
                    enforced = runtime.policy_for(pid)
                except (ValueError, RuntimeError) as exc:
                    problems.append(f"{label}: cannot read the runtime policy ({exc})")
                else:
                    if numbers["cadence_seconds"] < enforced.cadence_seconds - 1e-9:
                        problems.append(
                            f"{label}: cadence_seconds {numbers['cadence_seconds']:g} is looser "
                            f"than the runtime policy ({enforced.cadence_seconds:g})"
                        )
                    if numbers["session_minutes"] > enforced.session_minutes + 1e-9:
                        problems.append(
                            f"{label}: session_minutes {numbers['session_minutes']:g} is looser "
                            f"than the runtime policy ({enforced.session_minutes:g})"
                        )
                    if numbers["budget_fraction"] > enforced.budget_fraction + 1e-9:
                        problems.append(
                            f"{label}: budget_fraction {numbers['budget_fraction']:g} is looser "
                            f"than the runtime policy ({enforced.budget_fraction:g})"
                        )
        signals = entry.get("signals")
        if not isinstance(signals, list) or not signals:
            problems.append(f"{label}: signals must be a non-empty list")
        else:
            seen: set[str] = set()
            for index, signal in enumerate(signals):
                if not isinstance(signal, dict):
                    problems.append(f"{label}: signals[{index}] must be an object")
                    continue
                sid = str(signal.get("id") or "")
                if not sid:
                    problems.append(f"{label}: signals[{index}] missing id")
                    continue
                if sid in seen:
                    problems.append(f"{label}: duplicate signal id {sid}")
                seen.add(sid)
                if str(signal.get("level")) not in COLLECTION_SIGNAL_LEVELS:
                    problems.append(
                        f"{label}: signal {sid} level must be one of "
                        f"{'/'.join(COLLECTION_SIGNAL_LEVELS)}"
                    )
                for key in ("detect", "action"):
                    if not str(signal.get(key) or "").strip():
                        problems.append(f"{label}: signal {sid} missing {key}")
            if not any(str(item.get("level")) == "block" for item in signals if isinstance(item, dict)):
                problems.append(f"{label}: needs at least one block-level signal")
        stop_rules = entry.get("stop_rules")
        if not isinstance(stop_rules, list) or not stop_rules:
            problems.append(f"{label}: stop_rules must be a non-empty list")
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"{label}: sources must be a non-empty list")
        else:
            grades: set[str] = set()
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    problems.append(f"{label}: sources[{index}] must be an object")
                    continue
                grade = str(source.get("grade") or "")
                if grade not in COLLECTION_SOURCE_GRADES:
                    problems.append(
                        f"{label}: sources[{index}] grade must be one of "
                        f"{'/'.join(COLLECTION_SOURCE_GRADES)}"
                    )
                else:
                    grades.add(grade)
                if _policy_day(source.get("as_of")) is None:
                    problems.append(f"{label}: sources[{index}] as_of must be YYYY-MM-DD")
                for key in ("url", "claim"):
                    if not str(source.get(key) or "").strip():
                        problems.append(f"{label}: sources[{index}] missing {key}")
            if sources and not grades & {"official", "craft"}:
                problems.append(f"{label}: sources need at least one official or craft source")
        observed = entry.get("observed")
        if observed is None:
            problems.append(f"{label}: observed must be present (may be empty)")
        elif not isinstance(observed, list):
            problems.append(f"{label}: observed must be a list")
        else:
            seen_observed: set[str] = set()
            floor = numbers.get("cadence_seconds")
            for index, item in enumerate(observed):
                if not isinstance(item, dict):
                    problems.append(f"{label}: observed[{index}] must be an object")
                    continue
                oid = str(item.get("id") or "")
                tag = f"observed {oid}" if oid else f"observed[{index}]"
                if not oid:
                    problems.append(f"{label}: observed[{index}] missing id")
                elif oid in seen_observed:
                    problems.append(f"{label}: duplicate observed id {oid}")
                else:
                    seen_observed.add(oid)
                for key in ("claim", "threshold"):
                    if not str(item.get(key) or "").strip():
                        problems.append(f"{label}: {tag} missing {key}")
                confidence = str(item.get("confidence") or "")
                if confidence not in COLLECTION_OBSERVED_CONFIDENCE:
                    problems.append(
                        f"{label}: {tag} confidence must be one of "
                        f"{'/'.join(COLLECTION_OBSERVED_CONFIDENCE)}"
                    )
                if _policy_day(item.get("as_of")) is None:
                    problems.append(f"{label}: {tag} as_of must be YYYY-MM-DD")
                window = item.get("window_seconds")
                if window is not None and (
                    not isinstance(window, int) or isinstance(window, bool) or window < 0
                ):
                    problems.append(
                        f"{label}: {tag} window_seconds must be a non-negative integer or null"
                    )
                suggested = item.get("suggested_cadence_seconds")
                if suggested is not None:
                    if not isinstance(suggested, (int, float)) or isinstance(suggested, bool):
                        problems.append(
                            f"{label}: {tag} suggested_cadence_seconds must be a number or null"
                        )
                    elif floor is not None and suggested < floor - 1e-9:
                        problems.append(
                            f"{label}: {tag} suggests {float(suggested):g}s, faster than the budget "
                            f"({floor:g}s) — experience values may only slow a run down"
                        )
                urls = item.get("source_urls")
                if not isinstance(urls, list) or not urls:
                    problems.append(f"{label}: {tag} source_urls must be a non-empty list")
                else:
                    for url_index, url in enumerate(urls):
                        if not str(url or "").startswith(("http://", "https://")):
                            problems.append(
                                f"{label}: {tag} source_urls[{url_index}] must be an http(s) URL"
                            )
        if "unverified" not in entry:
            problems.append(f"{label}: unverified must be present (may be empty)")
        elif not isinstance(entry.get("unverified"), list):
            problems.append(f"{label}: unverified must be a list")
    absent = [pid for pid in COLLECTION_PRIORITY_PLATFORMS if pid not in platforms]
    if absent:
        problems.append(
            "priority platforms have no collection policy: " + ", ".join(absent)
        )
    return problems


def collection_policies_markdown(platforms: list[str] | None = None) -> str:
    """Render the collection policy cards for the selected platforms."""
    section = collection_policy_section()
    catalog = collection_policy_catalog()
    if platforms is None:
        selected = list(catalog)
    else:
        selected = [str(item) for item in platforms if str(item).strip()]
    selected = [item for item in dict.fromkeys(selected) if item in catalog]
    review_by = section.get("review_by") or "未标注"
    if not selected:
        return (
            "# Askovo 采集策略卡\n\n"
            "> 本次选择里没有可采集策略（目录里 blocked 的平台没有策略卡）。\n"
        )
    lines = [
        "# Askovo 采集策略卡",
        "",
        f"> 策略是**预算**，不是访问许可：能否采集由 `platform-catalog.json` 的 access decision、"
        f"study scope 与已获批 URL 决定。下次复核：**{review_by}**。"
        "挑战页只被动等待或人工完成；不绕过、不伪造指纹、不用代理池、不养马甲、不做 AI 人性化。",
        "",
        "| 平台 | 访问方式 | 站点间隔 | 会话上限 | 预算 | block 信号 | 停止规则 |",
        "|---|---|---|---|---|---|---|",
    ]
    for platform in selected:
        policy = catalog[platform]
        budget = policy.get("budget") or {}
        modes = "、".join(str(mode) for mode in policy.get("access_modes", []))
        blocks = [
            str(signal.get("id"))
            for signal in policy.get("signals", [])
            if str(signal.get("level")) == "block"
        ]
        lines.append(
            f"| `{platform}` | {modes} | {budget.get('cadence_seconds', '')}s | "
            f"{budget.get('session_minutes', '')} min | "
            f"{float(budget.get('budget_fraction') or 0):.0%} | "
            f"{'、'.join(blocks)} | {len(policy.get('stop_rules') or [])} 条 |"
        )
    for platform in selected:
        policy = catalog[platform]
        budget = policy.get("budget") or {}
        lines.extend([
            "",
            f"## {platform}",
            "",
            f"- 访问方式：{'、'.join(str(mode) for mode in policy.get('access_modes', []))}",
            f"- 预算：站点间隔 {budget.get('cadence_seconds', '')}s；"
            f"会话上限 {budget.get('session_minutes', '')} min；"
            f"量级取计划量的 {float(budget.get('budget_fraction') or 0):.0%}",
        ])
        if policy.get("note"):
            lines.append(f"- 备注：{policy['note']}")
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in policy.get("observed") or []:
            confidence = str(item.get("confidence") or "")
            if confidence in counts:
                counts[confidence] += 1
        total = sum(counts.values())
        if total:
            lines.append(
                f"- 社区经验：{total} 条"
                f"（high {counts['high']} / medium {counts['medium']} / low {counts['low']}）"
                "；经验值只用来放慢节奏和提前熔断，low 不进自动门禁"
            )
        lines.extend(["", "| 信号 | 级别 | 检测 | 动作 |", "|---|---|---|---|"])
        for signal in policy.get("signals", []):
            lines.append(
                f"| `{signal.get('id')}` | {signal.get('level')} | "
                f"{signal.get('detect')} | {signal.get('action')} |"
            )
        lines.extend(["", "**停止规则**", ""])
        for rule in policy.get("stop_rules", []):
            lines.append(f"- {rule}")
        lines.extend(["", "**来源**", ""])
        for source in policy.get("sources", []):
            lines.append(
                f"- [{source.get('grade')} {source.get('as_of')}] {source.get('url')} — "
                f"{source.get('claim')}"
            )
        unverified = policy.get("unverified") or []
        if unverified:
            lines.extend(["", "**未核**", ""])
            for item in unverified:
                lines.append(f"- {item}")
    lines.extend([
        "",
        "## 不做",
        "",
        "- 验证码/挑战页绕过（含打码与人工打码服务）；",
        "- 浏览器指纹伪造（含 stealth 补丁与 UA 伪装）；",
        "- 代理池/住宅代理轮换；",
        "- 多账号马甲矩阵；",
        "- 「AI 人性化」行为模拟（随机延迟、鼠标轨迹、拟人打字）。",
        "",
        "口径与判据见 `skills/askovo/references/collection-strategy.md`；"
        "机器可读在 `skills/askovo/assets/platform-field-notes.json` 的 `collection_policies`，"
        "`askovo doctor` 校验。",
        "",
    ])
    return "\n".join(lines)


def strategies_for(platforms: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Strategies that apply to the given platforms (``*`` always applies)."""
    wanted = {str(item) for item in (platforms or [])}
    selected: list[dict[str, Any]] = []
    for strategy in strategy_catalog():
        strategy_platforms = {str(item) for item in strategy.get("platforms", [])}
        if not wanted or "*" in strategy_platforms or strategy_platforms & wanted:
            selected.append(strategy)
    return selected


def strategies_markdown(strategies: list[dict[str, Any]] | None = None,
                        platforms: list[str] | None = None) -> str:
    """Render the cross-platform operating strategies as a method table."""
    selected = strategies_for(platforms) if strategies is None else strategies
    lines = [
        "# Askovo 多平台采集策略",
        "",
        "> 策略是**经验**，不是许可：轮转降低的是每个站点感知到的频率，不绕过平台限制；"
        "挑战页只被动等待或人工完成，登录会话仅由用户手工完成，身份/代理不轮换。",
        "",
        "| 策略 | 何时用 | 不变量（不能破的约束） | 机制 | 验证 |",
        "|---|---|---|---|---|",
    ]
    for strategy in selected:
        verification = strategy.get("verification") or {}
        lines.append(
            f"| **{strategy.get('name')}** (`{strategy.get('id')}`) | {strategy.get('when')} | "
            f"{strategy.get('invariant')} | {strategy.get('mechanism')} | "
            f"{verification.get('status', '')}（{verification.get('date', '')}） |"
        )
    lines.extend([
        "",
        "## 怎么用",
        "",
        "- 规划时：`askovo platforms \"<需求>\" --strategies` 按推荐平台取策略；",
        "- 调度时：`connectors/rotation.py` 的 `RotationScheduler` 强制每站点最小间隔、"
        "429/422 冷却、日配额与会话冷却（掉线等人工重登）；",
        "- 收尾时：策略与不变量补进 `skills/askovo/assets/platform-field-notes.json` 的 "
        "`strategies` 段并声明 `enforcement`（`askovo doctor` 校验必填字段、产物、helper 与 "
        "runtime guard 引用）。",
        "",
    ])
    return "\n".join(lines)


def runtime_policies_markdown(platforms: list[str] | None = None) -> str:
    """Render the enforced per-platform CDP runtime budgets."""
    strategy = _cdp_strategy()
    catalog = platform_index()
    registry = field_notes_catalog()
    declared = set((registry.get("source_types") or {}).keys())
    if platforms:
        selected = [str(item) for item in platforms if str(item).strip()]
    else:
        selected = [str(item) for item, entry in catalog.items() if entry.get("cdp")]
        selected += [item for item in declared if item in (registry.get("runtime_policies") or {}).get("platforms", {})]
    if not selected:
        return (
            "# Askovo CDP 运行时策略\n\n"
            "> 本次选择里没有 CDP 平台；运行时策略只约束 CDP 可见页通道"
            "（`cdp: true` 的平台或已声明的 source type）。\n"
        )
    lines = [
        "# Askovo CDP 运行时策略",
        "",
        "> 这些是**运行时预算**，不是访问许可：平台目录、study scope、Design gate、"
        "人工 ack 与获批 URL 才决定能否采集；策略只约束「怎么碰」，不绕过任何限制。",
        "",
        "| 平台 | 站点最小间隔 | 会话上限 | 超时熔断 | 单 cell goto | 预算系数 | 需登录 | 模式互斥 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for platform in dict.fromkeys(selected):
        policy = strategy.policy_for(platform)
        lines.append(
            f"| `{platform}` | {policy.cadence_seconds:g}s | {policy.session_minutes:g} min | "
            f"{policy.timeout_cooldown_minutes:g} min | {policy.max_gotos_per_cell} | "
            f"{policy.budget_fraction:.0%} | {'是' if policy.requires_session else '否'} | "
            f"{'、'.join(policy.exclusive_modes)} |"
        )
    lines.extend([
        "",
        "## 执行口径",
        "",
        "- **超时=熔断**：任何 timeout/abort 后停止接触该平台至少「超时熔断」时长；"
        "不诊断、不截图、不重试——撕裂的输入流本身就是自动化签名；",
        "- **一个 cell 一次 goto**：导航→校验→采集在同一 cell 内完成；`reload()` 默认禁止；",
        "- **会话限时**：登录态采集到「会话上限」即停，人工登出后再开新一段；掉线只由人工重登；",
        "- **预算留头**：cell 预算按「预算系数」打折（Discord 60%，其余 70%），宁可少采；",
        "- **模式互斥**：同一段会话里不混用「模式互斥」列出的模式（如邀请加入与频道抓取）；",
        "- **空渲染=不支持的栈**：200 + 空标题 + 空正文不是挑战页、也不是空语料，换同垂类信源；",
        "- **挑战页只被动等待或人工完成**，不求解、不伪造、不换身份。",
        "",
        "机器可读：`askovo platforms \"<需求>\" --json` 的每个 CDP 平台带 `runtime_policy`；"
        "实现见 `connectors/cdp_strategy.py`（`SessionGuard`），"
        "`python3 connectors/cdp_strategy.py --selftest` 离线自检。",
        "",
    ])
    return "\n".join(lines)


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
    notes_by_platform = field_notes_index()
    try:
        collection_section = collection_policy_section()
        collection_ids = set(collection_policy_catalog())
    except (OSError, json.JSONDecodeError, ValueError):
        collection_section = {}
        collection_ids = set()
    collection_policies = {
        pid: collection_policy_for(pid, collection_section) for pid in collection_ids
    }
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
            "field_notes": [
                {
                    "id": note.get("id"),
                    "channel": note.get("channel"),
                    "restriction": note.get("restriction"),
                    "solution": note.get("solution"),
                    "verification": (note.get("verification") or {}).get("status"),
                    "helper": note.get("helper"),
                }
                for note in notes_by_platform.get(platform_id, []) + notes_by_platform.get("*", [])
            ],
        }
        if decision == "blocked":
            blocked.append(entry)
        else:
            if entry["cdp"]:
                # The plan carries the enforced runtime budget, not just prose:
                # one goto per cell, timeout cooldown, session time-box, headroom.
                entry["runtime_policy"] = _cdp_strategy().policy_for(platform_id).to_dict()
            if collection_policies.get(platform_id):
                # What one collection run may spend on this platform: access
                # modes, cadence, session cap, stop signals and dated sources.
                entry["collection_policy"] = collection_policies[platform_id]
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
        "strategies": strategies_for([item["id"] for item in ranked[:8]]),
        "runtime_policies": {
            item["id"]: item["runtime_policy"]
            for item in ranked[:8]
            if item.get("runtime_policy")
        },
        "collection_policies": {
            item["id"]: item["collection_policy"]
            for item in ranked[:8]
            if item.get("collection_policy")
        },
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
    field_notes: list[dict[str, Any]] = []
    seen_notes: set[str] = set()
    for item in plan["recommended"]:
        for note in item.get("field_notes", []):
            note_id = str(note.get("id"))
            if note_id in seen_notes:
                continue
            seen_notes.add(note_id)
            field_notes.append(note)
    if field_notes:
        lines.extend(["", "## 已知平台限制与解法（实战）", ""])
        for note in field_notes:
            lines.append(
                f"- `{note.get('id')}`（{note.get('verification') or '未标注'}）："
                f"{note.get('restriction')} → {note.get('solution')}"
            )
        lines.append("")
        lines.append("> 记录的是实战限制与解法，不是访问许可；完整字段见 "
                     "`askovo platforms \"<需求>\" --field-notes`。")
    strategies = plan.get("strategies") or []
    if strategies:
        lines.extend(["", "## 多平台轮转策略（不变量优先）", ""])
        for strategy in strategies[:8]:
            lines.append(
                f"- **{strategy.get('name')}**（`{strategy.get('id')}`）："
                f"{strategy.get('mechanism')} 不变量：{strategy.get('invariant')}"
            )
        lines.append("")
        lines.append("> 完整策略表：`askovo platforms \"<需求>\" --strategies`。")
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
    text = _raw_text(raw)
    title = str(raw.get("title") or "")
    created_at = _raw_created_at(raw)
    source_url = _raw_source_url(raw)
    record_id = str(raw.get("record_id") or raw.get("id") or raw.get("source_record_id") or "")
    if not record_id:
        # title-only 可以没有正文，但不能把 title 写进 text；用 URL/标题/run_id 稳定去重。
        record_id = source_url or hashlib.sha256((text or title or run_id).encode()).hexdigest()[:16]
    if not record_id.startswith(platform + ":"):
        record_id = f"{platform}:{record_id}"
    record = {
        "record_id": record_id,
        "platform": platform,
        "source_platform": platform,
        "source_url": source_url,
        "source_channel": str(raw.get("source_channel") or raw.get("subreddit") or ""),
        "source_content_type": str(raw.get("source_content_type") or raw.get("content_type") or "unknown"),
        "parent_id": raw.get("parent_id"),
        "thread_id": raw.get("thread_id"),
        "author_hash": str(raw.get("author_hash") or _hash_author(_raw_author(raw))),
        "created_at": created_at,
        "date_precision": str(raw.get("date_precision") or "unknown"),
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
    if platform == "youtube":
        source_url = record["source_url"]
        video_id = str(raw.get("youtube_video_id") or
                       urllib.parse.parse_qs(urllib.parse.urlparse(source_url).query).get("v", [""])[0])
        item_id = str(raw.get("youtube_item_id") or raw.get("id") or record.get("record_id") or "")
        source_type = record["source_content_type"]
        content_type = str(raw.get("youtube_content_type") or (
            ("reply" if raw.get("parent_id") else "top_level_comment")
            if source_type == "comment" else source_type))
        record.update({
            "youtube_video_id": video_id,
            "youtube_item_id": item_id,
            "youtube_content_type": content_type,
            "comment_thread_id": str(raw.get("comment_thread_id") or raw.get("thread_id") or
                                      (item_id if content_type in {"top_level_comment", "reply"} else "")),
            "source_query": str(raw.get("source_query") or query),
            "source_order": raw.get("source_order"),
            "last_verified_at": str(raw.get("last_verified_at") or record["collected_at"]),
            "refresh_due_at": str(raw.get("refresh_due_at") or ""),
            "content_status": str(raw.get("content_status") or "present"),
        })
    return record


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
        "completed_at": manifest.get("completed_at") or now(),
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


def _collect_youtube(query: str, limit: int) -> list[dict[str, Any]]:
    from connectors import collect_youtube_innertube as collector

    records: list[dict[str, Any]] = []
    for video_id in collector.search_videos(query, min(4, limit)):
        payload = collector.post("next", dict(collector.CTX, videoId=video_id))
        meta = collector.video_meta(payload)
        token = collector.comment_token(payload)
        pages = 0
        while token and len(records) < limit and pages < 40:
            page = collector.post("next", dict(collector.CTX, continuation=token))
            pages += 1
            for comment in collector.parse_comments(page):
                if len(records) >= limit:
                    break
                if not comment.get("text") or not comment.get("id"):
                    continue
                records.append({
                    "id": f"youtube:{comment['id']}",
                    "title": meta.get("title", ""),
                    "text": comment["text"],
                    "url": f"https://youtu.be/{video_id}",
                    "author": comment.get("author") or "",
                    "created_at": collector.approx_time(comment.get("time_text"), time.time()) or "",
                    "context": meta.get("channel", ""),
                    "source_channel": meta.get("channel", ""),
                    "source_content_type": "comment",
                    "thread_id": video_id,
                    "youtube_video_id": video_id,
                    "youtube_item_id": comment["id"],
                    "date_precision": "approximate",
                    "claim_type": "need",
                    "evidence_form": "self_report",
                })
            token = collector.next_page_token(page)
            time.sleep(1.2)
    return records


def _collect_hn(query: str, limit: int) -> list[dict[str, Any]]:
    from connectors import collect_hn as collector

    rows = collector.collect({"queries": [query]}, limit, 100, 0.25, 12)
    return [{
        "id": row["record_id"],
        "title": row.get("thread_title", ""),
        "text": row["text"],
        "url": row["source_url"],
        "author": "",
        "created_at": row.get("created_at", ""),
        "context": row.get("source_channel", ""),
        "source_channel": row.get("source_channel", ""),
        "source_content_type": "comment",
        "parent_id": row.get("parent_id"),
        "claim_type": "need",
        "evidence_form": "self_report",
    } for row in rows]


# ---------------------------------------------------------------------------
# CDP transport: authorized visible pages only. No challenge bypass.


CDP_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
CDP_TARGET_HOSTS = {
    "github": ("github.com",),
    "reddit": ("reddit.com",),
    "youtube": ("youtube.com", "youtu.be"),
    "hackernews": ("news.ycombinator.com",),
    "amazon": ("amazon.com", "amazon.ca", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.co.jp"),
    "instagram": ("instagram.com",),
    "bilibili": ("bilibili.com",),
    "weibo": ("weibo.com", "weibo.cn"),
    "kickstarter": ("kickstarter.com",),
    "discord": ("discord.com",),
    "x": ("x.com", "twitter.com"),
    "tiktok": ("tiktok.com",),
}
MAX_CDP_HANDSHAKE_BYTES = 64 * 1024
MAX_CDP_MESSAGE_BYTES = 16 * 1024 * 1024
CAPTURE_CHALLENGE_WAIT_SECONDS = 5.0
CDP_CALL_TIMEOUT_SECONDS = 30.0


class CDPTimeout(TimeoutError):
    """A CDP call exceeded its budget; the websocket stream is now torn.

    A torn stream is a stop signal, not a retry signal: the next call would
    resume reading in the middle of the previous frame, and on a session
    platform the timeout itself is the anti-automation signature (field:
    Discord drops the login after timeout-then-continue). Reconnect with a
    fresh page instead.
    """

    def __init__(self, method: str, timeout_seconds: float) -> None:
        self.method = method
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"CDP {method} timed out after {self.timeout_seconds:.0f}s; "
            "the stream is torn — stop touching the platform and reconnect with a fresh page"
        )


class CDPTransportError(RuntimeError):
    """The CDP connection is unusable (torn by an earlier timeout or closed)."""


def _capture_title_reports_not_found(title: str) -> bool:
    return bool(_cdp_strategy().title_reports_not_found(title))


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
    def __init__(self, ws: _WebSocket, *, timeout: float = CDP_CALL_TIMEOUT_SECONDS):
        self.ws = ws
        self.timeout = float(timeout)
        self.next_id = 0
        self._broken = ""

    @property
    def broken(self) -> str:
        """Why this client can no longer be used (empty means healthy)."""
        return self._broken

    def _arm_timeout(self, seconds: float) -> None:
        sock = getattr(self.ws, "sock", None)
        if sock is not None:
            try:
                sock.settimeout(seconds)
            except OSError:  # pragma: no cover - socket already closed
                pass

    def call(self, method: str, params: dict[str, Any] | None = None,
             *, timeout: float | None = None) -> dict[str, Any]:
        if self._broken:
            raise CDPTransportError(
                f"CDP connection is unusable ({self._broken}); open a fresh page "
                "instead of retrying on a torn stream"
            )
        budget = self.timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, budget)
        self.next_id += 1
        message_id = self.next_id
        try:
            self._arm_timeout(budget)
            self.ws.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"{method} exceeded its {budget:g}s wall-clock budget")
                self._arm_timeout(max(0.05, remaining))
                raw = self.ws.recv_text()
                # Events carry no top-level "id"; skip them before parsing.
                if '"id"' not in raw:
                    continue
                message = json.loads(raw)
                if message.get("id") != message_id:
                    continue
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result") or {}
        except (socket.timeout, TimeoutError) as exc:
            # The frame boundary is unknown after a timeout: never read on.
            self._broken = f"{method} timed out after {budget:.0f}s"
            raise CDPTimeout(method, budget) from exc
        except ConnectionError:
            self._broken = "connection closed"
            raise

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
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


def cdp_existing_page(cdp_base: str, url: str) -> str:
    """Attach to an already visible authorized page without navigating it."""
    _, expected_port = _validate_cdp_base(cdp_base)
    target = cdp_base.rstrip("/") + "/json/list"
    with _CDP_OPENER.open(target, timeout=15) as response:
        payload = _read_limited_json(response)
    if not isinstance(payload, list):
        raise RuntimeError("CDP /json/list did not return an array")
    wanted = url.rstrip("/")
    for item in payload:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        if str(item.get("url") or "").rstrip("/") != wanted:
            continue
        ws_url = str(item.get("webSocketDebuggerUrl") or "")
        _validate_cdp_ws_url(ws_url, expected_port)
        return ws_url
    raise RuntimeError(
        "no already-open visible page exactly matches the capture URL; "
        "open it in the user browser or omit --attach-existing"
    )


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
  return {rows: rows, page_title: document.title, page_url: location.href, page_text: bodyText};
})()
"""


CDP_INSTAGRAM_EXTRACTOR = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const bodyText = clean(document.body ? document.body.innerText : "");
  if (/Robot Check|Enter the characters|验证码|异常流量|not a robot|captcha/i.test(bodyText)) {
    return {error: "challenge_page"};
  }
  const rows = [];
  const seen = new Set();
  const add = (row) => {
    if (!row.text || seen.has(row.id + "|" + row.text)) return;
    seen.add(row.id + "|" + row.text);
    rows.push(row);
  };
  for (const article of document.querySelectorAll("article")) {
    const caption = article.querySelector("h1");
    const authorNode = article.querySelector('a[role="link"]');
    const time = article.querySelector("time[datetime]");
    const permalink = time && time.closest('a[href*="/p/"], a[href*="/reel/"]');
    add({
      id: ((permalink && permalink.getAttribute("href")) || location.href) + "#caption",
      title: "Instagram caption",
      text: clean(caption ? caption.innerText : ""),
      author: clean(authorNode ? authorNode.innerText : ""),
      created_at: time ? time.getAttribute("datetime") || "" : "",
      source_url: permalink ? new URL(permalink.getAttribute("href"), location.href).href : location.href,
      source_channel: clean(authorNode ? authorNode.innerText : ""),
      source_content_type: "post",
      page_url: location.href
    });
  }
  for (const time of document.querySelectorAll("time[datetime]")) {
    let row = time;
    for (let depth = 0; depth < 5 && row.parentElement; depth += 1) row = row.parentElement;
    const text = clean(row.innerText);
    const authorNode = row.querySelector('a[role="link"]');
    const permalink = time.closest('a[href*="/p/"], a[href*="/reel/"], a[href*="/comment/"]');
    const href = permalink ? permalink.getAttribute("href") : location.href;
    add({
      id: String(href) + "#" + (time.getAttribute("datetime") || rows.length),
      title: "Instagram comment",
      text: text,
      author: clean(authorNode ? authorNode.innerText : ""),
      created_at: time.getAttribute("datetime") || "",
      source_url: new URL(href, location.href).href,
      source_channel: clean(authorNode ? authorNode.innerText : ""),
      source_content_type: "comment",
      page_url: location.href
    });
  }
  if (!rows.length && bodyText.length > 80) {
    add({id: location.href, title: document.title, text: bodyText, author: "", created_at: "",
         source_url: location.href, source_channel: "", source_content_type: "page", page_url: location.href});
  }
  return {rows: rows, page_title: document.title, page_url: location.href, page_text: bodyText};
})()
"""

CDP_DISCORD_EXTRACTOR = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const bodyText = clean(document.body ? document.body.innerText : "");
  if (/Robot Check|Enter the characters|验证码|异常流量|not a robot|captcha/i.test(bodyText)) {
    return {error: "challenge_page"};
  }
  const header = document.querySelector("h1, [class*='header-'] h1, section h1");
  const channel = clean(header ? header.textContent : "");
  const rows = [];
  for (const li of document.querySelectorAll('li[id^="chat-messages-"]')) {
    const id = (li.id.match(/chat-messages-\d+-\d+-(\d+)/) || [])[1] || li.id;
    const time = li.querySelector("time[datetime]");
    const author = li.querySelector('[class*="username"], [class*="author"]');
    const content = li.querySelector('[class*="messageContent"]');
    rows.push({
      id: id,
      title: "Discord message",
      text: clean(content ? content.innerText : li.innerText),
      author: clean(author ? author.textContent : ""),
      created_at: time ? time.getAttribute("datetime") || "" : "",
      source_url: location.href + "/" + id,
      source_channel: channel,
      source_content_type: "message",
      page_url: location.href
    });
  }
  // 论坛/帖子卡片不是 chat-messages 节点；不单独提取就会退回整页文本，
  // created_at、作者和帖子 URL 全部丢失。
  for (const card of document.querySelectorAll("article")) {
    const titleNode = card.querySelector("h1, h2, h3");
    const time = card.querySelector("time[datetime]");
    const link = card.querySelector('a[href*="/channels/"]');
    const href = link ? link.getAttribute("href") : "";
    const text = clean(card.innerText);
    if (text.length < 40) continue;
    const id = (href.match(/(\d+)(?:[/?]|$)/) || [])[1] || clean(titleNode ? titleNode.textContent : "") || String(rows.length);
    rows.push({
      id: id,
      title: clean(titleNode ? titleNode.textContent : "") || "Discord forum post",
      text: text,
      author: clean((card.querySelector('[class*="username"], [class*="author"]') || {}).textContent),
      created_at: time ? time.getAttribute("datetime") || "" : "",
      source_url: href ? new URL(href, location.href).href : location.href,
      source_channel: channel,
      source_content_type: "forum_post",
      page_url: location.href
    });
  }
  return {rows: rows, page_title: document.title, page_url: location.href, page_text: bodyText};
})()
"""

CDP_YOUTUBE_EXTRACTOR = r"""
(() => {
  const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const bodyText = clean(document.body ? document.body.innerText : "");
  if (/Robot Check|Enter the characters|验证码|异常流量|not a robot|captcha/i.test(bodyText)) {
    return {error: "challenge_page"};
  }
  const videoId = new URL(location.href).searchParams.get("v") || "";
  const channelNode = document.querySelector("ytd-channel-name #text, ytd-video-owner-renderer a");
  const channel = clean(channelNode ? channelNode.textContent : "");
  const rows = [];
  for (const thread of document.querySelectorAll("ytd-comment-thread-renderer")) {
    const comment = thread.querySelector("ytd-comment-view-model") || thread;
    const content = comment.querySelector("#content-text");
    const author = comment.querySelector("#author-text");
    const published = comment.querySelector("#published-time-text");
    const publishedText = clean(published ? published.textContent : "");
    const id = thread.getAttribute("data-comment-id") || comment.getAttribute("data-comment-id") ||
      (comment.querySelector("#published-time-text a") || {}).href || String(rows.length);
    rows.push({
      id: id, title: "YouTube comment", text: clean(content ? content.textContent : ""),
      author: clean(author ? author.textContent : ""), created_at: publishedText,
      date_precision: publishedText ? "relative_text" : "unknown", youtube_video_id: videoId,
      source_url: location.href, source_channel: channel,
      source_content_type: "comment", thread_id: videoId, page_url: location.href
    });
  }
  return {rows: rows, page_title: document.title, page_url: location.href, page_text: bodyText};
})()
"""

CDP_EXTRACTORS = {
    "instagram": CDP_INSTAGRAM_EXTRACTOR,
    "discord": CDP_DISCORD_EXTRACTOR,
    "youtube": CDP_YOUTUBE_EXTRACTOR,
}

CDP_PAGE_EXTRACTOR = r"""
(() => {
  const clean = (s) => String(s || "");
  return {
    title: document.title || "",
    url: location.href,
    text: clean(document.body ? document.body.innerText : "").slice(0, 200000)
  };
})()
"""


def _validate_capture_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("capture --url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("capture --url must not contain credentials")
    if parsed.port not in (None, default_port):
        raise ValueError("capture --url must use the default HTTP(S) port")
    return parsed.geturl()


# Capture is a narrow CDP exception, not a generic browser-scraping route.
# Only platforms whose catalog entry sets cdp: true (mirrored in CDP_TARGET_HOSTS)
# may use it, and each page follows the same explicit scope + enabled-adapter +
# registry-review checks as collect --cdp. Login-protected platforms are
# user-session-only: the user logs in by hand; challenges are never bypassed.
CAPTURE_HOST_PLATFORMS: dict[str, tuple[str, ...]] = {
    platform: hosts for platform, hosts in CDP_TARGET_HOSTS.items()
}
CAPTURE_HOST_PLATFORMS.update({
    "app_store": ("apps.apple.com",),
    "google_play": ("play.google.com",),
    "hackernews": ("news.ycombinator.com",),
    "stackoverflow": ("stackoverflow.com",),
    "zhihu": ("zhihu.com",),
    "xiaohongshu": ("xiaohongshu.com",),
    "jd": ("jd.com",),
    "taobao": ("taobao.com", "tmall.com"),
    "kickstarter": ("kickstarter.com",),
})


def _platform_for_capture_host(hostname: str) -> str | None:
    host = str(hostname or "").lower().rstrip(".")
    if not host:
        return None
    for platform, domains in CAPTURE_HOST_PLATFORMS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return None


def _capture_scope_failure(study: dict[str, Any], url: str) -> dict[str, Any] | None:
    """Apply collect's explicit allowed_sources rule to a capture URL."""
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    allowed = scope.get("allowed_sources") if isinstance(scope.get("allowed_sources"), list) else []
    allowed_ids = {str(item).strip() for item in allowed if str(item).strip()}
    parsed = urllib.parse.urlparse(str(url))
    platform = _platform_for_capture_host(parsed.hostname or "")
    host = str(parsed.hostname or "")
    if platform in CDP_TARGET_HOSTS and platform in allowed_ids:
        return None
    if platform not in CDP_TARGET_HOSTS:
        return {
            "status": "cdp_not_allowed",
            "platform": platform,
            "reason": (
                f"page host {host} is outside the CDP-enabled platforms "
                f"({'/'.join(CDP_TARGET_HOSTS)}); capture is not a generic browser route "
                "and blocked platforms never use CDP"),
            "allowed_sources": sorted(allowed_ids),
        }
    return {
        "status": "scope_blocked",
        "platform": platform,
        "reason": (
            f"page host {host} maps to {platform!r}, which is not listed in "
            "study.scope.allowed_sources"),
        "allowed_sources": sorted(allowed_ids),
        "note": "capture reuses the collect scope rule: one entrance, one rule set",
    }


def _capture_adapter_failure(study: dict[str, Any], platform: str) -> dict[str, Any] | None:
    """Match collect's registry and enabled-adapter checks before CDP I/O.

    An expired policy review is a warning, not a stop: capture records the
    review status and keeps the route open at a reduced cadence while a
    re-review is scheduled.
    """
    entry = platform_index().get(platform)
    if not entry or not entry.get("cdp") or entry.get("decision") == "blocked":
        return {
            "status": "cdp_not_allowed", "platform": platform,
            "reason": "CDP is only enabled for authorized visible pages on catalog "
                      "platforms with cdp: true and an approved target host",
        }
    adapters = study.get("source_adapters") if isinstance(study.get("source_adapters"), dict) else {}
    adapter = adapters.get(platform) if isinstance(adapters, dict) else None
    if not isinstance(adapter, dict) or not adapter.get("enabled", False):
        return {
            "status": "adapter_disabled", "platform": platform,
            "reason": "capture requires an enabled platform adapter in study.json, same as collect",
        }
    return None


def _ocr_with_vision(image_path: Path) -> dict[str, Any]:
    """Optional macOS Vision OCR adapter. Returns text/engine/error."""
    script = Path(__file__).with_name("ocr_image.swift")
    if sys.platform != "darwin":
        return {"engine": "macos_vision", "text": "", "error": "macOS Vision OCR only on darwin"}
    if not script.is_file():
        return {"engine": "macos_vision", "text": "", "error": f"missing {script.name}"}
    try:
        proc = subprocess.run(["swift", str(script), str(image_path)],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"engine": "macos_vision", "text": "", "error": str(exc)[:300]}
    if proc.returncode != 0:
        return {"engine": "macos_vision", "text": "",
                "error": (proc.stderr or proc.stdout or "ocr failed").strip()[:300]}
    text = proc.stdout.strip()
    return {"engine": "macos_vision", "text": text,
            "error": "" if text else "no text recognized"}


def capture_page(
    study_dir: Path,
    url: str,
    cdp_base: str,
    ack_terms: bool,
    *,
    ocr: bool = False,
    wait_seconds: float = 2.0,
    attach_existing: bool = False,
) -> dict[str, Any]:
    """Capture a user-authorized visible page through CDP.

    This writes a *candidate capture* under 01-sources/captures/: page text,
    screenshot, optional OCR text, hashes and source metadata. It does not
    register evidence or change the chain; a human must review it first.
    """
    study_dir = Path(study_dir).resolve()
    if not (study_dir / "study.json").is_file():
        return {"status": "error", "reason": f"missing study.json under {study_dir}"}
    if not ack_terms:
        return {"status": "terms_required",
                "reason": "capture needs --ack-terms and a browser session you are authorized to use"}
    try:
        url = _validate_capture_url(url)
        _validate_cdp_base(cdp_base)
    except ValueError as exc:
        return {"status": "error", "reason": str(exc)}
    try:
        study = load_json(study_dir / "study.json")
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "reason": f"cannot read study.json: {exc}"}
    if not isinstance(study, dict):
        return {"status": "error", "reason": "study.json must be a JSON object"}
    scope_failure = _capture_scope_failure(study, url)
    if scope_failure is not None:
        return scope_failure
    platform = _platform_for_capture_host(urllib.parse.urlparse(url).hostname or "")
    if platform is None:  # defensive: scope validation normally returns first
        return {"status": "cdp_not_allowed", "reason": "capture host is not approved"}
    try:
        _validate_cdp_target(platform, url)
    except ValueError as exc:
        return {"status": "error", "platform": platform, "reason": str(exc)}
    adapter_failure = _capture_adapter_failure(study, platform)
    if adapter_failure is not None:
        return adapter_failure
    strategy = _cdp_strategy()
    policy = strategy.policy_for(platform)
    capture_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                  + "-" + hashlib.sha256(url.encode()).hexdigest()[:8])
    out_dir = study_dir / "01-sources" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    client: CDPClient | None = None
    try:
        ws_url = cdp_existing_page(cdp_base, url) if attach_existing else cdp_new_page(cdp_base, url)
        client = CDPClient(_WebSocket(ws_url))
        client.call("Runtime.enable")
        # `/json/new` returns before navigation commits. A transient about:blank
        # is still the requested page loading, not evidence of a scope escape.
        deadline = time.monotonic() + max(0.5, wait_seconds)
        while True:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
            value = client.evaluate(CDP_PAGE_EXTRACTOR)
            if not isinstance(value, dict):
                return {"status": "error", "reason": "CDP did not return page content"}
            final_url = str(value.get("url") or url)
            if final_url != "about:blank" or time.monotonic() >= deadline:
                break
        if final_url == "about:blank":
            return {
                "status": "blank_render", "platform": platform,
                "reason": "page navigation did not commit before the capture wait expired; no candidate was written",
                "final_url": final_url, "terminal_state": "BLOCKED_USER_INPUT",
                "next_action": "retry once with a longer --wait after confirming the visible page loaded",
            }
        final_platform = _platform_for_capture_host(
            urllib.parse.urlparse(final_url).hostname or "")
        if final_platform != platform:
            return {
                "status": "scope_blocked", "platform": platform,
                "reason": "final page URL left the approved platform; capture stopped",
                "final_url": final_url,
            }
        try:
            _validate_cdp_target(platform, final_url)
        except ValueError as exc:
            return {"status": "error", "platform": platform, "reason": str(exc)}
        text = str(value.get("text") or "")
        challenge_waited = False
        if strategy.classify_page("", text) == "challenge":
            # Passive wait only: a human may complete the challenge in the same
            # browser. Never solve it, reload through a bypass, or alter the page.
            deadline = time.monotonic() + max(0.0, CAPTURE_CHALLENGE_WAIT_SECONDS)
            while time.monotonic() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                refreshed = client.evaluate(CDP_PAGE_EXTRACTOR)
                if not isinstance(refreshed, dict):
                    continue
                refreshed_text = str(refreshed.get("text") or "")
                if strategy.classify_page("", refreshed_text) != "challenge":
                    value = refreshed
                    text = refreshed_text
                    challenge_waited = True
                    break
            else:
                return {"status": "challenge",
                        "reason": ("page shows a challenge; passive wait expired and "
                                   "human completion was not observed — capture stopped")}
        title = str(value.get("title") or "")
        verdict = strategy.classify_page(title, text)
        if verdict == "challenge":
            # The title can still report the interstitial after the body
            # cleared; never mint a candidate out of a challenge page.
            return {"status": "challenge",
                    "reason": ("page still reports a challenge after the passive wait; "
                               "capture stopped without a candidate")}
        if verdict == "page_not_found":
            # An error page is not research evidence: stop before the
            # screenshot and persist no candidate for it.
            return {
                "status": "page_not_found",
                "platform": platform,
                "reason": ("final page reports a not-found/error state; "
                           "no candidate was written"),
                "final_url": final_url,
                "title": title,
            }
        if verdict == "blank_render":
            # 200 + empty title + empty body is an unsupported rendering stack,
            # not a challenge and not an empty corpus: no candidate, no retry.
            return {
                "status": "blank_render",
                "platform": platform,
                "reason": ("the page returned an empty title and body; this rendering "
                           "stack is unsupported on the CDP channel — pivot to another "
                           "source in the same vertical instead of retrying"),
                "final_url": final_url,
                "title": title,
                "runtime_policy": policy.to_dict(),
            }
        if platform == "discord" and len(text.strip()) < 1500 and strategy.detect_membership_gate(text):
            # Join is not access: a short page that announces a membership gate
            # is a coverage gap, not evidence. Never capture it as a candidate.
            return {
                "status": "membership_gated",
                "platform": platform,
                "reason": ("the page announces a membership verification gate; joining "
                           "a server is not permission to read its history — record the "
                           "gap; no candidate was written"),
                "final_url": final_url,
                "title": title,
                "runtime_policy": policy.to_dict(),
            }
        shot = client.call("Page.captureScreenshot", {"format": "png"})
        raw = shot.get("data") if isinstance(shot, dict) else None
        if not raw:
            return {"status": "error", "reason": "CDP screenshot returned no data"}
        image_path = out_dir / f"{capture_id}.png"
        image_path.write_bytes(base64.b64decode(raw))
        ocr_payload = {"engine": "not_requested", "text": "", "error": ""}
        if ocr:
            ocr_payload = _ocr_with_vision(image_path)
        # 同时保存平台结构化行：整页文本用于人工阅读，结构化行用于 created_at、
        # 作者和后续归一化。只存整页 title/text 会把平台字段全部丢掉。
        structured = client.evaluate(CDP_EXTRACTORS.get(platform, CDP_EXTRACTOR))
        structured_rows = structured.get("rows") if isinstance(structured, dict) else []
        if not isinstance(structured_rows, list):
            structured_rows = []
        structured_created_at = next(
            (str(row.get("created_at") or "") for row in structured_rows
             if str(row.get("created_at") or "").strip()), "")
        structured_author = next(
            (str(row.get("author") or "") for row in structured_rows
             if str(row.get("author") or "").strip()), "")
        payload = {
            "schema": "askovo.page-capture/1",
            "capture_id": capture_id,
            "captured_at": now(),
            "collected_at": now(),
            "url": url,
            "final_url": final_url,
            "source_url": final_url,
            "capture_platform": platform,
            "capture_mode": "attach_existing" if attach_existing else "new_page",
            "title": title,
            "text": text,
            "created_at": structured_created_at,
            "author": structured_author,
            "structured_rows": structured_rows[:200],
            "text_length": len(text),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "screenshot": str(image_path),
            "screenshot_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "ocr": {
                "engine": ocr_payload.get("engine"),
                "text": ocr_payload.get("text") or "",
                "text_length": len(str(ocr_payload.get("text") or "")),
                "text_sha256": hashlib.sha256(
                    str(ocr_payload.get("text") or "").encode()).hexdigest(),
                "error": ocr_payload.get("error") or "",
            },
            "cdp_endpoint": cdp_base,
            "ack_terms": True,
            "governance": {
                "transport": "cdp",
                "scope": "allowed_sources_matched",
                "adapter": "enabled",
                "registry_review": "expired" if platform_review_expired(platform) else "current",
                "challenge_check": ("waited_then_passed" if challenge_waited else "passed"),
                "cdp_loopback": True,
                "runtime_policy": policy.to_dict(),
            },
            "review_status": "expired" if platform_review_expired(platform) else "current",
            "warning": (
                "platform policy review is expired; capture continues on the authorized "
                "visible-page route at a reduced cadence and the registry re-review is "
                "scheduled rather than closing the route"
            ) if platform_review_expired(platform) else "",
            "evidence_status": "candidate",
            "note": "candidate capture only; named-human accept with an explicit evidence level is required", 
        }
        json_path = out_dir / f"{capture_id}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        with (out_dir / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "capture_id": capture_id, "captured_at": payload["captured_at"],
                "url": url, "title": payload["title"],
                "text_sha256": payload["text_sha256"],
                "screenshot": str(image_path),
                "ocr_error": payload["ocr"]["error"],
            }, ensure_ascii=False) + "\n")
        status = "captured"
        if ocr and payload["ocr"]["error"]:
            status = "ocr_failed"
        return {"status": status, "capture_id": capture_id, "capture": str(json_path),
                "screenshot": str(image_path), "ocr": payload["ocr"],
                "platform": platform, "source_url": final_url,
                "review_status": payload["review_status"],
                "evidence_status": "candidate", "text_length": len(text)}
    except (TimeoutError, socket.timeout) as exc:
        # A timeout tears the CDP stream and, on a session platform, is the
        # anti-automation signature itself: stop instead of retrying.
        decision = strategy.classify_failure(exc, platform=platform, policy=policy)
        return {
            "status": "cdp_timeout",
            "platform": platform,
            "reason": str(exc),
            "action": decision["message"],
            "retry_after_seconds": int(policy.timeout_cooldown_minutes * 60),
            "runtime_policy": policy.to_dict(),
        }
    finally:
        if client is not None:
            client.close()


def _collection_scope_failure(study_dir: Path, platform: str, *, fixture: bool = False) -> dict[str, Any] | None:
    study = load_json(study_dir / "study.json")
    scope = study.get("scope", {}) if isinstance(study, dict) else {}
    allowed_sources = scope.get("allowed_sources", []) if isinstance(scope, dict) else []
    if not isinstance(allowed_sources, list) or platform not in allowed_sources:
        return {"status": "scope_blocked", "platform": platform,
                "reason": "platform is not listed in study.scope.allowed_sources"}
    if fixture:
        # 授权离线导出不需要 live adapter；enabled=false 只阻断真实在线采集。
        return None
    adapters = study.get("source_adapters", {}) if isinstance(study, dict) else {}
    adapter = adapters.get(platform) if isinstance(adapters, dict) else None
    if isinstance(adapter, dict) and adapter.get("enabled") is False:
        # 只有显式 enabled=false 才是禁用；缺省配置、fixture 和 CDP 都按原路线放行。
        return {"status": "adapter_disabled", "platform": platform,
                "reason": "live collection requires an enabled platform adapter in study.json"}
    return None


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
    attach_existing: bool = False,
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
            "reason": "CDP is only enabled for authorized visible pages on the catalog platforms with cdp: true",
        }
    if not url:
        return {"status": "error", "platform": platform, "reason": "CDP requires --url"}
    _validate_cdp_target(platform, url)
    scope_failure = _collection_scope_failure(study_dir, platform)
    if scope_failure is not None:
        return scope_failure
    started_at = now()
    if lease_valid is not None and not lease_valid():
        return {"status": "lease_lost", "platform": platform, "reason": "queue lease is no longer owned by this worker"}
    strategy = _cdp_strategy()
    policy = strategy.policy_for(platform)
    guard = strategy.SessionGuard(platform, policy=policy)
    guard.begin_cell("collect")
    if not attach_existing:
        guard.navigate()  # one goto per cell: the page is opened exactly once
    extractor = CDP_EXTRACTORS.get(platform, CDP_EXTRACTOR)
    client: CDPClient | None = None
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    try:
        ws_url = cdp_existing_page(cdp_base, url) if attach_existing else cdp_new_page(cdp_base, url)
        client = CDPClient(_WebSocket(ws_url))
        client.call("Runtime.enable")
        time.sleep(max(0.5, wait_seconds))
        stale_rounds = 0
        for _ in range(max(0, scrolls) + 1):
            guard.check_session()
            value = client.evaluate(extractor)
            page_kind = strategy.classify_page(
                str(value.get("page_title") or "") if isinstance(value, dict) else "",
                str(value.get("page_text") or "") if isinstance(value, dict) else "",
            )
            if page_kind == "challenge":
                guard.record_stop("challenge_page")
                return {
                    "status": "challenge",
                    "platform": platform,
                    "reason": "page title or body shows a challenge; stop without scrolling or writing a run",
                }
            if page_kind == "page_not_found":
                guard.record_stop("page_not_found")
                return {"status": "page_not_found", "platform": platform,
                        "reason": "the approved page is not available; do not collect an error page"}
            if isinstance(value, dict):
                final_url = str(value.get("page_url") or url)
                try:
                    _validate_cdp_target(platform, final_url)
                except ValueError:
                    guard.record_stop("scope_violation")
                    return {"status": "scope_violation", "platform": platform,
                            "reason": "final page URL left the authorized platform/host; no run was written"}
            if isinstance(value, dict) and value.get("error") == "challenge_page":
                guard.record_stop("challenge_page")
                return {
                    "status": "challenge",
                    "platform": platform,
                    "reason": "page shows a challenge/robot check; stop and use an authorized export instead",
                }
            if (
                not rows
                and isinstance(value, dict)
                and not value.get("rows")
                and strategy.looks_logged_out(
                    str(value.get("page_url") or url), str(value.get("page_text") or "")
                )
            ):
                guard.record_session_drop("login page after navigation")
                return {
                    "status": "session_drop",
                    "platform": platform,
                    "reason": "the user session is not logged in; a human must log in before retrying",
                }
            if (
                not rows
                and isinstance(value, dict)
                and not value.get("rows")
                and not str(value.get("page_title") or "").strip()
            ):
                # 200 + empty title + empty body is an unsupported stack, not
                # an empty corpus: stop before writing an empty run.
                guard.record_stop("blank_render")
                return {
                    "status": "blank_render",
                    "platform": platform,
                    "reason": ("page returned an empty title and body; unsupported rendering "
                               "stack — pivot to another source in the same vertical"),
                    "runtime_policy": policy.to_dict(),
                }
            before = len(rows)
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
            stale_rounds = stale_rounds + 1 if len(rows) == before else 0
            if stale_rounds >= 2:
                # The list stopped growing: stop instead of metronome-scrolling
                # a page that is not producing (silent extractor failure triage).
                break
            if platform in {"discord", "instagram", "x", "tiktok"}:
                client.call("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": 640, "y": 360,
                })
                client.call("Input.dispatchMouseEvent", {
                    "type": "mouseWheel", "x": 640, "y": 360,
                    "deltaX": 0, "deltaY": -900 if platform == "discord" else 900,
                })
            else:
                client.evaluate("window.scrollBy(0, Math.max(700, Math.floor(window.innerHeight * 0.85)))")
            time.sleep(max(0.4, wait_seconds / 2))
    except (TimeoutError, socket.timeout, strategy.SessionExpired, strategy.CircuitOpen) as exc:
        decision = guard.record_failure(exc, str(exc))
        status = "cdp_timeout" if isinstance(exc, (TimeoutError, socket.timeout)) else (
            "session_expired" if isinstance(exc, strategy.SessionExpired) else "cooldown")
        return {
            "status": status,
            "platform": platform,
            "reason": str(exc),
            "action": decision["message"],
            "retry_after_seconds": int(policy.timeout_cooldown_minutes * 60),
            "runtime_policy": policy.to_dict(),
        }
    finally:
        guard.end_cell("circuit_open" if guard.circuit()["open"] else "ok")
        if client is not None:
            client.close()
    if not rows:
        return {
            "status": "empty_unconfirmed",
            "platform": platform,
            "reason": "no records were extracted; the page may be empty, blocked or using an unsupported selector",
        }
    completed_at = now()
    raw_records = [
        {
            "id": str(row.get("id") or row.get("href") or f"{platform}:{hashlib.sha256((row.get('source_url','') + row.get('text','')[:500]).encode()).hexdigest()[:16]}"),
            "title": row.get("title") or "",
            "text": row.get("text") or "",
            "url": row.get("source_url") or row.get("url") or row.get("href") or url,
            "author": row.get("author") or "",
            "created_at": row.get("created_at") or row.get("published_at") or row.get("time") or "",
            "context": "cdp_visible_page",
            "rating": row.get("rating") or "",
            "source_channel": row.get("source_channel") or "",
            "source_content_type": row.get("source_content_type") or "unknown",
            "parent_id": row.get("parent_id"),
            "thread_id": row.get("thread_id"),
            "claim_type": "need",
            "evidence_form": "self_report",
            "source_order": source_order,
            "date_precision": row.get("date_precision") or "unknown",
            "content_status": row.get("content_status") or "present",
            "last_verified_at": row.get("last_verified_at") or "",
        }
        for source_order, row in enumerate(rows[:limit])
    ]
    try:
        study = load_json(study_dir / "study.json")
        adapter = (study.get("source_adapters") or {}).get(platform) or {}
    except (OSError, json.JSONDecodeError):
        adapter = {}
    if platform == "youtube":
        for raw in raw_records:
            raw["refresh_due_at"] = str(adapter.get("refresh_due_at") or "")
    if adapter.get("allow_personal_data") is False:
        for raw in raw_records:
            author = str(raw.get("author") or "")
            pseudonym = _hash_author(author) if author else ""
            raw["author"] = pseudonym
            raw["author_hash"] = pseudonym or None
            if str(raw.get("source_channel") or "") == author:
                raw["source_channel"] = pseudonym
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
        "started_at": started_at,
        "finished_at": completed_at,
        "requested": limit,
        "source_url": url,
        "cdp_base": cdp_base,
        "capture_mode": "attach_existing" if attach_existing else "new_page",
        "runtime_policy": policy.to_dict(),
        "limits": entry.get("limits", []),
        "bias": entry.get("bias", []),
        "terms_note": "visible page text only; no challenge bypass; platform terms may still restrict collection",
        "review_status": "expired" if platform_review_expired(platform) else "current",
        "warnings": [
            "platform policy review is expired; capture continues on the authorized "
            "visible-page route at a reduced cadence while the registry re-review is scheduled"
        ] if platform_review_expired(platform) else [],
    }
    written = _write_run(study_dir, platform, run_id, normalized, manifest, raw_records)
    return {"status": "collected", "platform": platform, "transport": "cdp", "records": len(normalized),
            "review_status": manifest["review_status"], "warnings": manifest["warnings"], **written}


def _procurement_preflight(study_dir: Path, platform: str,
                           entry: dict[str, Any]) -> dict[str, Any] | None:
    """Stop routes whose live access requires the user to buy/license a service.

    An authorized local fixture bypasses this preflight because no provider is
    selected. Askovo never purchases a tier, provider, credits, or subscription.
    """
    access_modes = {str(item) for item in entry.get("access_modes", [])}
    paid_api = str(entry.get("auth") or "") == "oauth_paid"
    licensed_provider = "licensed_provider" in access_modes
    if not paid_api and not licensed_provider:
        return None
    import_command = (
        f"askovo import {study_dir} <authorized-export.jsonl> "
        f"--source-family {platform} --evidence-level E1"
    )
    alternatives = [
        {"route": "authorized_export_or_paste", "command": import_command,
         "requires_procurement": False},
        {"route": "local_screenshot_transcription",
         "action": "transcribe a screenshot you are authorized to use, import the text, "
                   "and have a named human assign its evidence level; OCR itself assigns none",
         "requires_procurement": False},
    ]
    if entry.get("cdp") and platform in CDP_TARGET_HOSTS:
        alternatives.insert(0, {
            "route": "authorized_visible_page_cdp",
            "command": f"askovo capture page {study_dir} --url <approved-visible-url> --ack-terms --ocr",
            "then": "askovo capture accept ... --by NAME --evidence-level E0|E1|E2",
            "requires_procurement": False,
        })
    service = "the official paid API tier" if paid_api else "a licensed data provider"
    return {
        "status": "blocked",
        # C-01 §3 registry vocabulary for the machine-readable reason; the
        # delivery-contract terminal state (BLOCKED_USER_INPUT) travels in its
        # own field so the frozen ten-code registry stays intact.
        "reason_code": "INPUT_REQUIRED",
        "blocked_reason_code": "INPUT_REQUIRED",
        "terminal_state": "BLOCKED_USER_INPUT",
        "platform": platform,
        "reason": f"live {platform} collection selects {service}; user input/procurement is required",
        "requires_procurement": True,
        "user_action": (
            f"Use an authorized export/local paste, or arrange access to {service} yourself. "
            "Askovo cannot buy it or confirm eligibility for you."),
        "transaction_executed": False,
        "alternative_routes": alternatives,
    }


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
    attach_existing: bool = False,
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
    if fixture is None and not cdp_url:
        procurement_block = _procurement_preflight(study_dir, platform, entry)
        if procurement_block is not None:
            return procurement_block
    run_id = run_id or _run_id(platform)
    review_expired = platform_review_expired(platform)
    review_warnings: list[str] = []
    if review_expired:
        review_warnings.append(
            "platform policy review is expired; collection continues on the authorized "
            "route at a reduced cadence while the registry re-review is scheduled"
        )
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
        "review_status": "expired" if review_expired else "current",
        "warnings": review_warnings,
    }
    if cdp_url:
        plan["transport"] = "cdp"
        plan["adapter"] = "cdp"
        plan["url"] = url
        plan["ack_terms"] = ack_terms
        plan["attach_existing"] = attach_existing
    if dry_run:
        next_command = (
            f"askovo collect {study_dir} --platform {platform} --query {query!r} --limit {limit}"
        )
        if cdp_url:
            next_command += f" --cdp-url {cdp_url} --url {str(url or '')!r}"
            if ack_terms:
                next_command += " --ack-terms"
            if attach_existing:
                next_command += " --attach-existing"
        return {"status": "planned", **plan, "next": next_command}
    scope_failure = _collection_scope_failure(study_dir, platform, fixture=fixture is not None)
    if scope_failure is not None:
        return scope_failure
    study = load_json(study_dir / "study.json")
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
    started_at = now()
    if cdp_url:
        return collect_cdp(
            study_dir, platform, query, url or "", cdp_url, ack_terms, limit,
            run_id=run_id, lease_valid=lease_valid, attach_existing=attach_existing,
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
    elif entry.get("adapter") == "youtube":
        try:
            raw_records = _collect_youtube(query, limit)
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            return {"status": "error", "platform": platform, "reason": str(exc)}
    elif entry.get("adapter") == "hackernews":
        try:
            raw_records = _collect_hn(query, limit)
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
    completed_at = now()
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
        "started_at": started_at,
        "finished_at": completed_at,
        "requested": limit,
        "limits": entry.get("limits", []),
        "bias": entry.get("bias", []),
        "review_status": plan["review_status"],
        "warnings": plan["warnings"],
    }
    written = _write_run(study_dir, platform, run_id, normalized, manifest, raw_records[:limit])
    return {"status": "collected", "platform": platform, "records": len(normalized),
            "review_status": plan["review_status"], "warnings": plan["warnings"], **written}


def _analysis_segments(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive segment counts; small cells stay visible but flagged."""
    dimensions = {
        "platform": lambda record: str(record.get("platform") or record.get("source_family") or "unknown"),
        "claim_type": lambda record: _evidence_claim(record),
        "evidence_form": lambda record: _evidence_form(record),
        "corpus_role": lambda record: str(record.get("corpus_role") or "unknown"),
    }
    total = len(records) or 1
    result: dict[str, Any] = {}
    for name, key in dimensions.items():
        buckets: dict[str, dict[str, Any]] = {}
        for record in records:
            value = key(record)
            bucket = buckets.setdefault(value, {"n": 0, "evidence_levels": {}})
            bucket["n"] += 1
            level = str(record.get("evidence_level") or "unregistered")
            bucket["evidence_levels"][level] = bucket["evidence_levels"].get(level, 0) + 1
        result[name] = [
            {
                "value": value,
                "n": bucket["n"],
                "share": round(bucket["n"] / total, 4),
                "low_n": bucket["n"] < 3,
                "evidence_levels": bucket["evidence_levels"],
            }
            for value, bucket in sorted(buckets.items(), key=lambda item: (-item[1]["n"], item[0]))
        ]
    return result


def _analysis_time_coverage(records: list[dict[str, Any]], study: dict[str, Any]) -> dict[str, Any]:
    months = sorted({
        _record_time(record)[:7]
        for record in records
        if len(_record_time(record)) >= 7
    })
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    window = scope.get("source_time_window") if isinstance(scope.get("source_time_window"), dict) else {}
    start = str(window.get("start") or "")
    end = str(window.get("end") or "")
    outside = 0
    valid = False
    try:
        start_day = datetime.strptime(start, "%Y-%m-%d").date()
        end_day = datetime.strptime(end, "%Y-%m-%d").date()
        valid = True
    except (TypeError, ValueError):
        start_day = end_day = None
    if valid and start_day and end_day:
        for record in records:
            day = _record_time(record)[:10]
            try:
                parsed = datetime.strptime(day, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if parsed < start_day or parsed > end_day:
                outside += 1
    return {
        "months": months,
        "month_count": len(months),
        "window": {"start": start, "end": end} if valid else None,
        "outside_window": outside,
        "boundary": "时间覆盖只说明记录分布；不在窗口内的记录需要单独解释，不能当作总体趋势。",
    }


ANALYSIS_FIELD_CONCEPTS = {
    "record_id": ("record_id", "id"),
    "text": ("text", "body", "normalized_text", "content", "selftext"),
    "source_url": ("source_url", "url", "source_ref"),
    "created_at": ("created_at", "published_at", "source_time", "created", "timestamp", "created_utc", "time", "published_time", "date_text"),
}
ANALYSIS_REQUIRED_FIELDS = ("record_id",)


def _analysis_field_completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Non-empty rates for the fields a downstream join depends on.

    A 0% rate on record_id is a normalization bug. text/source_url/created_at
    can legitimately be absent for first-party or structured material, so they
    are reported but only flagged for review, not declared a bug.
    """
    total = len(records)
    fields: dict[str, dict[str, Any]] = {}
    for concept, keys in ANALYSIS_FIELD_CONCEPTS.items():
        if concept == "text":
            non_empty = sum(1 for record in records if str(_evidence_text(record) or "").strip())
        else:
            non_empty = sum(
                1 for record in records
                if any(str(record.get(key) or "").strip() for key in keys)
            )
        fields[concept] = {
            "non_empty": non_empty,
            "ratio": round(non_empty / total, 3) if total else 0.0,
        }
    zero = [concept for concept, item in fields.items() if total and item["non_empty"] == 0]
    return {
        "fields": fields,
        "zero_rate_fields": zero,
        "required_zero_rate": [concept for concept in zero if concept in ANALYSIS_REQUIRED_FIELDS],
        "note": (
            "0% 的 record_id 是清洗/转换 bug；正文、source_url、created_at 对第一方或结构化材料"
            "可能本来为空，按来源复核后再判断。先修管线，不要改派生结论。"
        ),
    }


def _record_time(record: dict[str, Any]) -> str:
    """First known timestamp on a record; imports and captures use different aliases."""
    return str(
        record.get("created_at") or record.get("published_at") or record.get("source_time")
        or record.get("created") or record.get("timestamp") or record.get("created_utc")
        or record.get("time") or record.get("published_time") or record.get("date_text")
        or record.get("collected_at") or ""
    )


_CHINESE_LEXICON: tuple[set[str], int] | None = None


def _chinese_lexicon() -> tuple[set[str], int]:
    """Load the bundled Chinese lexicon once: (terms, max term length)."""
    global _CHINESE_LEXICON
    if _CHINESE_LEXICON is None:
        terms: set[str] = set()
        try:
            for line in CHINESE_LEXICON_PATH.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word and not word.startswith("#"):
                    terms.add(word)
        except OSError:
            terms = set()
        longest = max((len(term) for term in terms), default=0)
        _CHINESE_LEXICON = (terms, longest)
    return _CHINESE_LEXICON


def _cjk_lexicon_terms(run: str) -> list[str]:
    """Greedy longest-match segmentation of one CJK run against the lexicon.

    Unmatched characters are skipped, so the caller never receives character
    fragments: a term appears only when the lexicon knows the word.
    """
    terms, longest = _chinese_lexicon()
    if not terms:
        return []
    found: list[str] = []
    index = 0
    while index < len(run):
        matched = ""
        for size in range(min(longest, len(run) - index), 1, -1):
            candidate = run[index:index + size]
            if candidate in terms:
                matched = candidate
                break
        if matched:
            found.append(matched)
            index += len(matched)
        else:
            index += 1
    return found


def _analysis_terms(text: str, stop: set[str]) -> list[str]:
    """Descriptive terms: Latin words (3+) plus lexicon-matched Chinese words."""
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]+", text.casefold()):
        if token[0].isascii():
            if token not in stop:
                terms.append(token)
        else:
            terms.extend(_cjk_lexicon_terms(token))
    return terms


def _query_terms(question: str, stop: set[str]) -> list[str]:
    """Match terms for a question; CJK runs with no lexicon hit fall back to
    2-char bigrams so an unseen word still matches records instead of
    silently returning zero hits."""
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]+", question.casefold()):
        if token[0].isascii():
            if token not in stop:
                terms.append(token)
            continue
        run_terms = _cjk_lexicon_terms(token)
        if run_terms:
            terms.extend(run_terms)
        elif len(token) >= 2:
            terms.extend(token[i:i + 2] for i in range(len(token) - 1))
    return terms


def _topic_counts(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if key == "platform":
            value = str(record.get("platform") or record.get("source_family") or "unknown")
        else:
            value = str(record.get(key) or "unknown").strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _analysis_topics(records: list[dict[str, Any]], stop: set[str], *, max_topics: int = 8) -> list[dict[str, Any]]:
    """Deterministic co-occurrence topics; descriptive candidates, not prevalence claims."""
    doc_terms: list[tuple[dict[str, Any], set[str]]] = []
    df: dict[str, int] = {}
    for record in records:
        terms = {term for term in _analysis_terms(_evidence_text(record), stop) if len(term) >= 2}
        doc_terms.append((record, terms))
        for term in terms:
            df[term] = df.get(term, 0) + 1
    total = len(records)
    if total < 3:
        return []
    candidates = [
        term for term, count in df.items()
        if count >= 2 and count <= max(2, int(total * 0.65))
    ]
    candidates.sort(key=lambda term: (-df[term], term))
    candidates = candidates[:40]
    adjacency: dict[str, set[str]] = {term: set() for term in candidates}
    for _, terms in doc_terms:
        common = sorted(terms.intersection(candidates))
        for index, left in enumerate(common):
            for right in common[index + 1:]:
                adjacency[left].add(right)
                adjacency[right].add(left)
    visited: set[str] = set()
    clusters: list[set[str]] = []
    for term in candidates:
        if term in visited:
            continue
        stack = [term]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    stack.append(neighbor)
        if len(component) >= 2 or df[term] >= 3:
            clusters.append(component)
    topics: list[dict[str, Any]] = []
    for component in clusters:
        members = [record for record, terms in doc_terms if terms.intersection(component)]
        if not members:
            continue
        terms_sorted = sorted(component, key=lambda term: (-df[term], term))
        topics.append({
            "terms": terms_sorted[:6],
            "record_count": len(members),
            "example_record_ids": [str(record.get("record_id") or "") for record in members[:3]],
            "platforms": _topic_counts(members, "platform"),
            "evidence_levels": _topic_counts(members, "evidence_level"),
            "note": "共现聚合的候选主题，不是总体主题比例；需要人工命名与复核",
        })
    topics.sort(key=lambda item: -item["record_count"])
    return topics[:max_topics]


_MECHANISM_RE = re.compile(
    r"因为|由于|所以|因此|导致|于是|才会|就会|because|so that|therefore|due to|as a result",
    re.IGNORECASE,
)
_CONTRAST_RE = re.compile(
    r"但|但是|然而|不过|却|而是|并非|不是|没有|but|however|although|though|instead|rather than",
    re.IGNORECASE,
)


def _analysis_mechanisms(records: list[dict[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    """Candidate mechanism/contrast sentences; markers are not proof of causality."""
    found: list[dict[str, Any]] = []
    for record in records:
        text = _evidence_text(record)
        for sentence in re.split(r"[。！？；\n.!?;]+", text):
            excerpt = sentence.strip()
            if len(excerpt) < 8:
                continue
            if _MECHANISM_RE.search(excerpt):
                kind = "mechanism_candidate"
            elif _CONTRAST_RE.search(excerpt):
                kind = "contrast_candidate"
            else:
                continue
            found.append({
                "kind": kind,
                "record_id": str(record.get("record_id") or ""),
                "platform": str(record.get("platform") or record.get("source_family") or "unknown"),
                "evidence_level": str(record.get("evidence_level") or "unclassified"),
                "text": excerpt[:300],
            })
            if len(found) >= limit:
                return found
    return found


def _analysis_duplicates(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for record in records:
        text = _evidence_text(record)
        digest = str(record.get("normalized_text_hash") or "")
        if not digest:
            digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        groups.setdefault(digest, []).append(str(record.get("record_id") or ""))
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    return {
        "duplicate_groups": duplicates[:20],
        "duplicate_records": sum(len(group) for group in duplicates),
        "unique_records": len(groups),
        "note": "normalized_text_hash 或正文哈希归并；近重复改写不会被误判为独立主题",
    }


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
        claim = _evidence_claim(record)
        form = _evidence_form(record)
        by_platform[platform] = by_platform.get(platform, 0) + 1
        by_claim[claim] = by_claim.get(claim, 0) + 1
        by_form[form] = by_form.get(form, 0) + 1
        created = _record_time(record)
        if len(created) >= 7:
            month = created[:7]
            by_month[month] = by_month.get(month, 0) + 1
        text = _evidence_text(record)
        lengths.append(len(text))
        text_blob.append(text)
    stop = set("the and for with that this from are was were you your our not but have has had will can could should about into over under more most some such than then them they their there here what when where which who whom why how all any both each few other own same so too very just also".split())
    tokens: dict[str, int] = {}
    for text in text_blob:
        for token in _analysis_terms(text, stop):
            tokens[token] = tokens.get(token, 0) + 1
    top_terms = sorted(tokens.items(), key=lambda item: (-item[1], item[0]))[:30]
    matches = []
    if question:
        q_terms = _query_terms(question, stop)
        for record in unique:
            text = _evidence_text(record).lower()
            hit = [term for term in q_terms if term in text]
            if hit:
                matches.append({"record_id": record.get("record_id"), "platform": record.get("platform"), "hits": hit, "excerpt": _evidence_text(record)[:300]})
        matches.sort(key=lambda item: (-len(item["hits"]), str(item["record_id"])))
    try:
        study = load_json(study_dir / "study.json")
        if not isinstance(study, dict):
            study = {}
    except (OSError, json.JSONDecodeError):
        study = {}
    level_counts: dict[str, int] = {}
    for record in unique:
        level = str(record.get("evidence_level") or "unregistered")
        level_counts[level] = level_counts.get(level, 0) + 1
    field_completeness = _analysis_field_completeness(unique)
    analysis = {
        "generated_at": now(),
        "question": question,
        "records": len(unique),
        "invalid_records": invalid_records,
        "by_platform": by_platform,
        "by_claim_type": by_claim,
        "by_evidence_level": dict(sorted(level_counts.items())),
        "segments": _analysis_segments(unique),
        "segments_note": "描述性计数，n<3 的分段标记 low_n；不做显著性、因果或总体推断。",
        "time_coverage": _analysis_time_coverage(unique, study),
        "field_completeness": field_completeness,
        "topics": _analysis_topics(unique, stop),
        "mechanisms": _analysis_mechanisms(unique),
        "duplicates": _analysis_duplicates(unique),
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
        "## 字段完整性（管线体检）",
        "",
    ]
    field_labels = {
        "record_id": "记录 id",
        "text": "正文",
        "source_url": "来源 URL",
        "created_at": "发生时间",
    }
    for concept, item in field_completeness["fields"].items():
        lines.append(
            f"- {field_labels.get(concept, concept)}：{item['non_empty']}/{analysis['records']}"
            f"（{item['ratio']:.0%}）"
        )
    if field_completeness["required_zero_rate"]:
        lines.append(
            "- **0% 必填字段：" + "、".join(
                field_labels.get(item, item) for item in field_completeness["required_zero_rate"])
            + "**——先查清洗/转换是否丢字段，不要把 0% 当来源缺口。"
        )
    elif field_completeness["zero_rate_fields"]:
        lines.append(
            "- 0% 字段：" + "、".join(
                field_labels.get(item, item) for item in field_completeness["zero_rate_fields"])
            + "（第一方或结构化材料可能本来为空，按来源复核）。"
        )
    lines.extend([
        "",
        "> " + field_completeness["note"],
        "",
    ])
    stop = set("the and for with that this from are was were you your our not but have has had will can could should about into over under more most some such than then them they their there here what when where which who whom why how all any both each few other own same so too very just also".split())
    topics = _analysis_topics(records, stop)
    if topics:
        lines.extend(["## 候选主题（共现聚合）", ""])
        for index, topic in enumerate(topics, start=1):
            lines.append(
                f"{index}. **{' / '.join(topic['terms'])}**（{topic['record_count']} 条）"
                f" · 例：{', '.join(topic['example_record_ids'])}")
        lines.append("> 共现聚合只是候选主题，不是总体主题比例；需要人工命名与复核。")
        lines.append("")
    mechanisms = _analysis_mechanisms(records)
    if mechanisms:
        lines.extend(["## 机制与转折句（候选）", ""])
        for item in mechanisms[:12]:
            lines.append(
                f"- [{item['kind']}] `{item['record_id']}`（{item['platform']} / {item['evidence_level']}）：{item['text']}")
        lines.append("> 含因果/转折词的句子是候选机制或反证线索，不等于已验证因果。")
        lines.append("")
    duplicates = _analysis_duplicates(records)
    lines.extend([
        "## 重复与独立记录", "",
        f"- 重复组：{len(duplicates['duplicate_groups'])}；重复记录：{duplicates['duplicate_records']}；去重后独立记录：{duplicates['unique_records']}",
        f"> {duplicates['note']}",
        "",
        "## 高频词（候选主题，不是结论）",
        "",
    ])
    lines.extend(f"- {item['term']}：{item['count']}" for item in analysis["top_terms"][:20])
    if question:
        lines.extend(["", "## 与问题的匹配片段", ""])
        for item in matches[:10]:
            lines.append(f"- `{item['record_id']}`（{item['platform']}）：{item['excerpt']}")
    lines.extend(["", "## 分段（描述性）", ""])
    for dimension in ("platform", "claim_type", "corpus_role"):
        values = analysis["segments"].get(dimension) or []
        rendered = "；".join(
            f"{item['value']} {item['n']} 条" + ("（low_n）" if item["low_n"] else "")
            for item in values[:8]
        )
        lines.append(f"- {dimension}：{rendered or '无'}")
    coverage = analysis["time_coverage"]
    lines.extend([
        "",
        "## 时间覆盖",
        "",
        f"- 覆盖月份：{'、'.join(coverage['months']) or '无'}（{coverage['month_count']} 个月）",
        f"- 声明窗口：{json.dumps(coverage['window'], ensure_ascii=False) if coverage['window'] else '未配置'}",
        f"- 窗口外记录：{coverage['outside_window']} 条；窗口外记录需要单独解释。",
    ])
    lines.extend(["", "## 边界", "", analysis["boundary"]])
    (out_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "analyzed", "analysis": str(out_dir / "analysis.json"), "markdown": str(out_dir / "analysis.md"), "records": len(unique)}


# --------------------------------------------------------------------------- #
# Research answer: the terminal projection of the golden chain
# (capture/paste -> human review -> evidence -> analyze -> answer).
# It is a deterministic read over evidence.jsonl + study.decision: the
# conclusion changes when the evidence changes, every cited record keeps its
# collection back-link, and no evidence means unanswerable + gap list —
# never an invented conclusion. It writes no canonical truth.
# --------------------------------------------------------------------------- #

ANSWER_SCHEMA = "askovo.research-answer/1"
ANSWER_MIN_SUPPORT = 3  # n<3 is low_n everywhere else in the engine; go needs it met
ANSWER_STOPWORDS = set(
    "the and for with that this from are was were you your our not but have has had will "
    "can could should about into over under more most some such than then them they their "
    "there here what when where which who whom why how all any both each few other own same "
    "so too very just also a an of to in on at or be is it as by we do does did".split())
_STATUS_QUO_MARKERS = ("不做", "维持现状", "保持现状", "停止", "放弃", "暂缓",
                       "do nothing", "status quo", "stop the", "cancel the", "postpone")


def _answer_terms(text: str) -> list[str]:
    return [token for token in
            re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", str(text or "").lower())
            if token not in ANSWER_STOPWORDS]


def _cjk_bigrams(text: str) -> set[str]:
    chars = re.findall(r"[\u4e00-\u9fff]", str(text or ""))
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _option_match_keys(options: list[str]) -> list[set[str]]:
    """Distinctive match keys per option: CJK bigrams + latin tokens.

    Bigrams shared by two options (e.g. 「摄像头」in every alternative) cannot
    distinguish anything, so they are dropped; an option whose keys are all
    shared falls back to its full key set instead of matching nothing.
    """
    raw = []
    for option in options:
        keys = set(_answer_terms(option))
        keys |= {bigram.lower() for bigram in _cjk_bigrams(option)}
        raw.append(keys)
    distinctive = []
    for index, keys in enumerate(raw):
        shared = set().union(*(raw[other] for other in range(len(raw)) if other != index)) \
            if len(raw) > 1 else set()
        distinctive.append(keys - shared or keys)
    return distinctive


def _is_counter_record(record: dict[str, Any]) -> bool:
    return (str(record.get("claim_type")) == "counter"
            or str(record.get("corpus_role")) in ("control", "substitute_rejector")
            or str(record.get("evidence_level")) == "E4-")


def _answer_ref(record: dict[str, Any]) -> dict[str, Any]:
    ref = {
        "record_id": str(record.get("record_id") or ""),
        "source_family": str(record.get("source_family") or ""),
        "source_ref": str(record.get("source_ref") or ""),
        "evidence_level": str(record.get("evidence_level") or ""),
        "excerpt": _evidence_text(record)[:120],
    }
    if record.get("capture_id"):
        ref["capture_id"] = str(record.get("capture_id"))
    if record.get("capture_url"):
        ref["url"] = str(record.get("capture_url"))
    return ref


def _chain_node_states(study_dir: Path) -> dict[str, Any]:
    path = study_dir / "04-findings" / "product-reasoning.json"
    try:
        reasoning = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {"available": False, "note": "no readable product-reasoning.json"}
    chains = reasoning.get("chains") if isinstance(reasoning, dict) else None
    if not isinstance(chains, list) or not chains:
        return {"available": False, "note": "no chains written yet; nodes stay hypotheses"}
    states: dict[str, Any] = {}
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id") or "")
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        states[chain_id] = {
            str(node): str((node_data or {}).get("status") or "hypothesis")
            for node, node_data in nodes.items()
        }
    return {"available": True, "chains": states}


def _decision_option_entries(study: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize declared decision options; direction is explicit data only.

    Supported shapes::

        "options": ["Run a pilot", "Stop"]
        "option_directions": {"option-A": "go", "option-B": "no_go"}
        "options": [{"id": "pilot", "label": "Run a pilot", "direction": "go"}]

    A missing direction stays missing. Guessing polarity from words such as
    "stop" inverts statements like "stop delaying and launch the pilot", so the
    formal answer never reads direction out of free text.
    """
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    raw = decision.get("options") or []
    directions = decision.get("option_directions") \
        if isinstance(decision.get("option_directions"), dict) else {}
    entries: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        fallback_id = "option-%s" % (chr(ord("A") + index) if index < 26 else index + 1)
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("statement") or "").strip()
            option_id = str(item.get("id") or "").strip() or fallback_id
            direction = str(item.get("direction")
                            or directions.get(option_id) or "").strip().lower()
        else:
            label = str(item).strip()
            option_id = fallback_id
            direction = str(directions.get(option_id) or "").strip().lower()
        entries.append({
            "id": option_id,
            "label": label,
            "direction": direction if direction in ("go", "no_go") else "",
        })
    return entries


def _option_direction(entries: list[dict[str, str]],
                      option_id: str | None) -> tuple[str, str | None]:
    if not option_id:
        return "", None
    for entry in entries:
        if entry["id"] == option_id:
            return entry["direction"], entry["label"]
    return "", None


def _select_canonical_chain(chains: list[dict[str, Any]],
                            records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Pick the chain the current question is decided on; never default to [0].

    One chain is unambiguous. With several, the latest named DecisionRecord
    names the live chain; without a record the answer asks for an explicit
    choice instead of projecting whichever chain happens to be first.
    """
    if len(chains) == 1:
        return chains[0], ""
    if records:
        latest = max(
            records,
            key=lambda item: (_version_int(item.get("version")),
                              str(item.get("recorded_at") or "")))
        chain_id = str(latest.get("chain_id") or "")
        for chain in chains:
            if str(chain.get("id") or "") == chain_id:
                return chain, ""
        return None, "最新 DecisionRecord 指向的链 %r 不在 chains 里" % chain_id
    return None, ("存在 %d 条推理链，且没有 DecisionRecord 指定当前问题对应哪一条"
                  % len(chains))


def _version_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_business_decision(study_dir: Path, question: str) -> dict[str, Any]:
    """Project a formal business recommendation from the canonical seven-node chain.

    Lexical evidence matches never enter this projection. A formal recommendation
    requires a named DecisionRecord, a decided chain and audited support; the
    existing DecisionBrief builder owns the actual recommendation semantics.
    """
    reasoning_path = study_dir / "04-findings" / "product-reasoning.json"
    try:
        reasoning = load_json(reasoning_path)
    except (OSError, json.JSONDecodeError):
        reasoning = {}
    chains = reasoning.get("chains") if isinstance(reasoning, dict) else []
    records = reasoning.get("decision_records") if isinstance(reasoning, dict) else []
    chains = [item for item in (chains or []) if isinstance(item, dict)]
    records = [item for item in (records or []) if isinstance(item, dict)
               and str(item.get("decision_maker") or "").strip()]
    base = {
        "kind": "not_ready",
        "status": "needs_decision_record",
        "statement": None,
        "recommended_option_id": None,
        "approved": False,
        "canonical_ref": "04-findings/product-reasoning.json",
        "next_action": "人工完成七节点挂接与审计后：askovo decision record STUDY --chain CHAIN --by OWNER",
    }
    if not chains:
        base["status"] = "needs_canonical_chain"
        base["next_action"] = "先挂接 demand judgment 与七节点链，再记录负责人 DecisionRecord"
        return base
    chain, selection_problem = _select_canonical_chain(chains, records)
    if chain is None:
        base.update(status="needs_chain_selection", reason=selection_problem,
                    chain_candidates=[str(item.get("id") or "") for item in chains],
                    next_action=("明确当前问题对应哪条链，再记录负责人 DecisionRecord："
                                 "askovo decision record %s --chain <CHAIN_ID> --by OWNER"
                                 % study_dir))
        return base
    chain_id = str(chain.get("id") or "")
    matching = [item for item in records if str(item.get("chain_id") or "") == chain_id]
    if not matching:
        base["next_action"] = (
            "词汇匹配只作研究辅助；正式业务决定先执行："
            "askovo decision record %s --chain %s --by OWNER" % (study_dir, chain_id))
        return base
    matching.sort(key=lambda item: _version_int(item.get("version")))
    decision_record = matching[-1]
    try:
        import decision_brief
        brief = decision_brief.build(study_dir, question=question, chain_id=chain_id)
    except Exception as exc:  # noqa: BLE001 正式投影失败时不能退回词汇 go
        base.update(status="projection_failed", reason="%s: %s" % (type(exc).__name__, exc))
        return base
    recommendation = brief.get("recommendation") or {}
    return {
        "kind": str(recommendation.get("kind") or "hold"),
        "status": str(brief.get("decision_status") or "hold"),
        "statement": recommendation.get("statement"),
        "recommended_option_id": brief.get("recommended_option_id"),
        "approved": False,
        "not_approved": True,
        "stale": brief.get("artifact_status") == "stale",
        "source_fingerprint": brief.get("source_fingerprint"),
        "canonical_ref": "04-findings/product-reasoning.json",
        "decision_record": {
            "record_id": decision_record.get("record_id"),
            "version": decision_record.get("version"),
            "decision_maker": decision_record.get("decision_maker"),
        },
        "audit": {
            "supported_chain": bool(recommendation.get("kind") == "recommend"),
            "basis": recommendation.get("ranking_basis"),
        },
        "next_action": brief.get("next_required_action"),
    }


def answer_study(study_dir: Path, question: str | None = None) -> dict[str, Any]:
    """Answer the study's decision question from the evidence store, or refuse.

    Two separate projections share one output:
    - lexical support/counter matches are research assistance only and can at
      most recommend ``continue_research``;
    - a formal go/no-go comes only from the canonical seven-node chain,
      audited support and a named DecisionRecord via ``business_decision``.
    normalized.jsonl is deliberately excluded: only the canonical evidence
    store participates in either projection.
    """
    study_dir = Path(study_dir).resolve()
    study = load_json(study_dir / "study.json")
    if not isinstance(study, dict):
        study = {}
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    question = str(question or decision.get("question") or "").strip()
    option_entries = _decision_option_entries(study)
    options = [entry["label"] for entry in option_entries if entry["label"]]
    # One evidence authority: the same qualified store that audit/deliver use.
    # Reading evidence.jsonl directly let unqualified rows join the lexical
    # counts and let a corrupt file pass as a smaller corpus (A-09).
    integrity = evidence_store_integrity(study_dir)
    store = load_evidence_store(study_dir)
    unique: list[dict[str, Any]] = list(store["records"])

    match_keys = _option_match_keys(options)
    support = [{
        "option": option,
        "match_keys": sorted(keys)[:12],
        "supporting_refs": [],
        "counter_refs": [],
    } for option, keys in zip(options, match_keys)]
    for record in unique:
        text = _evidence_text(record).lower()
        counter = _is_counter_record(record)
        for entry in support:
            if any(key in text for key in entry["match_keys"]):
                (entry["counter_refs"] if counter else entry["supporting_refs"]).append(
                    _answer_ref(record))

    level_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for record in unique:
        level = str(record.get("evidence_level") or "unregistered")
        level_counts[level] = level_counts.get(level, 0) + 1
        family = str(record.get("source_family") or "unknown")
        family_counts[family] = family_counts.get(family, 0) + 1

    minimum_evidence = [str(item) for item in (decision.get("minimum_evidence") or [])]
    answer_status = "unanswerable"
    decision_value = "unanswerable"
    lexical_decision = "unanswerable"
    leading_option: str | None = None
    gaps: list[dict[str, Any]] = []

    if not integrity["valid"]:
        # A corrupt store can hide the record a conclusion depends on. Refuse a
        # trusted answer instead of quietly answering from fewer rows.
        answer_status = "invalid_evidence_store"
        decision_value = lexical_decision = "unanswerable"
        gaps.append({
            "gap": ("02-data/evidence.jsonl 有 %d 行无法解析，拒绝给出可信结论；"
                    "不能把损坏当成语料变少" % len(integrity["problems"])),
            "next_actions": [
                "修复或重导证据行（备份原文件后逐行检查 line 字段）",
                "确认修复后重跑 askovo audit 与 askovo answer",
            ],
            "problems": integrity["problems"][:10],
        })
    elif not unique:
        gaps.append({"gap": "证据库为空：还没有任何经审核登记的证据",
                     "next_actions": [
                         "粘贴文本：askovo import <study> <file> --source-family paste --evidence-level E1",
                         "可见页面：askovo capture page <study> --url … --ack-terms，再 capture accept --by NAME",
                         "截图 OCR：capture page --ocr 后用 capture accept --from ocr"]})
        for item in minimum_evidence:
            gaps.append({"gap": f"决策最低证据要求未满足：{item}", "next_actions": []})
        gates = study.get("quality_gates") if isinstance(study.get("quality_gates"), dict) else {}
        if gates.get("required_corpus_roles"):
            gaps.append({"gap": "必需语料角色尚无记录："
                         + ", ".join(map(str, gates["required_corpus_roles"])),
                         "next_actions": []})
    elif not options:
        gaps.append({"gap": "study.decision.options 为空：没有可比较的选项",
                     "next_actions": ["在 study.json 的 decision.options 里写出至少两个选项"]})
    elif not any(entry["supporting_refs"] or entry["counter_refs"] for entry in support):
        answer_status = "unanswerable"
        gaps.append({"gap": f"证据库有 {len(unique)} 条记录，但没有一条提到任何选项的内容",
                     "next_actions": ["检查选项措辞是否与语料同词，或补充针对性语料"]})
        for item in minimum_evidence:
            gaps.append({"gap": f"决策最低证据要求未满足：{item}", "next_actions": []})
    else:
        ranked = sorted(support, key=lambda entry: (-len(entry["supporting_refs"]),
                                                    entry["option"]))
        top = ranked[0]
        tied = [entry["option"] for entry in ranked
                if len(entry["supporting_refs"]) == len(top["supporting_refs"])]
        leading_option = top["option"]
        if len(tied) > 1:
            answer_status = "inconclusive"
            decision_value = lexical_decision = "continue_research"
            gaps.append({"gap": f"选项并列领先（各 {len(top['supporting_refs'])} 条支持）："
                         + "、".join(tied),
                         "next_actions": ["补充能区分并列选项的证据"]})
        elif top["counter_refs"]:
            answer_status = "contested"
            decision_value = lexical_decision = "continue_research"
            gaps.append({
                "gap": f"领先选项「{leading_option}」存在 {len(top['counter_refs'])} 条反证；"
                       "支持数不能淹没反证，需人工裁决",
                "next_actions": ["人工审核反证记录，或收集能回应反证的新证据"]})
        elif len(top["supporting_refs"]) < ANSWER_MIN_SUPPORT:
            answer_status = "supported_low_n"
            decision_value = lexical_decision = "continue_research"
            gaps.append({
                "gap": f"领先选项「{leading_option}」仅 {len(top['supporting_refs'])} 条支持"
                       f"（低于 {ANSWER_MIN_SUPPORT}）",
                "next_actions": ["继续采集，或接受低样本并人工签注"]})
        else:
            answer_status = "supported"
            lowered = leading_option.lower()
            status_quo = any(marker in lowered or marker in leading_option
                             for marker in _STATUS_QUO_MARKERS)
            decision_value = lexical_decision = "no_go" if status_quo else "go"

    business_decision = _canonical_business_decision(study_dir, question)
    if lexical_decision in ("go", "no_go"):
        # Lexical matches can guide the next research step, never authorize a
        # business go. Without a canonical recommendation the terminal advice
        # is deliberately continue_research, even with 3+ same-source E1 hits.
        decision_value = "continue_research"
        if business_decision.get("kind") != "recommend":
            gaps.append({
                "gap": "词汇命中只是研究辅助，不能直接形成做/不做的业务决定",
                "next_actions": [business_decision.get("next_action")
                                 or "完成七节点、审计与负责人 DecisionRecord"],
            })
    if integrity["valid"] \
            and business_decision.get("kind") == "recommend" \
            and business_decision.get("status") == "ready" \
            and not business_decision.get("stale"):
        # Direction comes from the structured option identity, not from words in
        # the recommendation text ("停止拖延，立即上线试点" must not read as no_go).
        direction, direction_label = _option_direction(
            option_entries, business_decision.get("recommended_option_id"))
        if direction:
            decision_value = direction
        else:
            decision_value = "continue_research"
            gaps.append({
                "gap": ("正式建议指向的选项没有结构化方向：recommended_option_id=%r，"
                        "option=%r；不做文字关键词推断"
                        % (business_decision.get("recommended_option_id"),
                           direction_label)),
                "next_actions": [
                    "在 study.json 的 decision.option_directions 为每个选项写 go / no_go，"
                    "或把 options 改成带 id/label/direction 的对象后重跑 answer",
                ],
            })

    supporting_levels = sorted({
        ref["evidence_level"]
        for entry in support for ref in entry["supporting_refs"]})
    result = {
        "schema": ANSWER_SCHEMA,
        "generated_at": now(),
        "question": question,
        "options": options,
        "answer_status": answer_status,
        "decision": decision_value,
        "leading_option": leading_option,
        "lexical_projection": {
            "answer_status": answer_status,
            "candidate_decision": lexical_decision,
            "leading_option": leading_option,
            "business_decision_allowed": False,
            "note": "选项词命中只用于研究辅助；同源E1、关键词数量或normalized-only记录均不能产生正式go",
        },
        "business_decision": business_decision,
        "support": support,
        "option_directions": {
            entry["id"]: entry["direction"]
            for entry in option_entries if entry["direction"]},
        "evidence_store": {
            "valid": integrity["valid"],
            "qualified_records": len(unique),
            "problems": integrity["problems"][:10],
            "note": "答案与 audit/deliver 共用同一合格证据集；损坏行不静默跳过",
        },
        "evidence_summary": {
            "records": len(unique),
            "by_evidence_level": dict(sorted(level_counts.items())),
            "by_source_family": dict(sorted(family_counts.items())),
            "min_support_for_go": ANSWER_MIN_SUPPORT,
        },
        "supporting_evidence_levels": supporting_levels,
        "gaps": gaps,
        "chain_context": _chain_node_states(study_dir),
        "boundary": (
            "词汇计数只作研究辅助，最多建议继续研究；不证明总体比例、因果或付费意愿。"
            "正式go/no-go只来自七节点+审计支持+负责人DecisionRecord；"
            "反证不被支持数淹没；引用只回链02-data/evidence.jsonl，normalized-only不参与。"
            if unique else
            "无证据时本答案只声明不可回答与缺口，不产生任何结论。"),
        "evidence_file": str(study_dir / "02-data/evidence.jsonl"),
    }
    out_dir = study_dir / "04-findings"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research-answer.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [f"# 研究答案：{question or '（未设置决策问题）'}", ""]
    lines.append(
        f"> 正式业务决策：`{business_decision.get('kind')}` / `{business_decision.get('status')}`；"
        f"当前建议：`{decision_value}`；批准：**否**。"
        f"依据：{business_decision.get('canonical_ref')}。")
    if answer_status in ("unanswerable", "invalid_evidence_store"):
        lines.append("> 词汇辅助：**拒绝给出结论**——"
                     + ("证据文件有无法解析的行，先修复再回答。"
                        if answer_status == "invalid_evidence_store"
                        else "证据库没有可用匹配，缺口如下；不会编造结论。"))
    else:
        label = {"supported": "证据支持", "supported_low_n": "低样本支持",
                 "contested": "存在反证", "inconclusive": "并列未决"}[answer_status]
        lines.append(f"> 词汇辅助：**{label}**；候选：`{lexical_decision}`；"
                     f"领先选项：{leading_option or '—'}（不直接构成业务决定）。")
    lines += ["", "## 各选项证据（回链采集来源）", ""]
    for entry in support:
        lines.append(f"### {entry['option']}")
        lines.append(f"- 支持 {len(entry['supporting_refs'])} 条 / 反证 {len(entry['counter_refs'])} 条")
        for ref in entry["supporting_refs"]:
            back = f"（回链 {ref['record_id']} · {ref['source_family']}"
            back += f" · {ref.get('capture_id')})" if ref.get("capture_id") else "）"
            lines.append(f"- 支持{back}：{ref['excerpt']}")
        for ref in entry["counter_refs"]:
            lines.append(f"- 反证（回链 {ref['record_id']}）：{ref['excerpt']}")
        lines.append("")
    if gaps:
        lines += ["## 缺口与下一步", ""]
        for item in gaps:
            lines.append(f"- {item['gap']}")
            for action in item.get("next_actions") or []:
                lines.append(f"  - {action}")
        lines.append("")
    lines += ["## 边界", "", result["boundary"], "",
              f"- 证据等级分布：{json.dumps(result['evidence_summary']['by_evidence_level'], ensure_ascii=False)}",
              f"- 机器真值：`02-data/evidence.jsonl` 与 `04-findings/product-reasoning.json`；本文件是投影。"]
    (out_dir / "research-answer.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def cli_answer(args: Any) -> int:
    try:
        result = answer_study(Path(args.study_dir),
                              question=str(getattr(args, "question", "") or "").strip() or None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
    platform_filter = getattr(args, "platform", None)
    if platform_filter:
        plan["recommended"] = [item for item in plan["recommended"] if item["id"] == platform_filter]
        plan["blocked"] = [item for item in plan["blocked"] if item["id"] == platform_filter]
        for section in ("runtime_policies", "collection_policies"):
            if isinstance(plan.get(section), dict):
                plan[section] = {
                    key: value for key, value in plan[section].items() if key == platform_filter
                }
        plan["platform_filter"] = platform_filter
        known = sorted(set(platform_index()) | set(field_notes_index()))
        if platform_filter not in known:
            print(
                f"unknown platform: {platform_filter} (known: {', '.join(known)})",
                file=sys.stderr,
            )
            return 2
        if not plan["recommended"] and not plan["blocked"]:
            # A known source can sit outside the top-ranked set; --field-notes,
            # --policies and --json still have a truthful answer for it.
            plan["platform_filter_note"] = (
                f"{platform_filter} is a known source but is not in the current ranked set; "
                "showing its notes/policies only."
            )
        notes = field_notes_for([platform_filter])
    else:
        notes = field_notes_for([item["id"] for item in plan["recommended"]])
    plan["field_notes"] = notes
    strategy_platforms = [platform_filter] if platform_filter else [item["id"] for item in plan["recommended"]]
    plan["strategies"] = strategies_for(strategy_platforms)
    if getattr(args, "policies", False):
        catalog = platform_index()
        declared = set((field_notes_catalog().get("source_types") or {}).keys())
        plan["runtime_policies"] = {
            platform: _cdp_strategy().policy_for(platform).to_dict()
            for platform in strategy_platforms
            if platform in declared or catalog.get(platform, {}).get("cdp")
        }
    if getattr(args, "collection_policies", False):
        catalog = collection_policy_catalog()
        plan["collection_policies"] = {
            platform: collection_policy_for(platform)
            for platform in strategy_platforms
            if platform in catalog
        }
    if getattr(args, "json", False):
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    elif getattr(args, "field_notes", False):
        print(field_notes_markdown(notes=notes, platform=platform_filter))
    elif getattr(args, "strategies", False):
        print(strategies_markdown(plan["strategies"]))
    elif getattr(args, "policies", False):
        print(runtime_policies_markdown(list(plan["runtime_policies"])))
    elif getattr(args, "collection_policies", False):
        print(collection_policies_markdown(list(plan["collection_policies"])))
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
            attach_existing=bool(getattr(args, "attach_existing", False)),
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError, ConnectionError, urllib.error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result.get("status")
    if status in {"terms_required", "cdp_not_allowed"}:
        return 4
    if status in {"collected", "planned"}:
        return 0
    return 3


def cli_analyze(args: Any) -> int:
    try:
        result = analyze_study(Path(args.study_dir), args.question)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if getattr(args, "semantic", False):
        import semantic_candidates
        study_dir = Path(args.study_dir).resolve()
        try:
            records = semantic_candidates.load_records(study_dir)
            summary = semantic_candidates.run_semantic_analysis(
                study_dir, records,
                question=args.question or "",
                provider=getattr(args, "semantic_provider", "auto"),
                allow_external=bool(getattr(args, "allow_external", False)),
                max_records=int(getattr(args, "semantic_max_records", 120)),
                batch_size=int(getattr(args, "semantic_batch_size", 20)),
                retrieval=getattr(args, "retrieval", "auto"),
            )
        except semantic_candidates.SemanticUnavailable as exc:
            print("%s%s" % (exc, ("\n" + exc.suggestion) if exc.suggestion else ""),
                  file=sys.stderr)
            return 2 if exc.reason_code == "EXTERNAL_NOT_AUTHORIZED" else 1
        except (semantic_candidates.SemanticError, OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        result["semantic"] = summary
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if summary.get("status") in ("failed", "partial") else 0
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


def cli_mode(args: Any) -> int:
    try:
        contract = research_entry_contract(
            args.need,
            mode=args.mode,
            stage=args.stage,
            stage_source="explicit" if args.stage else None,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(contract, ensure_ascii=False, indent=2))
    else:
        print(research_mode_markdown(contract))
    return 0


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
        mode = route.get("research_mode") or {}
        if mode:
            print(f"- 研究模式：{mode.get('mode_label', '')}（从{mode.get('entry_label', '')}进入）")
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


def cli_explore(args: Any) -> int:
    study_dir = Path(args.study_dir).resolve()
    study_file = study_dir / "study.json"
    if not study_file.is_file():
        print(f"找不到 study.json: {study_file}", file=sys.stderr)
        return 2
    study = load_json(study_file)
    contract = opportunity_map_contract(study)
    target = study_dir / "04-findings" / "opportunity-map.json"
    markdown = study_dir / "04-findings" / "opportunity-map.md"
    if target.exists() and not getattr(args, "force", False):
        print(f"机会空间地图已存在：{target}；如需覆盖请加 --force", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(opportunity_map_markdown(contract), encoding="utf-8")
    if getattr(args, "json", False):
        print(json.dumps(contract, ensure_ascii=False, indent=2))
    else:
        print(f"已生成机会空间地图：{target}")
        print(f"- 模式：{contract['mode']}；入口：{contract['entry_node']}")
        print(f"- 五层：{', '.join(layer['label'] for layer in contract['layers'].values())}")
        print(f"- 阅读版：{markdown}")
    return 0


def cli_external_research(args: Any) -> int:
    """Run an authorized host adapter and store its output as unverified candidates.

    A-06: the subprocess boundary (env allowlist, signed command registry, bounded
    streams, per-run id, no path escape) lives in :mod:`external_bridge`. Askovo
    never fetches the returned URLs; they stay candidates with no evidence level.
    """
    try:
        record = external_bridge.run(
            Path(str(args.study_dir)),
            str(args.command or ""),
            authorize=bool(getattr(args, "authorize", False)),
            trusted_local=bool(getattr(args, "trusted_local", False)),
            question=str(getattr(args, "question", "") or ""),
            output=str(getattr(args, "output", "") or ""),
            timeout=getattr(args, "timeout", None),
            max_stdout_bytes=getattr(args, "max_stdout_bytes", None),
            max_stderr_bytes=getattr(args, "max_stderr_bytes", None),
        )
    except external_bridge.BridgeError as exc:
        print(json.dumps({
            "status": "refused",
            "reason_code": exc.reason_code,
            "reason": str(exc),
            "suggestion": exc.suggestion or None,
        }, ensure_ascii=False, indent=2))
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": "%s: %s" % (type(exc).__name__, exc)},
                         ensure_ascii=False, indent=2))
        return 2
    if getattr(args, "json", False):
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        for line in external_bridge.summary_lines(record):
            print(line)
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
            evidence_level=getattr(args, "evidence_level", "E1"),
            corpus_role=getattr(args, "corpus_role", "open_scene"),
            context_key=getattr(args, "context_key", ""),
        )
    except ImportReviewError as exc:
        print(json.dumps({"status": "error", "reason": str(exc),
                          "reason_code": exc.reason_code,
                          "suggestion": exc.suggestion}, ensure_ascii=False, indent=2))
        return 1
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
            "validation": {
                "status": "insufficient",
                "mismatch_count": 0,
                "mismatches": [],
            },
            "boundary": (
                "算术投影，不构成商业证明；null 表示未知；来源缺口需补证后重算；"
                "声明值与计算值不一致只报告，不替用户改数"
            ),
        }
        statuses = [str(chain.get("validation_status") or "insufficient") for chain in stats["chains"]]
        mismatches: list[dict[str, Any]] = []
        for chain in stats["chains"]:
            for mismatch in chain.get("mismatches") or []:
                mismatches.append({"chain": chain.get("id"), **mismatch})
        if any(status == "mismatch" for status in statuses):
            result["validation"]["status"] = "mismatch"
        elif any(status == "ok" for status in statuses):
            result["validation"]["status"] = "ok"
        result["validation"]["mismatches"] = mismatches
        result["validation"]["mismatch_count"] = len(mismatches)
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


def _reasoning_file(study_dir: Path) -> Path:
    return Path(study_dir) / "04-findings" / "product-reasoning.json"


def _select_reasoning_chain(reasoning: dict[str, Any], selector: str) -> dict[str, Any]:
    """Resolve a chain by id or 1-based position; never guess near-misses."""
    chains = reasoning.get("chains")
    if not isinstance(chains, list) or not chains:
        raise ValueError("product-reasoning.json 没有 chains；先运行 `askovo chain STUDY` 生成七节点链")
    text = str(selector or "").strip()
    if not text:
        chain = chains[0]
        if not isinstance(chain, dict):
            raise ValueError("chains[1] 不是对象；先修复 04-findings/product-reasoning.json")
        return chain
    for chain in chains:
        if isinstance(chain, dict) and str(chain.get("id") or "") == text:
            return chain
    if text.isdigit() and 1 <= int(text) <= len(chains):
        chain = chains[int(text) - 1]
        if isinstance(chain, dict):
            return chain
    available = "、".join(
        f"{chain.get('id') or '<无 id>'}（序号 {index}）"
        for index, chain in enumerate(chains, start=1)
        if isinstance(chain, dict)
    )
    raise ValueError(f"未找到推理链 {selector!r}；可用：{available}")


def _reasoning_node(chain: dict[str, Any], node_name: str) -> tuple[str, dict[str, Any]]:
    """Return an editable node object; create a hypothesis stub only for a known node name."""
    name = str(node_name or "").strip()
    if name not in REASONING_NODES:
        raise ValueError(f"未知节点 {node_name!r}；可用节点：{', '.join(REASONING_NODES)}")
    nodes = chain.get("nodes")
    if nodes is None:
        nodes = {}
        chain["nodes"] = nodes
    if not isinstance(nodes, dict):
        raise ValueError(f"{chain.get('id') or 'chain'}.nodes 必须是对象；先修复 product-reasoning.json")
    node = nodes.get(name)
    if node is None:
        node = {
            "statement": "",
            "rationale": "",
            "status": "hypothesis",
            "evidence_ids": [],
            "assumptions": [],
        }
        nodes[name] = node
    elif not isinstance(node, dict):
        raise ValueError(f"{chain.get('id') or 'chain'}.nodes.{name} 必须是对象；先修复 product-reasoning.json")
    if not isinstance(node.get("evidence_ids"), list):
        node["evidence_ids"] = []
    return name, node


def _evidence_records_by_id(study_dir: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for record in _read_jsonl_rows(Path(study_dir) / "02-data" / "evidence.jsonl"):
        if record.get("retracted"):
            continue
        record_id = str(record.get("record_id") or "").strip()
        if record_id and record_id not in records:
            records[record_id] = record
    return records


def _next_change_log_id(changes: list[Any]) -> str:
    used = {str(entry.get("id")) for entry in changes if isinstance(entry, dict)}
    index = len(changes) + 1
    while f"CHG{index:02d}" in used:
        index += 1
    return f"CHG{index:02d}"


def _save_product_reasoning(study_dir: Path, reasoning: dict[str, Any]) -> Path:
    path = _reasoning_file(study_dir)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(reasoning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return path


def _append_chain_change(
    chain: dict[str, Any],
    chain_id: str,
    node_name: str,
    changed_fields: list[str],
    previous: dict[str, Any],
    reason_evidence_ids: Iterable[str],
    note: str,
) -> dict[str, Any]:
    changes = chain.get("change_log")
    if changes is None:
        changes = []
        chain["change_log"] = changes
    if not isinstance(changes, list):
        raise ValueError(f"{chain_id}.change_log 必须是数组；先修复 product-reasoning.json")
    entry = {
        "id": _next_change_log_id(changes),
        "base_version": f"chain-v{len(changes)}",
        "new_version": f"chain-v{len(changes) + 1}",
        "reason_evidence_ids": sorted({str(value).strip() for value in reason_evidence_ids if str(value).strip()}),
        "affected_refs": [f"{chain_id}.{node_name}"],
        "impact": f"编辑 {node_name}：{', '.join(changed_fields)}",
        "decision": note,
        "owner": "askovo chain-node",
        "decided_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "projection_sync": "pending",
        "previous": previous,
    }
    changes.append(entry)
    return entry


def _chain_node_payload(
    study_dir: Path,
    chain: dict[str, Any],
    node_name: str,
    node: dict[str, Any],
    *,
    status: str,
    changed_fields: list[str],
    previous: dict[str, Any],
    entry: dict[str, Any] | None,
    message: str,
) -> dict[str, Any]:
    chain_id = str(chain.get("id") or "").strip()
    records = _evidence_records_by_id(study_dir)
    evidence_ids = [str(value) for value in node.get("evidence_ids") or [] if str(value).strip()]
    levels = {
        value: str(records[value].get("evidence_level") or "")
        for value in evidence_ids if value in records
    }
    if status == "updated":
        next_step = (
            f"运行 `askovo check {study_dir} --stage full` 重新审计（本次改动涉及 {chain_id}.{node_name}）；"
            "审计通过后再重跑 `askovo deliver STUDY --kind ...` 同步交付物。"
            "本次编辑只改机器真值，不是审计通过，也不代表证据已复核。"
        )
    elif status == "unchanged":
        next_step = "文件未变化，无需重跑 check/deliver；要查看当前审计状态可运行 `askovo check STUDY --stage full`。"
    else:
        next_step = f"只读操作，未写文件；如需查看审计状态，运行 `askovo check {study_dir} --stage full`。"
    result = {
        "status": status,
        "chain": chain_id,
        "chain_status": chain.get("status"),
        "node": node_name,
        "node_status": node.get("status"),
        "changed_fields": changed_fields,
        "previous": previous,
        "evidence_ids": evidence_ids,
        "evidence_levels": levels,
        "change_log_id": entry.get("id") if entry else None,
        "affected_refs": list(entry.get("affected_refs") or []) if entry else [],
        "chain_file": str(_reasoning_file(study_dir)),
        "audit_status": "not_run",
        "message": message,
        "next_step": next_step,
    }
    return result


CHAIN_NODE_FIELD_TYPES = {
    "current_substitute": str, "friction_cost": str, "consequence": str,
    "desired_outcome": str, "measure": str, "capability": str, "form": str, "scope": str,
    "assumptions": list, "constraints": list, "alternatives_considered": list,
    "acceptance_conditions": list, "non_goals": list, "acceptance_criteria": list,
    "market_definition": str, "geographies": list, "time_window": str,
    "included_markets": list, "excluded_markets": list, "target_segment": str,
    "segments": list, "payer": str, "positioning": str,
    "competitive_alternatives": list, "pricing_hypothesis": dict,
    "cost_drivers": list, "success_metrics": list, "revenue_model": dict,
    "gate": dict, "resource_commitment": str, "revisit_trigger": str,
}

CHAIN_FIELD_TYPES = {
    "title": str, "context_key": str, "demand_judgment_id": str,
    "next_test": dict, "counter_evidence_ids": list, "gaps": list,
    "alternative_explanations": list, "human_review": dict,
}


def cli_chain_node(args: Any) -> int:
    """Edit one node of the canonical chain; writes truth + change_log, never audits."""
    try:
        study_dir = Path(args.study_dir).resolve()
        reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            raise ValueError(
                "找不到 04-findings/product-reasoning.json；先运行 `askovo chain STUDY` 生成七节点链"
            )
        chain = _select_reasoning_chain(reasoning, getattr(args, "chain", ""))
        action = str(getattr(args, "chain_node_action", "") or "")
        node_name = str(getattr(args, "node", "") or "").strip()
        if action == "show":
            if node_name:
                name, node = _reasoning_node(chain, node_name)
                result = _chain_node_payload(
                    study_dir, chain, name, node,
                    status="shown", changed_fields=[], previous={}, entry=None,
                    message="只读查看；未写文件，也未运行审计。",
                )
                result["node_payload"] = node
            else:
                nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
                result = {
                    "status": "shown",
                    "chain": str(chain.get("id") or ""),
                    "chain_status": chain.get("status"),
                    "chain_title": chain.get("title"),
                    "nodes": {
                        name: (nodes.get(name) if isinstance(nodes.get(name), dict) else None)
                        for name in REASONING_NODES
                    },
                    "chain_file": str(_reasoning_file(study_dir)),
                    "audit_status": "not_run",
                    "message": "只读查看；未写文件，也未运行审计。",
                    "next_step": f"运行 `askovo check {study_dir} --stage full` 查看当前证据与门禁状态。",
                }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        chain_id = str(chain.get("id") or "").strip()
        if not chain_id:
            raise ValueError("该链缺少 id；change_log.affected_refs 需要 CHAIN.node，先补 id 再编辑")
        if not node_name:
            raise ValueError("该动作需要 --node；可用节点：" + ", ".join(REASONING_NODES))
        name, node = _reasoning_node(chain, node_name)

        if action == "set":
            updates: dict[str, str] = {}
            for field_name in ("statement", "rationale", "status"):
                raw = getattr(args, field_name, None)
                if raw is None:
                    continue
                value = str(raw).strip()
                if field_name == "status":
                    if value not in CHAIN_NODE_STATUSES:
                        raise ValueError(
                            f"未知节点状态 {value!r}；可用：{', '.join(CHAIN_NODE_STATUSES)}"
                        )
                elif not value:
                    raise ValueError(
                        f"--{field_name} 不能为空；若该节点不再适用，请用 --status deprioritized 并说明原因"
                    )
                updates[field_name] = value
            field_name = str(getattr(args, "field", "") or "").strip()
            raw_json = getattr(args, "value_json", None)
            if field_name:
                if field_name not in CHAIN_NODE_FIELD_TYPES:
                    raise ValueError("不支持的字段 %r；可用：%s" % (
                        field_name, ", ".join(sorted(CHAIN_NODE_FIELD_TYPES))))
                if raw_json is None:
                    raise ValueError("--field 需要同时提供 --value-json")
                try:
                    typed_value = json.loads(raw_json)
                except json.JSONDecodeError as exc:
                    raise ValueError("--value-json 必须是有效 JSON：%s" % exc) from exc
                expected = CHAIN_NODE_FIELD_TYPES[field_name]
                if not isinstance(typed_value, expected) or (
                        expected is str and not typed_value.strip()):
                    raise ValueError("--field %s 需要%s" % (
                        field_name, "非空字符串" if expected is str else "JSON 数组"))
                updates[field_name] = typed_value
            elif raw_json is not None:
                raise ValueError("--value-json 只能与 --field 一起使用")
            if not updates:
                raise ValueError("set 至少需要字段值、--statement、--rationale 或 --status 之一")
            previous: dict[str, Any] = {}
            changed: list[str] = []
            for field_name, value in updates.items():
                old = node.get(field_name)
                if old != value:
                    previous[field_name] = old
                    node[field_name] = value
                    changed.append(field_name)
            if not changed:
                result = _chain_node_payload(
                    study_dir, chain, name, node,
                    status="unchanged", changed_fields=[], previous={}, entry=None,
                    message="写入值与当前值相同；未写文件，未追加 change_log。",
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            entry = _append_chain_change(
                chain, chain_id, name, changed, previous, [],
                str(getattr(args, "note", "") or "").strip()
                or "人工更新节点字段；未重新审计，不作为审计通过",
            )
            _save_product_reasoning(study_dir, reasoning)
            result = _chain_node_payload(
                study_dir, chain, name, node,
                status="updated", changed_fields=changed, previous=previous, entry=entry,
                message=f"已写入 {chain_id}.{name}；旧值保存在 change_log[{entry['id']}].previous。",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        evidence_ids = [
            str(value).strip()
            for value in (getattr(args, "evidence", None) or [])
            if str(value).strip()
        ]
        if not evidence_ids:
            raise ValueError("该动作需要至少一个 --evidence 证据 ID")
        bound = [str(value) for value in node.get("evidence_ids") or [] if str(value).strip()]
        if action == "bind-evidence":
            records = _evidence_records_by_id(study_dir)
            unknown = [value for value in evidence_ids if value not in records]
            if unknown:
                raise ValueError(
                    "证据库没有这些 ID：" + ", ".join(unknown)
                    + "；核对 02-data/evidence.jsonl，或先运行 `askovo import STUDY FILE`"
                )
            added = [value for value in dict.fromkeys(evidence_ids) if value not in bound]
            if not added:
                result = _chain_node_payload(
                    study_dir, chain, name, node,
                    status="unchanged", changed_fields=[], previous={}, entry=None,
                    message="这些证据已全部绑定在该节点；未写文件，未追加 change_log。",
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            node["evidence_ids"] = bound + added
            entry = _append_chain_change(
                chain, chain_id, name, ["evidence_ids"], {"evidence_ids": bound}, added,
                str(getattr(args, "note", "") or "").strip()
                or "人工绑定证据；证据是否属于该节点可接受的判断类仍由 check 判定",
            )
            _save_product_reasoning(study_dir, reasoning)
            result = _chain_node_payload(
                study_dir, chain, name, node,
                status="updated", changed_fields=["evidence_ids"],
                previous={"evidence_ids": bound}, entry=entry,
                message=f"已把 {', '.join(added)} 绑定到 {chain_id}.{name}；是否可被该节点引用由 check 判定。",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if action == "unbind-evidence":
            missing = [value for value in dict.fromkeys(evidence_ids) if value not in bound]
            if missing:
                raise ValueError(
                    "这些证据未绑定到 " + f"{chain_id}.{name}：" + ", ".join(missing)
                    + "；用 `askovo chain-node STUDY show --node " + name + "` 查看当前绑定"
                )
            remove = set(evidence_ids)
            node["evidence_ids"] = [value for value in bound if value not in remove]
            entry = _append_chain_change(
                chain, chain_id, name, ["evidence_ids"], {"evidence_ids": bound}, evidence_ids,
                str(getattr(args, "note", "") or "").strip()
                or "人工解绑证据；check 的证据覆盖与结论门禁会随之变化",
            )
            _save_product_reasoning(study_dir, reasoning)
            result = _chain_node_payload(
                study_dir, chain, name, node,
                status="updated", changed_fields=["evidence_ids"],
                previous={"evidence_ids": bound}, entry=entry,
                message=f"已从 {chain_id}.{name} 解绑 {', '.join(evidence_ids)}。",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        raise ValueError(
            "未知动作；可用动作：show、set、bind-evidence、unbind-evidence"
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _typed_json_value(args: Any, field_types: dict[str, Any], field_name: str) -> Any:
    if field_name not in field_types:
        raise ValueError("不支持的字段 %r；可用：%s" % (field_name, ", ".join(sorted(field_types))))
    raw = getattr(args, "value_json", None)
    if raw is None:
        raise ValueError("--field 需要同时提供 --value-json")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("--value-json 必须是有效 JSON：%s" % exc) from exc
    expected = field_types[field_name]
    if not isinstance(value, expected) or (expected is str and not value.strip()):
        label = "非空字符串" if expected is str else ("JSON 对象" if expected is dict else "JSON 数组")
        raise ValueError("--field %s 需要%s" % (field_name, label))
    return value


def _write_json_document(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _cli_chain_set(study_dir: Path, args: Any, reasoning: dict[str, Any]) -> int:
    chain = _select_reasoning_chain(reasoning, getattr(args, "chain", ""))
    field_name = str(getattr(args, "field", "") or "").strip()
    if not field_name:
        raise ValueError("chain set 需要 --field；可用：" + ", ".join(sorted(CHAIN_FIELD_TYPES)))
    value = _typed_json_value(args, CHAIN_FIELD_TYPES, field_name)
    old = chain.get(field_name)
    if old == value:
        print(json.dumps({"status": "unchanged", "chain": chain.get("id"), "field": field_name}, ensure_ascii=False, indent=2))
        return 0
    chain[field_name] = value
    note = str(getattr(args, "note", "") or "更新链级字段；未重新审计")
    entry = _append_chain_change(chain, str(chain.get("id") or ""), "chain", [field_name], {field_name: old}, [], note)
    entry["affected_refs"] = [f"{chain.get('id')}.{name}" for name in REASONING_NODES]
    _save_product_reasoning(study_dir, reasoning)
    print(json.dumps({"status": "updated", "chain": chain.get("id"), "field": field_name, "previous": old, "change_log_id": entry["id"], "affected_refs": entry["affected_refs"], "audit_status": "not_run"}, ensure_ascii=False, indent=2))
    return 0


def cli_demand_judgment(args: Any) -> int:
    try:
        study_dir = Path(args.study_dir).resolve()
        if getattr(args, "judgment_action", "") != "create":
            raise ValueError("可用动作：create")
        path = study_dir / "04-findings" / "demand-judgments.json"
        judgments = load_json(path) if path.is_file() else []
        if not isinstance(judgments, list):
            raise ValueError("demand-judgments.json 必须是数组")
        judgment_id = str(args.id).strip()
        if not judgment_id:
            raise ValueError("--id 不能为空")
        if any(str(row.get("id") or "") == judgment_id for row in judgments if isinstance(row, dict)):
            raise ValueError(f"需求判断 {judgment_id} 已存在；请使用新 id 或先修正现有记录")
        records = _evidence_records_by_id(study_dir)
        evidence_groups = {}
        for argument, field in (("problem_evidence", "problem_evidence_ids"), ("solution_evidence", "solution_evidence_ids"), ("commercial_evidence", "commercial_evidence_ids"), ("counter_evidence", "counter_evidence_ids")):
            values = [str(value).strip() for value in (getattr(args, argument, None) or []) if str(value).strip()]
            unknown = [value for value in values if value not in records]
            if unknown:
                raise ValueError(f"{field} 引用了不存在的证据 ID：{', '.join(unknown)}")
            evidence_groups[field] = values
        created = {
            "id": judgment_id,
            "title": str(args.title).strip(),
            "user_role": str(args.user_role).strip(),
            "scene": str(args.scene).strip(),
            "task": str(args.task).strip(),
            "current_substitute": str(args.current_substitute).strip(),
            "friction": str(args.friction).strip(),
            "consequence": str(args.consequence).strip(),
            "solution": str(args.solution).strip(),
            "acceptance_conditions": str(args.acceptance_conditions).strip(),
            **evidence_groups,
            "status": "needs-validation",
            "confidence": "low",
            "gaps": [],
            "next_test": str(args.next_test).strip(),
            "context_key": str(getattr(args, "context_key", "") or "").strip(),
        }
        required_text = ("title", "user_role", "scene", "task", "current_substitute", "friction", "consequence", "solution", "acceptance_conditions", "next_test")
        missing = [name for name in required_text if not created[name]]
        if missing:
            raise ValueError("需求判断缺字段：" + ", ".join(missing))
        judgments.append(created)
        _write_json_document(path, judgments)
        print(json.dumps({"status": "created", "judgment": created, "audit_status": "not_run", "next_step": f"运行 `askovo check {study_dir} --stage full` 重新审计"}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cli_evidence(args: Any) -> int:
    try:
        study_dir = Path(args.study_dir).resolve()
        if getattr(args, "evidence_action", "") in {"retract", "restore"}:
            record_id = str(args.record_id).strip()
            path = study_dir / "02-data" / "evidence.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            record = next((row for row in rows if str(row.get("record_id") or "") == record_id), None)
            if record is None:
                raise ValueError(f"证据 {record_id} 不存在；请先运行 `askovo import STUDY FILE`")
            actor = str(getattr(args, "by", "") or "").strip()
            if not actor:
                raise ValueError("撤销/恢复证据必须提供 --by，记录责任人")
            action = args.evidence_action
            if action == "retract":
                reason = str(getattr(args, "reason", "") or "").strip()
                if not reason:
                    raise ValueError("撤销证据必须提供 --reason，说明误导入或不再采用的原因")
                if record.get("retracted"):
                    raise ValueError(f"证据 {record_id} 已撤销；如需恢复请先运行 restore")
                record["retracted"] = True
                record["retraction"] = {"at": now(), "by": actor, "reason": reason}
            else:
                if not record.get("retracted"):
                    raise ValueError(f"证据 {record_id} 未撤销，无需恢复")
                record.pop("retracted", None)
                record["restoration"] = {"at": now(), "by": actor}
            temp = path.with_name(path.name + ".tmp")
            try:
                temp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
                os.replace(temp, path)
            finally:
                if temp.exists():
                    temp.unlink()
            print(json.dumps({"status": "retracted" if action == "retract" else "restored",
                              "record_id": record_id, "text_unchanged": True,
                              "audit_status": "not_run"}, ensure_ascii=False, indent=2))
            return 0
        if getattr(args, "evidence_action", "") != "set":
            raise ValueError("可用动作：set / retract / restore")
        record_id = str(args.record_id).strip()
        path = study_dir / "02-data" / "evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        record = next((row for row in rows if str(row.get("record_id") or "") == record_id), None)
        if record is None:
            raise ValueError(f"证据 {record_id} 不存在；请先运行 `askovo import STUDY FILE`")
        field_name = str(getattr(args, "field", "") or "").strip()
        if field_name != "evidence_form":
            raise ValueError("evidence set 目前只支持 --field evidence_form，避免用命令直接改写证据等级")
        form = _typed_json_value(args, {"evidence_form": str}, "evidence_form")
        level = str(getattr(args, "evidence_level", "") or "").strip().upper()
        if level not in IMPORT_LEVEL_ORDER:
            raise ValueError(f"未知证据等级 {level!r}")
        cap = IMPORT_LEVEL_CAPS.get(form, "E2")
        concept_path = getattr(args, "concept_test", "")
        if IMPORT_LEVEL_ORDER[level] > IMPORT_LEVEL_ORDER[cap]:
            if level != "E3" or not concept_path:
                raise ValueError(f"{form} 最高支持 {cap}；E3 还需同时提供 --concept-test")
            import capture_review
            capture_review._load_concept_test(Path(concept_path))
        previous = {"evidence_form": record.get("evidence_form"), "evidence_level": record.get("evidence_level")}
        record["evidence_form"] = form
        record["evidence_level"] = level
        record["evidence_correction"] = {
            "note": str(getattr(args, "note", "") or "纠正导入默认值"),
            "concept_test": str(concept_path or ""),
        }
        temp = path.with_name(path.name + ".tmp")
        try:
            temp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
        print(json.dumps({"status": "updated", "record_id": record_id, "previous": previous, "current": {"evidence_form": form, "evidence_level": level}, "audit_status": "not_run"}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cli_study(args: Any) -> int:
    try:
        study_dir = Path(args.study_dir).resolve()
        if getattr(args, "study_action", "") != "set":
            raise ValueError("可用动作：set")
        path = study_dir / "study.json"
        study = load_json(path)
        field_name = str(getattr(args, "field", "") or "").strip()
        fields = {
            "title": str,
            "decision.question": str, "decision.owner": str, "decision.deadline": str,
            "decision.options": list, "decision.minimum_evidence": list,
            "scope.target_users": list, "scope.markets": list, "scope.languages": list,
            "scope.allowed_sources": list, "scope.source_time_window": dict,
            "hypotheses": list, "stopping_rules": list, "restart_rules": list,
        }
        value = _typed_json_value(args, fields, field_name)
        target = study
        parts = field_name.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
            if not isinstance(target, dict):
                raise ValueError(f"{part} 不是对象，无法写入 {field_name}")
        key = parts[-1]
        previous = target.get(key)
        if previous == value:
            print(json.dumps({"status": "unchanged", "field": field_name}, ensure_ascii=False, indent=2))
            return 0
        target[key] = value
        _write_json_document(path, study)
        print(json.dumps({"status": "updated", "field": field_name, "previous": previous, "audit_status": "not_run", "next_step": f"运行 `askovo check {study_dir} --stage full` 重新审计"}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cli_chain(args: Any) -> int:
    try:
        study_dir = Path(args.study_dir).resolve()
        reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            scaffold_product_reasoning(study_dir)
            reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            raise ValueError("cannot create product-reasoning.json")
        if getattr(args, "chain_action", "") == "set":
            return _cli_chain_set(study_dir, args, reasoning)
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
            "next_step": (
                "用 `askovo chain-node STUDY show` 查看节点，用 `askovo chain-node STUDY set --node NODE "
                "--statement ... --status ...` 写 statement/rationale/status，用 `bind-evidence` 绑定证据；"
                "改完运行 `askovo check STUDY --stage design 或 --stage full`"
            ),
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


CONTEXT_SCHEMA = "askovo.research-context/1"
CONTEXT_CLAIM_STATUSES = ("evidence_supported", "hypothesis", "insufficient_evidence")


def _context_file_component(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", str(text or "").strip(), flags=re.UNICODE).strip("-")
    return cleaned[:80] or fallback


def _write_new_text_file(path: Path, text: str) -> None:
    """Exclusive create: a context version is immutable once written."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _context_claim(
    chain: dict[str, Any],
    node_name: str,
    node: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Map one chain node to a Growovo-verifiable claim; never upgrades status."""
    chain_id = str(chain.get("id") or "").strip() or "chain"
    statement = str(node.get("statement") or "").strip()
    if len(statement) < 8:
        statement = (
            f"{node_name} 节点：{statement}"
            if statement
            else f"{node_name} 节点尚未填写 statement（待补充）"
        )
    node_status = str(node.get("status") or "").strip()
    evidence_ids = [
        str(value).strip() for value in node.get("evidence_ids") or [] if str(value).strip()
    ]
    refs: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for evidence_id in evidence_ids:
        record = records.get(evidence_id)
        if record is None:
            unresolved.append(evidence_id)
            refs.append({
                "evidence_id": evidence_id,
                "source": f"02-data/evidence.jsonl#{evidence_id}",
                "resolved": False,
            })
            continue
        source = str(record.get("source_ref") or "").strip() or f"02-data/evidence.jsonl#{evidence_id}"
        ref: dict[str, Any] = {"evidence_id": evidence_id, "source": source, "resolved": True}
        level = str(record.get("evidence_level") or "").strip()
        if level:
            ref["evidence_level"] = level
        refs.append(ref)
    note = ""
    if node_status == "validated" and refs and not unresolved:
        status = "evidence_supported"
    elif node_status == "hypothesis":
        status = "hypothesis"
    else:
        status = "insufficient_evidence"
        if node_status == "validated":
            note = "节点标记为 validated，但缺少可用证据或证据未在 evidence.jsonl 中登记；导出时降级为 insufficient_evidence"
        elif node_status in ("rejected", "deprioritized"):
            note = f"节点状态 {node_status} 表示该判断未成立或已降权；下游不得当作已验证事实"
        elif node_status and node_status != "insufficient_evidence":
            note = f"节点状态 {node_status}，尚无足够证据支持；下游只能当作待验证前提"
    claim: dict[str, Any] = {
        "claim_id": f"{chain_id}:{node_name}",
        "statement": statement,
        "status": status,
        "node_status": node_status or "unknown",
        "chain_id": chain_id,
        "node": node_name,
        "evidence_refs": refs,
    }
    chain_context_key = str(chain.get("context_key") or "").strip()
    if chain_context_key:
        claim["context_key"] = chain_context_key
    if status == "hypothesis":
        claim["assumption"] = True
    if unresolved:
        claim["unresolved_evidence_ids"] = unresolved
    if status == "insufficient_evidence" and not refs:
        claim["evidence_refs"] = [{
            "evidence_id": f"reasoning-record:{chain_id}/{node_name}",
            "source": f"04-findings/product-reasoning.json#chains/{chain_id}/nodes/{node_name}",
            "basis": "status_record_only",
        }]
        note = (
            (note + "；" if note else "")
            + "没有任何外部证据引用；这里只引用 status 记录本身，不代表外部研究证据"
        )
    if note:
        claim["note"] = note
    return claim


def cli_context_export(args: Any) -> int:
    """Export a Growovo-verifiable research context: payload file + sha256 envelope."""
    try:
        study_dir = Path(args.study_dir).resolve()
        reasoning = load_product_reasoning(study_dir)
        if reasoning is None:
            raise ValueError(
                "找不到 04-findings/product-reasoning.json；先运行 `askovo chain STUDY` 生成七节点链"
            )
        chains = reasoning.get("chains")
        if not isinstance(chains, list) or not chains:
            raise ValueError("product-reasoning.json 没有 chains；先运行 `askovo chain STUDY` 生成七节点链")
        selector = str(getattr(args, "chain", "") or "").strip()
        selected = (
            [_select_reasoning_chain(reasoning, selector)]
            if selector
            else [chain for chain in chains if isinstance(chain, dict)]
        )
        if not selected:
            raise ValueError("没有可导出的 chain；先修复 04-findings/product-reasoning.json")
        approved_by = str(getattr(args, "approved_by", "") or "").strip()
        if not approved_by:
            raise ValueError("--approved-by 必填：导出上下文等于批准把研究前提交给下游产品")
        value_events = [
            str(value).strip()
            for value in (getattr(args, "value_event", None) or [])
            if str(value).strip()
        ]
        if not value_events:
            raise ValueError(
                "--value-event 至少一个：下游需要知道什么算价值事件，Askovo 不替下游发明口径"
            )
        records = _evidence_records_by_id(study_dir)
        claims: list[dict[str, Any]] = []
        non_goals: list[str] = []
        for chain in selected:
            nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
            for node_name in REASONING_NODES:
                node = nodes.get(node_name)
                if not isinstance(node, dict):
                    continue
                claims.append(_context_claim(chain, node_name, node, records))
                if node_name in ("product", "business"):
                    for value in node.get("non_goals") or []:
                        text = str(value).strip()
                        if text and text not in non_goals:
                            non_goals.append(text)
        for value in getattr(args, "non_goal", None) or []:
            text = str(value).strip()
            if text and text not in non_goals:
                non_goals.append(text)
        if not non_goals:
            raise ValueError(
                "--non-goal 至少一个：product/business 节点没有 non_goals，导出必须写明这次研究不做什么"
            )
        study_file = study_dir / "study.json"
        study = load_json(study_file) if study_file.is_file() else {}
        study_id = str((study or {}).get("study_id") or "").strip() if isinstance(study, dict) else ""
        context_id = str(getattr(args, "context_id", "") or "").strip()
        if not context_id:
            base = (
                study_id
                or str(selected[0].get("context_key") or "").strip()
                or study_dir.name
            )
            context_id = f"askovo-{base}"
        reasoning_path = _reasoning_file(study_dir)
        reasoning_sha = hashlib.sha256(reasoning_path.read_bytes()).hexdigest()
        version = str(getattr(args, "version", "") or "").strip() or f"reasoning-{reasoning_sha[:12]}"
        scope: dict[str, str] = {}
        market = str(getattr(args, "market", "") or "").strip()
        if market:
            scope["market"] = market
        time_window = str(getattr(args, "time_window", "") or "").strip()
        if time_window:
            scope["time_window"] = time_window
        chain_ids = [str(chain.get("id") or "").strip() for chain in selected]
        payload: dict[str, Any] = {
            "schema": CONTEXT_SCHEMA,
            "context_id": context_id,
            "version": version,
            "approved_by": approved_by,
            "subject_id": study_id or context_id,
            "claims": claims,
            "value_event_definitions": value_events,
            "non_goals": non_goals,
            "provenance_refs": sorted({
                str(ref.get("evidence_id") or "")
                for claim in claims
                for ref in claim.get("evidence_refs") or []
                if ref.get("evidence_id")
            }),
            "provenance": {
                "reasoning_file": "04-findings/product-reasoning.json",
                "reasoning_sha256": reasoning_sha,
                "chain_ids": chain_ids,
            },
        }
        if scope:
            payload["scope"] = scope
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        out_dir = Path(getattr(args, "out", "") or "").resolve()
        stem = (
            "askovo-context-"
            + _context_file_component(context_id, "context")
            + "-"
            + _context_file_component(version, "version")
        )
        payload_path = out_dir / f"{stem}.payload.json"
        envelope_path = out_dir / f"{stem}.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Two files keep the hash honest: the payload carries no self-reference,
        # and the envelope binds the payload bytes downstream can re-verify.
        _write_new_text_file(payload_path, payload_text)
        envelope = dict(payload)
        envelope["source"] = {"kind": "askovo", "ref": str(payload_path)}
        envelope["content_sha256"] = digest
        try:
            _write_new_text_file(
                envelope_path,
                json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        except FileExistsError:
            payload_path.unlink()
            raise
        counts = {status: 0 for status in CONTEXT_CLAIM_STATUSES}
        for claim in claims:
            counts[claim["status"]] += 1
        result = {
            "status": "exported",
            "context_id": context_id,
            "version": version,
            "payload_file": str(payload_path),
            "envelope_file": str(envelope_path),
            "content_sha256": digest,
            "reasoning_sha256": reasoning_sha,
            "chains": chain_ids,
            "claims": {"total": len(claims), **counts},
            "value_event_definitions": value_events,
            "non_goals": len(non_goals),
            "growovo_import": f"mkt context import --file {envelope_path} --by <operator>",
            "next_step": (
                "把 envelope_file 交给 Growovo：`mkt context import --file <envelope> --by <operator>`；"
                "Growovo 会重算 payload 文件的 sha256 与 content_sha256 比对。"
                "payload 文件必须与 envelope 一起保留在原路径。"
                "本导出只传递研究前提与证据引用：hypothesis 不会被升级为已验证事实。"
            ),
        }
    except FileExistsError as exc:
        print(
            f"导出文件已存在，不会覆盖：{exc.filename}；"
            "如需重新导出，请换一个 --version 或 --out 目录。",
            file=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_deliver(args: Any) -> int:
    try:
        result = deliver(Path(args.study_dir), args.kind, baseline=getattr(args, "baseline", None))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = delivery_error(Path(args.study_dir), args.kind, exc)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "blocked" else 0


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

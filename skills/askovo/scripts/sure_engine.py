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
import os
import socket
import struct
import json
import re
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
from typing import Any, Iterable

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
    ("road_test", ("开放道路", "实车路测", "上路测试", "道路试验", "on-road")),
    ("food_ingest", ("试吃", "试喝", "摄入", "食用测试", "吃下去")),
    ("skin_contact", ("皮肤接触", "涂抹", "上脸", "斑贴")),
    ("minors", ("儿童", "未成年", "小学生", "幼儿")),
    ("sensitive_data", ("健康数据", "生物特征", "位置轨迹", "家庭影像", "医疗记录")),
    ("destructive_test", ("跌落测试", "破坏性", "拆解测试", "针刺")),
    ("production_logs", ("生产日志", "全量日志", "用户遥测", "生产环境数据")),
    ("home_recording", ("入户录像", "家庭录像", "家中拍摄")),
    ("bystander_recording", ("路人拍摄", "旁观者录像", "公共场所录像")),
    ("electrical_thermal", ("电池测试", "高温测试", "充电异常", "市电测试", "热失控")),
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
        next_commands.append(f'askovo platforms "{text}" --domain {domain_info["domain"]} --bulk')
    elif intent_name == "collect":
        next_commands.append(f'askovo platforms "{text}" --domain {domain_info["domain"]} --bulk')
        next_commands.append(f'askovo collect <study> --platform github --query "<query>" --limit 100')
    elif intent_name == "analyze":
        next_commands.append('askovo analyze <study> --question "<研究问题>"')
    else:
        next_commands.append(f'askovo do "{text}" --domain {domain_info["domain"]} --stage {stage_key} --study {slug}')
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
        return "# askovo 路由\n\n需要先确认产品类型：\n\n" + "\n".join(
            f"- `{item['domain']}` — {item['label']}" for item in route["domain_options"]
        ) + "\n"
    lines = [
        "# askovo 路由结果",
        "",
        f"- 原始需求：{route['query']}",
        f"- 产品类型：**{route['domain_label']}**（`{route['domain']}`，置信度 {route['confidence']}）",
        f"- 阶段：**{route['stage_label']}**（`{route['stage']}`）",
        f"- 意图：`{route['intent']}`",
        f"- 安全门：`{route['safety_gate']}`",
        "",
        "## 推荐方法",
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


def _map_evidence_forms(forms: Iterable[str]) -> str:
    mapping = {
        "self_report": "interview_or_survey",
        "observation": "field_observation",
        "product_interaction": "prototype_session",
        "experiment": "experiment",
        "instrument_log": "telemetry_log",
        "lab_report": "lab_report",
        "transaction": "transaction",
        "support_record": "support_ticket",
    }
    values = [mapping.get(form, form) for form in forms]
    return ",".join(dict.fromkeys(values)) or "mixed"


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

    forms: set[str] = set()
    for item in selected:
        forms.update(item.get("evidence_forms", []))
    rows = [
        ["direct_solution", _map_evidence_forms(forms), "直接使用/接受目标方案的人", "待设计", "planned", "自选择/活跃用户偏差"],
        ["open_scene", "field_observation", "在开放场景描述问题的人", "待设计", "planned", "场景覆盖偏差"],
        ["substitute_rejector", "interview_or_survey", "用过替代方案后拒绝/放弃的人", "待设计", "planned", "难触达/回忆偏差"],
        ["post_purchase_support", "support_ticket", "购买后遇到问题的人", "待设计", "planned", "沉默用户缺失"],
        ["control", "interview_or_survey", "背景对照人群", "待设计", "planned", "相关性低"],
    ]
    with (study_dir / "01-sources" / "source-plan.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["corpus_role", "source_family", "route_or_query", "target_records", "access_status", "known_bias"])
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

## 下一步

```bash
askovo instruments .
askovo import . <材料文件> --source-family interview
askovo deliver . --kind memo
```

先补全 `study.json` 的决策、假设、证伪条件、样本理由与停止规则，再开始执行。
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
        "## 2. 产品与研究阶段",
        "",
        f"- 产品类型：{route['domain_label']} (`{route['domain']}`)",
        f"- 阶段：{route['stage_label']} (`{route['stage']}`)",
        f"- 方法：{', '.join(item['name'] for item in route['recommended_methods'])}",
        "",
        "## 3. 假设与证伪",
        "",
        "- H1：待确认",
        "- 证伪条件：待确认",
        "",
        "## 4. 证据计划",
        "",
    ]
    for item in route["recommended_methods"]:
        lines.append(
            f"- **{item['name']}**：{ '；'.join(item['answers']) }；"
            f"证据形式 `{', '.join(item['evidence_forms'])}`；"
            f"不能证明 `{', '.join(item['does_not_support'])}`"
        )
    lines.extend(["", "## 5. 本阶段要回答", ""])
    lines.extend(f"- {item}" for item in route.get("decisions", []))
    lines.extend(["", "## 6. 风险与停止规则", "", _risk_markdown(route.get("risk_flags", []))])
    lines.extend(
        [
            "- 采集前检查授权、隐私与参与者保护；高风险研究必须完成 S0。",
            "- 证据不足时输出研究状态与补证计划，不下结论。",
            "",
            "## 7. 交付物",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in route.get("deliverables", []))
    preview = route.get("platform_preview") or []
    if preview:
        lines.extend(["", "## 8. 数据来源预判", "", "| 平台 | 适配分 | 可用性 | 批量 |", "|---|---|---|---|"])
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


def deliver(study_dir: Path, kind: str = "memo") -> dict[str, Any]:
    study_dir = study_dir.resolve()
    study = load_json(study_dir / "study.json")
    route = study.get("route") or {}
    evidence = _evidence_summary(study_dir)
    audit_path = study_dir / "05-audit" / "audit.json"
    audit = load_json(audit_path) if audit_path.is_file() else None
    out_dir = study_dir / "06-report"
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "tracker":
        path = out_dir / "postlaunch-tracker.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["version", "metric", "numerator", "denominator", "window", "guardrail", "owner", "status", "note"])
        return {"status": "written", "path": str(path), "kind": kind}

    titles = {"memo": "决策备忘", "report": "研究报告", "prd": "PRD 输入"}
    title = titles.get(kind, "交付物")
    lines = [
        f"# {title}：{study.get('title', '')}",
        "",
        f"> 状态：草稿（未签收）。产品类型：{route.get('domain_label', study.get('product_domain', ''))}；"
        f"阶段：{route.get('stage_label', study.get('lifecycle_stage', ''))}。",
        "",
        "## 1. 结论",
        "",
        "- 结论 1（待补，必须挂证据 id）：",
        "- 结论 2（待补）：",
        "- 结论 3（待补）：",
        "",
        "## 2. 我们知道的",
        "",
        "| 证据 | 类型 | 证据形式 | 说明 |",
        "|---|---|---|---|",
    ]
    for record in evidence["records"][:20]:
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
            "## 3. 我们不知道的",
            "",
            "- 缺口（按 claim_type 列）：",
            "- 反证：",
            "- 适用范围：",
            "",
            "## 4. 建议与代价",
            "",
            "- 建议：",
            "- 代价/风险：",
            "",
            "## 5. 下一步验证",
            "",
            "- 最便宜的补证：",
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
            "本交付物不证明总体比例、市场规模或因果；可用性、工程性能、商业与安全结论分别有各自证据要求。",
        ]
    )
    if kind == "report":
        lines[6:6] = ["## 0. 方法与样本", "", f"- 方法：{', '.join(study.get('selected_methods', []))}", "- 样本与流失：待补", ""]
    if kind == "prd":
        lines = [
            f"# PRD 输入：{study.get('title', '')}",
            "",
            "## 用户与场景",
            "",
            "## 需求与证据",
            "",
            "## 非目标",
            "",
            "## 验收标准",
            "",
            "## 复测/上市跟踪",
            "",
            "## 证据附录",
            "",
        ] + lines[4:]
    path = out_dir / f"{kind}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "written", "path": str(path), "kind": kind, "evidence_count": evidence["count"]}


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
        "# askovo 平台雷达",
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
    if not value:
        return ""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalize_platform_record(raw: dict[str, Any], platform: str, run_id: str, query: str) -> dict[str, Any]:
    text = str(raw.get("text") or raw.get("body") or raw.get("selftext") or raw.get("content") or "")
    title = str(raw.get("title") or "")
    if title and text and title not in text:
        text = title + "\n\n" + text
    record_id = str(raw.get("record_id") or raw.get("id") or f"{platform}:{hashlib.sha256(text.encode()).hexdigest()[:12]}")
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


def _write_run(study_dir: Path, platform: str, run_id: str, records: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    raw_dir = study_dir / "02-data" / "raw" / platform
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{run_id}.jsonl"
    with raw_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    normalized_path = study_dir / "02-data" / "normalized.jsonl"
    added = 0
    with _locked_file(normalized_path.with_suffix(".lock")):
        existing: set[str] = set()
        if normalized_path.is_file():
            for line in normalized_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        existing.add(str(json.loads(line).get("record_id")))
                    except json.JSONDecodeError:
                        continue
        with normalized_path.open("a", encoding="utf-8") as handle:
            for record in records:
                if record["record_id"] in existing:
                    continue
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing.add(record["record_id"])
                added += 1
    manifest = dict(manifest)
    manifest.update({"run_id": run_id, "requested": manifest.get("requested", 0), "reached": len(records), "written": added, "raw_file": str(raw_path)})
    manifest_dir = study_dir / "01-sources" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"run_id": run_id, "raw_file": str(raw_path), "normalized_added": added, "manifest": str(manifest_path)}


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


class _WebSocket:
    """Minimal RFC6455 client for Chrome DevTools Protocol (ws:// only)."""

    def __init__(self, url: str, timeout: float = 30):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws":
            raise ValueError(f"only ws:// CDP endpoints are supported: {url}")
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
        status = response.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"CDP websocket handshake failed: {status.decode(errors='ignore')}")

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


def cdp_new_page(cdp_base: str, url: str) -> str:
    base = cdp_base.rstrip("/")
    target = f"{base}/json/new?{urllib.parse.quote(url, safe='')}"
    request = urllib.request.Request(target, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 405):
            raise
        with urllib.request.urlopen(target, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    ws_url = payload.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("CDP did not return a page websocket URL")
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
            "reason": "CDP is only enabled for platforms with authorized visible pages (amazon/instagram/x/youtube/bilibili/weibo)",
        }
    if not url:
        return {"status": "error", "platform": platform, "reason": "CDP requires --url"}
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
    run_id = _run_id(platform, "cdp")
    normalized = [_normalize_platform_record(raw, platform, run_id, query) for raw in raw_records]
    manifest = {
        "platform": platform,
        "query": query,
        "limit": limit,
        "adapter": "cdp",
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
    written = _write_run(study_dir, platform, run_id, normalized, manifest)
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
) -> dict[str, Any]:
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
    if cdp_url:
        return collect_cdp(study_dir, platform, query, url or "", cdp_url, ack_terms, limit)
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
    normalized = [_normalize_platform_record(raw, platform, run_id, query) for raw in raw_records[:limit]]
    manifest = {
        "platform": platform,
        "query": query,
        "limit": limit,
        "adapter": entry.get("adapter"),
        "access_basis": "authorized_export" if fixture else ", ".join(entry.get("access_modes", [])),
        "auth": entry.get("auth"),
        "started_at": now(),
        "finished_at": now(),
        "requested": limit,
        "limits": entry.get("limits", []),
        "bias": entry.get("bias", []),
    }
    written = _write_run(study_dir, platform, run_id, normalized, manifest)
    return {"status": "collected", "platform": platform, "records": len(normalized), **written}


def analyze_study(study_dir: Path, question: str | None = None) -> dict[str, Any]:
    study_dir = study_dir.resolve()
    records: list[dict[str, Any]] = []
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
                continue
            if isinstance(item, dict):
                records.append(item)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("record_id") or record.get("normalized_text_hash") or "")
        if key in seen:
            continue
        seen.add(key)
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
    if status in ("blocked", "adapter_unavailable", "error", "challenge"):
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

    def complete(self, job_id: str, records: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='done', record_count=?, lease_until=0, updated_at=? WHERE id=?",
                (records, now(), job_id),
            )

    def fail(self, job_id: str, error: str, attempts: int, max_attempts: int = 3) -> None:
        stamp = now()
        with self._connect() as conn:
            if attempts >= max_attempts:
                conn.execute(
                    "UPDATE jobs SET status='failed', last_error=?, lease_until=0, updated_at=? WHERE id=?",
                    (error[:2000], stamp, job_id),
                )
            else:
                delay = min(300, 5 * (2 ** max(0, attempts - 1)))
                conn.execute(
                    "UPDATE jobs SET status='retry', last_error=?, next_at=?, lease_until=0, updated_at=? WHERE id=?",
                    (error[:2000], time.time() + delay, stamp, job_id),
                )

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
                if row is None:
                    conn.execute("INSERT INTO rate_state (platform, next_at) VALUES (?, ?)", (platform, now_ts + min_interval))
                    wait = 0.0
                elif row["next_at"] <= now_ts:
                    conn.execute("UPDATE rate_state SET next_at=? WHERE platform=?", (now_ts + min_interval, platform))
                    wait = 0.0
                else:
                    wait = float(row["next_at"] - now_ts)
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
            wait = store.acquire_rate(job["platform"], _rate_for(job["platform"], min_interval))
            if wait > 0:
                time.sleep(wait)
            try:
                result = collect_platform(
                    study_dir,
                    job["platform"],
                    job["query"],
                    limit=int(job["limit_n"]),
                    fixture=Path(job["fixture"]) if job["fixture"] else None,
                    run_id=f"job-{job['id']}",
                    cdp_url=job["cdp_url"],
                    url=job["url"],
                    ack_terms=bool(job["ack_terms"]),
                )
                status = result.get("status")
                if status == "collected":
                    records = int(result.get("records", 0))
                    store.complete(job["id"], records)
                    with lock:
                        summary["done"] += 1
                        summary["records"] += records
                else:
                    store.fail(job["id"], json.dumps(result, ensure_ascii=False), int(job["attempts"]), int(job["max_attempts"]))
                    with lock:
                        summary["failed"] += 1
            except Exception as exc:  # keep the queue alive; record the failure
                store.fail(job["id"], f"{type(exc).__name__}: {exc}", int(job["attempts"]), int(job["max_attempts"]))
                with lock:
                    summary["failed"] += 1

    threads = [threading.Thread(target=worker, args=(f"worker-{index+1}",), daemon=False) for index in range(max(1, workers))]
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
        print(f"- 下一步：askovo instruments {result['study_dir']}；补全 study.json 后运行 askovo audit")
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

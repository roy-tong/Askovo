"""Role operating system for Askovo.

The role catalog orchestrates responsibilities, KPIs, SOPs, handoffs and
work-product templates. It never creates a second market, requirements,
product or business truth: study conclusions remain in product-reasoning.json.
Standard library only; Python 3.9+.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
CATALOG_PATH = ASSETS / "role-catalog.json"
INDUSTRY_PATH = ASSETS / "industry-contexts.json"
CHAIN_NODES = ("scene", "user", "pain", "need", "feature", "product", "business")
BASE_DOMAINS = ("software", "hardware", "consumer", "automotive", "mobile")
DEFAULT_INDUSTRY = {
    "software": "consumer_software",
    "hardware": "smart_hardware",
    "consumer": "cpg",
    "automotive": "automotive",
    "mobile": "smart_hardware",
}
STAGE_LIFECYCLES = {
    "discovery": ("L01", "L02"),
    "concept": ("L03", "L04"),
    "prototype": ("L05", "L06", "L07", "L08"),
    "validation": ("L08",),
    "pricing": ("L01", "L03"),
    "prelaunch": ("L08", "L09"),
    "postlaunch": ("L09", "L02"),
    "audit": ("L10", "L08"),
}
QUERY_ROLE_HINTS = (
    (("竞品", "竞争", "对标", "competitor"), ("R04", "竞品与替代研究")),
    (("价格", "定价", "支付意愿", "WTP", "pricing"), ("R20", "购买与价格决策")),
    (("法规", "认证", "合规", "标准", "监管"), ("R07", "法规与准入约束")),
    (("访谈", "焦点小组", "定性"), ("R11", "定性研究执行")),
    (("问卷", "定量", "联合分析", "分群"), ("R12", "定量研究设计")),
    (("旅程", "服务蓝图", "触点", "服务流程"), ("R39", "端到端服务设计")),
    (("Agent", "智能体", "大模型", "LLM"), ("R52", "AI 交互与失败恢复")),
    (("配方", "感官", "风味", "香氛"), ("R68", "感官与性能验证")),
    (("包装", "运输", "开箱"), ("R65", "包装工程与体验")),
    (("EVT", "DVT", "PVT", "量产", "试产"), ("R75", "工程与生产验证")),
    (("上市", "退市", "生命周期", "SKU"), ("R78", "生命周期与组合经营")),
    (("ResearchOps", "研究运营", "样本库", "知识库"), ("R79", "研究基础设施")),
    (("DesignOps", "设计运营", "设计资产"), ("R80", "设计基础设施")),
    (("概念", "concept"), ("R38", "产品概念设计")),
    (("商业案例", "ROI", "投资回报", "单位经济"), ("R08", "商业与经济可行性")),
    (("用户需求", "用户研究", "用户访谈", "消费者洞察"), ("R09", "用户与需求研究")),
    (("PRD", "需求规格", "需求文档", "验收标准"), ("R35", "需求与业务系统分析")),
    (("工业设计", "外观设计", "形态设计"), ("R56", "工业设计")),
    (("CMF", "色彩材料"), ("R57", "色彩材料工艺")),
    (("结构设计", "机械结构"), ("R58", "机械与结构设计")),
    (("系统架构", "系统设计", "系统需求"), ("R61", "系统架构与系统工程")),
    (("临床", "患者", "医疗流程"), ("R19", "医疗与临床需求研究")),
)
TASK_TYPES = ("decide", "discover", "define", "design", "validate", "launch", "operate", "review")
TASK_LABELS = {
    "decide": "决策与取舍",
    "discover": "市场与需求发现",
    "define": "产品定义与需求规划",
    "design": "方案与体验设计",
    "validate": "验证与评估",
    "launch": "上市与交付",
    "operate": "生命周期运营",
    "review": "审查与补证",
}
STAGE_TASK = {
    "discovery": "discover",
    "concept": "design",
    "prototype": "design",
    "validation": "validate",
    "pricing": "decide",
    "prelaunch": "launch",
    "postlaunch": "operate",
    "audit": "review",
}
TASK_HINTS = (
    ("decide", ("是否", "要不要", "值不值得", "值得做", "优先级", "取舍", "比较", "选择", "go/no-go", "决策", "商业可行性", "机会评估", "ROI", "投资回报", "回报")),
    ("discover", ("市场", "行业", "品类", "竞品", "趋势", "用户", "消费者", "访谈", "观察", "需求发现", "痛点", "机会发现", "人群", "画像", "VOC", "抱怨", "不满", "替代")),
    ("define", ("产品定义", "需求定义", "需求规格", "PRD", "范围", "验收", "backlog", "路线图", "需求分析", "功能定义")),
    ("design", ("概念", "设计", "原型", "交互", "界面", "体验", "结构", "外观", "CMF", "配方", "包装", "服务蓝图", "架构", "系统定义")),
    ("validate", ("验证", "测试", "可用性", "试点", "Beta", "HUT", "DVT", "EVT", "PVT", "可靠性", "安全", "合规", "概念测试", "价格测试", "评估")),
    ("launch", ("上市", "发布", "量产", "NPI", "试产", "GTM", "渠道", "商业化")),
    ("operate", ("运营", "留存", "流失", "复购", "生命周期", "SKU", "退市", "增长", "监控")),
    ("review", ("审计", "复核", "复盘", "现有材料", "补证", "体检", "评估已有", "审查")),
)
TASK_OUTPUT = {
    "decide": {
        "format": "决策备忘 / Business Case",
        "length": "1–3 页正文 + 证据附录",
        "structure": ["结论与推荐", "目标产品、场景与用户边界", "选项与不行动", "证据、反证与未知", "成本、风险与资源门", "下一验证与停止条件"],
        "audience": ["产品负责人", "业务/财务决策者"],
        "tone": "结论先行、业务语言、明确取舍",
        "evidence": "正文写数据基础与用户之声；证据等级、来源清单放附录",
        "visuals": ["选项比较表", "证据/风险矩阵"],
        "avoid": ["把岗位清单当方案", "用综合分掩盖单项失败", "把假设写成已验证"],
    },
    "discover": {
        "format": "研究简报 / 机会地图",
        "length": "3–6 页",
        "structure": ["研究问题与决策用途", "场景、角色与任务", "当前替代、痛点与后果", "需求与机会主题", "反证、无问题对照与覆盖缺口", "下一验证"],
        "audience": ["产品/研究团队", "设计负责人"],
        "tone": "证据优先、描述与解释分离",
        "evidence": "证据表 + 原话/行为摘录；未知与不可外推项并列",
        "visuals": ["任务/旅程图", "机会—证据矩阵"],
        "avoid": ["用词频代替需求优先级", "把便利样本推成总体", "只写阳性发现"],
    },
    "define": {
        "format": "需求规格 / PRD",
        "length": "标准规格（按验收项展开）",
        "structure": ["产品目标与非目标", "角色、场景与端到端流程", "需求与业务规则", "范围、优先级与依赖", "验收标准与追溯", "变更和未决风险"],
        "audience": ["产品", "研发", "设计", "QA"],
        "tone": "精确、可验收、可追溯",
        "evidence": "每条需求回链场景/需求/证据；假设与未决项显式",
        "visuals": ["流程与状态图", "需求追溯表"],
        "avoid": ["功能清单冒充产品定义", "没有非目标", "验收标准不可测"],
    },
    "design": {
        "format": "方案说明 + 设计/工程规格",
        "length": "按方案复杂度分模块",
        "structure": ["设计目标与约束", "候选方案与取舍", "目标体验/任务流程", "规格、接口与配置", "原型/样机与验证计划", "风险、非目标与下一阶段"],
        "audience": ["产品", "设计", "工程", "验证"],
        "tone": "方案具体、约束透明、取舍可比较",
        "evidence": "概念/原型版本、用户任务、工程约束分别标注；不把偏好当验证",
        "visuals": ["概念矩阵", "任务流/服务蓝图", "规格表"],
        "avoid": ["只放渲染图/界面稿", "不写工程约束", "概念接受写成产品验证"],
    },
    "validate": {
        "format": "分层验证报告 + 放行/缺口清单",
        "length": "完整报告（配置、分母、原始引用）",
        "structure": ["决策问题与预设判据", "版本、配置与样本", "价值/体验/工程/安全/生产分层结果", "失败、反证与不可判定项", "残余风险与复测", "结论边界与交接"],
        "audience": ["产品", "工程", "质量/安全/合规", "决策者"],
        "tone": "事实化、配置绑定、失败同等可见",
        "evidence": "原始记录索引、分母、阈值、时间窗；不用平均分合并验证类型",
        "visuals": ["验证矩阵", "配置—结果表"],
        "avoid": ["无分母通过率", "Beta/PVT/认证互替", "综合分替代单项结论"],
    },
    "launch": {
        "format": "发布/NPI 方案 + 风险与回滚",
        "length": "操作型检查单 + 关键说明",
        "structure": ["发布范围与目标", "版本/配置与依赖", "生产/渠道/支持准备", "质量门与专业签收", "监控、停止与回滚", "上市后复盘与退出条件"],
        "audience": ["产品", "供应链/运营", "市场/销售", "支持团队"],
        "tone": "行动导向、责任与阈值明确",
        "evidence": "发布依据引用分层验证与签收；计划不等于结果",
        "visuals": ["发布检查单", "里程碑与回滚表"],
        "avoid": ["把 decided 当 release-ready", "跳过专业签收", "无监控和回滚"],
    },
    "operate": {
        "format": "生命周期运营看板 + 行动清单",
        "length": "一页总览 + 指标/行动附录",
        "structure": ["当前生命周期阶段", "组合/SKU 与经营边界", "核心指标与分母", "用户/渠道/质量信号", "迭代、退市或资源调整", "下一复盘"],
        "audience": ["产品运营", "商业/品类", "支持团队"],
        "tone": "指标与行动导向",
        "evidence": "指标口径、时间窗、分母与来源；相关不等于因果",
        "visuals": ["生命周期/SKU 矩阵", "指标趋势"],
        "avoid": ["只报增长不看分母", "把相关当因果", "无退出标准"],
    },
    "review": {
        "format": "审计备忘 + 补证/整改清单",
        "length": "1–3 页 + 问题清单",
        "structure": ["审查范围与决策影响", "已支持/超出证据/未定", "推理断点与反证", "专业/合规缺口", "优先补证与整改", "重开与停止条件"],
        "audience": ["决策者", "研究/产品负责人"],
        "tone": "直接、分层、先讲阻断项",
        "evidence": "证据台账与主链位置；不重写结论",
        "visuals": ["问题—影响—动作表"],
        "avoid": ["为通过而改标签", "隐藏负例", "用文档完成度替代决策就绪"],
    },
}
TASK_DELIVERABLE_HINTS = {
    "decide": ("决策", "备忘", "brief", "商业案例", "商业", "机会", "路线图", "组合", "策略"),
    "discover": ("研究", "洞察", "需求", "画像", "旅程", "机会", "证据", "访谈", "简报", "地图"),
    "define": ("需求", "规格", "PRD", "验收", "范围", "优先级", "backlog", "路线图"),
    "design": ("设计", "概念", "原型", "方案", "规格", "架构", "配方", "包装", "交互", "蓝图", "契约", "工具", "失败", "权限", "感官", "材料"),
    "validate": ("验证", "测试", "评估", "报告", "协议", "计划", "放行", "缺口"),
    "launch": ("发布", "NPI", "上市", "量产", "计划", "GTM", "渠道", "定价"),
    "operate": ("生命周期", "运营", "组合", "SKU", "退市", "监控", "增长"),
    "review": ("审计", "复核", "缺口", "整改", "证据", "计划"),
}
TASK_DELIVERABLE_PENALTIES = {
    "decide": ("台账", "追踪", "矩阵", "PRD", "规格", "测试", "手册"),
    "discover": ("验收书", "上线检查"),
    "define": ("概念海报", "宣传册"),
    "design": ("决策台账", "宣传册"),
    "validate": ("宣传册", "概念海报"),
    "launch": ("概念海报",),
    "operate": ("概念海报", "研发规格"),
    "review": ("宣传册", "概念海报"),
}
SCALE_CAPS = {"lean": 3, "standard": 5, "cross_functional": 6}
DESIGN_LIFECYCLE = {
    "consumer_software": "L05",
    "enterprise_software": "L05",
    "ai_native": "L05",
    "smart_hardware": "L06",
    "traditional_hardware": "L06",
    "cpg": "L07",
    "apparel_home": "L07",
    "industrial_robotics": "L06",
    "automotive": "L06",
    "medical_health": "L06",
}
HIGH_RISK_INDUSTRIES = {"smart_hardware", "industrial_robotics", "automotive", "medical_health"}
LEAD_OVERRIDES = {
    ("ai_native", "L03"): "R29",
    ("ai_native", "L05"): "R52",
    ("enterprise_software", "L02"): "R19",
    ("enterprise_software", "L03"): "R28",
    ("smart_hardware", "L03"): "R30",
    ("traditional_hardware", "L03"): "R30",
    ("traditional_hardware", "L06"): "R56",
    ("cpg", "L03"): "R31",
    ("cpg", "L07"): "R66",
    ("apparel_home", "L07"): "R70",
    ("industrial_robotics", "L02"): "R19",
    ("industrial_robotics", "L03"): "R30",
    ("industrial_robotics", "L06"): "R61",
    ("automotive", "L06"): "R61",
    ("medical_health", "L02"): "R19",
    ("medical_health", "L03"): "R30",
    ("medical_health", "L08"): "R76",
}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid object catalog: {path}")
    return data


def load_catalog() -> dict[str, Any]:
    return _load(CATALOG_PATH)


def load_industries() -> dict[str, Any]:
    return _load(INDUSTRY_PATH)


def roles() -> list[dict[str, Any]]:
    return load_catalog().get("roles", [])


def lifecycles() -> list[dict[str, Any]]:
    return load_catalog().get("lifecycles", [])


def industries() -> list[dict[str, Any]]:
    return load_industries().get("industries", [])


def role_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in roles()}


def lifecycle_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in lifecycles()}


def industry_index() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in industries()}


def normalize_role(reference: str) -> str:
    value = str(reference or "").strip()
    if not value:
        raise ValueError("role id, name or alias is required")
    if value.isdigit():
        value = f"R{int(value):02d}"
    folded = value.casefold()
    for role in roles():
        candidates = [role["id"], role["name_zh"], role["name_en"], *role.get("aliases", [])]
        if folded in {str(item).casefold() for item in candidates}:
            return str(role["id"])
    raise ValueError(f"unknown role {reference!r}; use askovo roles list")


def normalize_industry(reference: str) -> str:
    value = str(reference or "").strip()
    folded = value.casefold()
    for industry in industries():
        candidates = [industry["id"], industry["label_zh"], industry["label_en"]]
        if folded in {str(item).casefold() for item in candidates}:
            return str(industry["id"])
    raise ValueError(f"unknown industry {reference!r}; use askovo roles list")


def _keyword_in_text(keyword: str, lowered_text: str) -> bool:
    word = str(keyword).casefold().strip()
    if not word:
        return False
    if word.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9 _+./-]*", word):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered_text))
    return word in lowered_text


def detect_industry(text: str, base_domain: str | None = None) -> dict[str, Any]:
    scores = []
    lowered = str(text or "").casefold()
    domain = base_domain if base_domain in BASE_DOMAINS else None
    for industry in industries():
        hits = [word for word in industry.get("keywords", []) if _keyword_in_text(str(word), lowered)]
        compatible_domains = industry.get("compatible_base_domains", [industry["base_domain"]])
        compatible = domain is None or domain in compatible_domains
        scores.append((len(hits), sum(len(str(word)) for word in hits), industry, hits, compatible))
    scores.sort(key=lambda row: (row[0], row[1], str(row[2]["id"])), reverse=True)
    compatible_rows = [row for row in scores if row[4]]
    overlay_rows = [row for row in compatible_rows if row[2].get("capability_overlay_only") and domain and domain != row[2]["base_domain"]]
    overlay_ids = {row[2]["id"] for row in overlay_rows}
    eligible = [row for row in compatible_rows if row[2]["id"] not in overlay_ids]
    capability_overlays = [
        {"id": row[2]["id"], "label_zh": row[2]["label_zh"], "keyword_hits": row[3]}
        for row in overlay_rows if row[0] > 0
    ]
    top = eligible[0] if eligible else (0, 0, None, [], True)
    tied = len(eligible) > 1 and top[0] > 0 and (eligible[1][0], eligible[1][1]) == (top[0], top[1])
    alternatives = [
        {"id": row[2]["id"], "label_zh": row[2]["label_zh"], "keyword_hits": row[3]}
        for row in eligible[1:] if row[0] > 0
    ]
    conflicts = [
        {"id": row[2]["id"], "label_zh": row[2]["label_zh"], "keyword_hits": row[3],
         "reason": f"industry compatibility {row[2].get('compatible_base_domains', [])} does not include routed domain {domain}"}
        for row in scores if not row[4] and row[0] > 0
    ]
    if top[0] > 0 and top[2] is not None:
        profile = top[2]
        return {
            "id": profile["id"],
            "label_zh": profile["label_zh"],
            "base_domain": profile["base_domain"],
            "source": "keyword_within_routed_domain" if domain else "keyword",
            "confidence": min(0.95, 0.55 + 0.1 * top[0]),
            "keyword_hits": top[3],
            "alternatives": alternatives,
            "conflicts": conflicts,
            "capability_overlays": capability_overlays,
            "requires_confirmation": tied,
        }
    domain = domain or "software"
    defaults = load_industries().get("defaults_by_base_domain", DEFAULT_INDUSTRY)
    industry_id = defaults[domain]
    profile = industry_index()[industry_id]
    return {
        "id": industry_id,
        "label_zh": profile["label_zh"],
        "base_domain": domain,
        "source": "domain_default",
        "confidence": 0.5,
        "keyword_hits": [],
        "alternatives": alternatives,
        "conflicts": conflicts,
        "capability_overlays": capability_overlays,
        "requires_confirmation": False,
    }


def _role_summary(role: dict[str, Any], industry_id: str | None = None) -> dict[str, Any]:
    result = {
        "id": role["id"],
        "name_zh": role["name_zh"],
        "name_en": role["name_en"],
        "lifecycle_id": role["lifecycle_id"],
        "mission": role["mission"],
        "chain_nodes": list(role["chain_nodes"]),
        "primary_deliverables": [item["name"] for item in role["deliverables"][:2]],
    }
    if industry_id:
        result["industry_id"] = industry_id
        result["industry_overridden"] = industry_id in role.get("industry_overrides", {})
    return result


def resolve_role(reference: str, industry: str | None = None) -> dict[str, Any]:
    role_id = normalize_role(reference)
    role = copy.deepcopy(role_index()[role_id])
    if industry:
        industry_id = normalize_industry(industry)
        profile = copy.deepcopy(industry_index()[industry_id])
        override = role.get("industry_overrides", {}).get(industry_id, {})
        role["industry_context"] = profile
        role["industry_override"] = copy.deepcopy(override)
        role["resolved_gates"] = list(dict.fromkeys(
            list(role.get("quality_gates", []))
            + list(override.get("additional_gates", []))
            + list(profile.get("mandatory_gates", []))
        ))
        role["resolved_human_boundaries"] = list(dict.fromkeys(
            list(role.get("human_boundaries", [])) + list(profile.get("human_accountabilities", []))
        ))
    return role


def list_roles(
    lifecycle: str | None = None,
    industry: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    if lifecycle and lifecycle not in lifecycle_index():
        raise ValueError(f"unknown lifecycle {lifecycle!r}; expected L01-L10")
    industry_id = normalize_industry(industry) if industry else None
    needle = str(query or "").strip().casefold()
    result = []
    for role in roles():
        if lifecycle and role["lifecycle_id"] != lifecycle:
            continue
        if needle:
            searchable = {
                role["id"], role["name_zh"], role["name_en"], role["mission"],
                *role.get("aliases", []), *role.get("responsibilities", []),
                *(item["name"] for item in role.get("deliverables", [])),
            }
            if not any(needle in str(item).casefold() for item in searchable):
                continue
        result.append(_role_summary(role, industry_id))
    return result


def infer_task(goal: str, stage: str | None = None, task: str | None = None) -> dict[str, Any]:
    if task:
        if task not in TASK_TYPES:
            raise ValueError(f"unknown task {task!r}; choose from: {', '.join(TASK_TYPES)}")
        return {"id": task, "label": TASK_LABELS[task], "source": "explicit", "confidence": 1.0, "scores": {}}
    lowered = str(goal or "").casefold()
    scores: dict[str, int] = {}
    hits_by_task: dict[str, list[str]] = {}
    for task_id, hints in TASK_HINTS:
        hits = [hint for hint in hints if _keyword_in_text(hint, lowered)]
        scores[task_id] = len(hits)
        hits_by_task[task_id] = hits
    ranked = sorted(scores.items(), key=lambda item: (-item[1], TASK_TYPES.index(item[0])))
    top_task, top_score = ranked[0] if ranked else ("decide", 0)
    if top_score > 0:
        return {
            "id": top_task,
            "label": TASK_LABELS[top_task],
            "source": "keyword",
            "confidence": min(0.9, 0.5 + 0.1 * top_score),
            "scores": {key: value for key, value in scores.items() if value},
            "keyword_hits": hits_by_task[top_task],
        }
    fallback = STAGE_TASK.get(str(stage), "decide")
    return {"id": fallback, "label": TASK_LABELS[fallback], "source": "stage_default", "confidence": 0.4, "scores": {}}


def _task_lifecycles(task: str, industry_id: str, profile: dict[str, Any], goal: str, lifecycle: str | None = None) -> tuple[str, ...]:
    if lifecycle:
        if lifecycle not in lifecycle_index():
            raise ValueError(f"unknown lifecycle {lifecycle!r}; expected L01-L10")
        return (lifecycle,)
    if task == "design":
        lifecycle_id = DESIGN_LIFECYCLE[industry_id]
        if industry_id == "medical_health" and any(word in goal for word in ("软件", "App", "数字", "界面")):
            lifecycle_id = "L05"
        return (lifecycle_id,)
    return {
        "discover": ("L01", "L02"),
        "decide": ("L03",),
        "define": ("L03",),
        "validate": ("L08",),
        "launch": ("L09",),
        "operate": ("L09", "L02"),
        "review": ("L10", "L08"),
    }[task]


def _task_lead(task: str, industry_id: str, profile: dict[str, Any], goal: str) -> str:
    lowered = goal.casefold()
    if task == "discover":
        market_words = ("市场", "行业", "品类", "竞品", "趋势", "market", "competitor")
        return "R01" if any(word in lowered for word in market_words) else "R09"
    if task in ("decide", "define"):
        return LEAD_OVERRIDES.get(
            (industry_id, "L03"), str(lifecycle_index()["L03"]["lead_role"]),
        )
    if task == "design":
        if any(word in lowered for word in ("服务设计", "服务蓝图", "服务流程")):
            return "R39"
        if industry_id in {"cpg", "apparel_home"} and "包装" in lowered and "配方" not in lowered:
            return "R71"
        if industry_id in {"consumer_software", "enterprise_software"}:
            if any(word in lowered for word in ("交互", "流程设计")):
                return "R46"
            if any(word in lowered for word in ("视觉", "UI", "品牌")):
                return "R48"
            return "R44"
        return {
            "ai_native": "R29",
            "smart_hardware": "R56",
            "traditional_hardware": "R56",
            "cpg": "R66",
            "apparel_home": "R70",
            "industrial_robotics": "R61",
            "automotive": "R61",
            "medical_health": "R61",
        }[industry_id]
    if task == "validate":
        if industry_id == "medical_health":
            return "R76"
        if any(word in lowered for word in ("可用性", "易用性", "usability")):
            return "R73"
        if any(word in lowered for word in ("HUT", "家庭试用", "Beta", "现场试用", "field trial")):
            return "R74"
        if industry_id in {"smart_hardware", "traditional_hardware", "industrial_robotics", "automotive"}:
            return "R75"
        return "R72"
    if task == "launch":
        return "R77"
    if task == "operate":
        return "R78"
    if any(word in lowered for word in ("研究", "证据", "材料", "research", "evidence")):
        return "R79"
    return "R26"


def _query_roles(goal: str, industry_id: str) -> dict[str, str]:
    lowered = str(goal).casefold()
    matches: dict[str, str] = {}
    for keywords, (role_id, reason) in QUERY_ROLE_HINTS:
        if any(_keyword_in_text(str(word), lowered) for word in keywords):
            matches[role_id] = f"任务触发：{reason}"
    if industry_id in {"cpg", "apparel_home"} and "包装" in lowered:
        if not any(word in lowered for word in ("运输", "防护", "结构", "跌落")):
            matches.pop("R65", None)
        matches["R71"] = "任务触发：包装与陈列体验"
    extras = {
        "industrial_robotics": (("工序", "节拍", "现场", "集成"), (("R61", "任务触发：现场系统集成"), ("R08", "任务触发：TCO/ROI"))),
        "automotive": (("HMI", "接管", "座舱"), (("R62", "任务触发：HMI 与人因"), ("R75", "任务触发：整车验证"))),
        "medical_health": (("风险", "使用错误", "预期用途"), (("R76", "任务触发：使用风险与合规"), ("R22", "任务触发：人因与使用环境"))),
        "cpg": (("功效", "稳定", "保质期"), (("R66", "任务触发：配方与稳定性"), ("R76", "任务触发：质量与法规"))),
        "smart_hardware": (("握持", "佩戴", "人因"), (("R22", "任务触发：人因与握持"),)),
        "ai_native": (("评测", "模型", "漂移", "幻觉"), (("R33", "任务触发：模型能力与评测"), ("R72", "任务触发：效果验证"))),
    }
    keywords, roles = extras.get(industry_id, ((), ()))
    if any(word.casefold() in lowered for word in keywords):
        for role_id, reason in roles:
            matches.setdefault(role_id, reason)
    return matches


def _recommend_scale(task: str, profile: dict[str, Any], industry_id: str, goal: str, requested: str | None) -> dict[str, Any]:
    if requested and requested not in SCALE_CAPS:
        raise ValueError(f"unknown scale {requested!r}; choose from: {', '.join(SCALE_CAPS)}")
    if requested:
        mode, source = requested, "explicit"
    else:
        risky_text = any(word in goal.casefold() for word in (
            "临床", "安全", "法规", "认证", "量产", "PVT", "DVT", "现场", "跨部门", "多部门", "迁移",
        ))
        if industry_id in HIGH_RISK_INDUSTRIES and task in {"design", "validate", "launch"}:
            mode, source = "cross_functional", "auto_high_risk_product"
        elif risky_text and task in {"validate", "launch", "design"}:
            mode, source = "cross_functional", "auto_risk_keywords"
        elif task in {"decide", "review", "discover", "operate"}:
            mode, source = "lean", "auto_task_focus"
        else:
            mode, source = "standard", "auto_default"
    return {
        "mode": mode,
        "cap": SCALE_CAPS[mode],
        "source": source,
        "rule": "最小充分团队：先保留牵头、任务触发与能力覆盖岗位，再用行业专业角色补足；高风险验证/上市才扩大。",
    }


def _deliverable_score(deliverable: dict[str, Any], task: str) -> int:
    name = str(deliverable.get("name", "")).casefold()
    positive = sum(len(hint) for hint in TASK_DELIVERABLE_HINTS[task] if hint.casefold() in name)
    negative = sum(len(hint) for hint in TASK_DELIVERABLE_PENALTIES.get(task, ()) if hint.casefold() in name)
    return positive - 2 * negative


def _choose_deliverable(role: dict[str, Any], task: str) -> dict[str, Any]:
    rows = role.get("deliverables", [])
    index, deliverable = max(
        enumerate(rows),
        key=lambda item: (_deliverable_score(item[1], task), -item[0]),
        default=(0, {}),
    )
    return deliverable


def _build_output_plan(
    task: str,
    selected_role_ids: list[str],
    lead_id: str,
    profile: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    index = role_index()
    lead_role = index[lead_id]
    primary_deliverable = _choose_deliverable(lead_role, task)
    supporting = []
    for role_id in selected_role_ids:
        if role_id == lead_id:
            continue
        role = index[role_id]
        deliverable = _choose_deliverable(role, task)
        if deliverable and _deliverable_score(deliverable, task) > 0:
            supporting.append({
                "role_id": role_id,
                "role_name": role["name_zh"],
                "deliverable_id": deliverable["id"],
                "name": deliverable["name"],
                "reason": f"补足 {TASK_LABELS[task]} 所需的专业输入",
            })
    supporting = supporting[:2]
    role_outputs = []
    for role_id in selected_role_ids:
        role = index[role_id]
        deliverable = _choose_deliverable(role, task)
        role_outputs.append({
            "role_id": role_id,
            "role_name": role["name_zh"],
            "deliverable_id": deliverable.get("id"),
            "name": deliverable.get("name"),
        })
    expression = dict(TASK_OUTPUT[task])
    expression.update({
        "language": "zh-CN",
        "industry_output_exemplars": list(profile.get("output_exemplars", [])),
        "industry_claim_boundaries": list(profile.get("claim_boundaries", [])),
        "principle": "内容只从主链、证据和已选岗位工作产出生成；岗位数量与输出篇幅按任务需要裁剪。",
    })
    return {
        "task": task,
        "task_label": TASK_LABELS[task],
        "primary": {
            "role_id": lead_id,
            "role_name": lead_role["name_zh"],
            "deliverable_id": primary_deliverable.get("id"),
            "name": primary_deliverable.get("name"),
        },
        "supporting": supporting,
        "role_work_outputs": role_outputs,
        "expression": expression,
        "content_plan": [
            {"section": section, "required": True}
            for section in expression["structure"]
        ],
        "source_refs": [
            "04-findings/product-reasoning.json",
            "04-findings/demand-judgments.json",
            "02-data/evidence.jsonl",
            "01-sources/role-workbench/workplan.json",
        ],
        "note": "输出合同在生成工作包时确定；正式语义仍只能从主链投影，不因篇幅或格式改变证据边界。",
    }


def recommend_roles(
    goal: str,
    industry: str | None = None,
    stage: str | None = None,
    lifecycle: str | None = None,
    base_domain: str | None = None,
    task: str | None = None,
    scale: str | None = None,
) -> dict[str, Any]:
    if not str(goal or "").strip():
        raise ValueError("goal is required for role recommendation")
    if base_domain and base_domain not in BASE_DOMAINS:
        raise ValueError(f"unknown base_domain {base_domain!r}; choose from: {', '.join(BASE_DOMAINS)}")
    if industry:
        industry_id = normalize_industry(industry)
        profile = industry_index()[industry_id]
        detected = {
            "id": industry_id,
            "label_zh": profile["label_zh"],
            "base_domain": profile["base_domain"],
            "source": "explicit",
            "confidence": 1.0,
            "keyword_hits": [],
            "alternatives": [],
            "conflicts": ([{
                "id": industry_id,
                "reason": f"explicit industry compatibility {profile.get('compatible_base_domains', [])} does not include routed domain {base_domain}; explicit choice retained",
            }] if base_domain and base_domain not in profile.get("compatible_base_domains", [profile["base_domain"]]) else []),
            "requires_confirmation": False,
            "capability_overlays": [],
        }
    else:
        detected = detect_industry(goal, base_domain)
        if detected.get("requires_confirmation") and not base_domain:
            choices = ", ".join([detected["id"], *[item["id"] for item in detected.get("alternatives", [])]])
            raise ValueError(f"industry is ambiguous; rerun with --industry. Candidates: {choices}")
        industry_id = str(detected["id"])
        profile = industry_index()[industry_id]
    task_info = infer_task(goal, stage, task)
    task_id = str(task_info["id"])
    lifecycle_ids = _task_lifecycles(task_id, industry_id, profile, goal, lifecycle)
    lead_id = _task_lead(task_id, industry_id, profile, goal)
    scale_info = _recommend_scale(task_id, profile, industry_id, goal, scale)
    query_roles = _query_roles(goal, industry_id)
    candidates: OrderedDict[str, dict[str, Any]] = OrderedDict()
    candidates[lead_id] = {"priority": 0, "reason": f"牵头：对本次{TASK_LABELS[task_id]}决策与交接负责"}
    for role_id, reason in query_roles.items():
        candidates.setdefault(role_id, {"priority": 1, "reason": reason})
    if task_id in {"decide", "define", "design", "validate"}:
        overlays = {str(item.get("id")) for item in detected.get("capability_overlays", [])}
        if industry_id == "ai_native":
            overlays.add("ai_native")
        if "ai_native" in overlays:
            for role_id in ("R29", "R52"):
                if role_id == "R52" and task_id == "decide" and role_id != lead_id:
                    continue
                if role_id not in candidates:
                    candidates[role_id] = {"priority": 2, "reason": "能力覆盖层：补足 AI 产品与交互/失败恢复视角"}
    for role_id in profile.get("core_roles", []):
        role = role_index().get(str(role_id))
        if role and role["lifecycle_id"] in lifecycle_ids:
            candidates.setdefault(str(role_id), {"priority": 3, "reason": "行业专业：本轮任务所需的行业角色"})
    if industry_id in HIGH_RISK_INDUSTRIES and task_id in {"validate", "launch"}:
        candidates.setdefault("R76", {"priority": 2, "reason": "高风险任务：独立安全、质量或合规复核"})
    authoritative = [lead_id, *query_roles.keys()]
    cap = int(scale_info["cap"])
    selected_ids = list(dict.fromkeys(authoritative))
    for role_id, meta in sorted(candidates.items(), key=lambda item: (item[1]["priority"], int(item[0][1:]))):
        if role_id in selected_ids:
            continue
        if len(selected_ids) >= cap:
            break
        selected_ids.append(role_id)
    ordered_selected = [lead_id, *[item for item in selected_ids if item != lead_id]]
    assignments = []
    for role_id in ordered_selected:
        role = role_index()[role_id]
        assignments.append({
            **_role_summary(role, industry_id),
            "assignment": "accountable" if role_id == lead_id else "responsible_or_consulted",
            "reason": candidates.get(role_id, {}).get("reason", "任务所需的专业角色"),
            "owner": None,
        })
    selected_set = set(selected_ids)
    deferred_roles = [
        {
            "id": role_id,
            "name_zh": role_index()[role_id]["name_zh"],
            "reason": "本轮任务暂不需要，或超出所选协作规模；任务范围扩大时再加入",
        }
        for role_id, meta in candidates.items()
        if role_id not in selected_set
    ]
    deferred_ids = {item["id"] for item in deferred_roles}
    for role_id in profile.get("core_roles", []):
        if role_id in selected_set or role_id in deferred_ids:
            continue
        deferred_roles.append({
            "id": role_id,
            "name_zh": role_index()[role_id]["name_zh"],
            "reason": "本轮任务阶段不需要该专业角色；出现对应设计、验证或上市任务时再加入",
        })
    assignment_ids = {item["id"] for item in assignments}
    handoff_edges = []
    for item in assignments:
        source = role_index()[item["id"]]
        for target_id in source.get("handoffs", {}).get("delivers_to", []):
            if target_id not in assignment_ids:
                continue
            target = role_index()[target_id]
            first_step = target.get("sop", [{}])[0]
            handoff_edges.append({
                "from": item["id"],
                "to": target_id,
                "deliverable_refs": [row["id"] for row in source.get("deliverables", [])],
                "expected_input": first_step.get("input"),
                "acceptance_gate": first_step.get("gate"),
                "binding_status": "proposed",
            })
    output_plan = _build_output_plan(task_id, ordered_selected, lead_id, profile, goal)
    return {
        "goal": goal,
        "industry": {
            "id": industry_id,
            "label_zh": profile["label_zh"],
            "base_domain": profile["base_domain"],
            "detection": detected,
        },
        "study_stage": stage,
        "task": task_info,
        "scope": {
            **scale_info,
            "selected_count": len(selected_ids),
            "deferred_count": len(deferred_roles),
            "expanded_for_task_triggers": len(selected_ids) > cap,
        },
        "lifecycles": [lifecycle_index()[item] for item in lifecycle_ids],
        "lead_role_id": lead_id,
        "assignments": assignments,
        "deferred_roles": deferred_roles,
        "output_plan": output_plan,
        "handoff_edges": handoff_edges,
        "industry_gates": list(profile["mandatory_gates"]),
        "claim_boundaries": list(profile["claim_boundaries"]),
        "canonical_reasoning": "04-findings/product-reasoning.json",
        "orchestration_only": True,
        "selection_policy": "minimum_sufficient",
        "note": "岗位与输出编排按目标、任务和产品类型裁剪；它是工作分工草案，不是需求、市场、产品或商业结论。",
    }


def validate_catalog() -> list[str]:
    errors: list[str] = []
    try:
        catalog = load_catalog()
        role_rows = catalog.get("roles", [])
        lifecycle_rows = catalog.get("lifecycles", [])
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"role catalog load: {exc}"]
    try:
        industry_rows = industries()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return errors + [f"industry catalog load: {exc}"]
    lifecycle_ids = {str(item.get("id")) for item in lifecycle_rows}
    role_ids = {str(item.get("id")) for item in role_rows}
    industry_ids = {str(item.get("id")) for item in industry_rows}
    expected_roles = {f"R{number:02d}" for number in range(1, 81)}
    expected_lifecycles = {f"L{number:02d}" for number in range(1, 11)}
    if role_ids != expected_roles:
        errors.append(f"role ids mismatch: missing={sorted(expected_roles-role_ids)} extra={sorted(role_ids-expected_roles)}")
    if len(role_rows) != 80:
        errors.append(f"expected 80 unique role rows, got {len(role_rows)}")
    if lifecycle_ids != expected_lifecycles or len(lifecycle_rows) != 10:
        errors.append("expected exactly L01-L10 lifecycle rows")
    if len(industry_rows) != 10 or len(industry_ids) != 10:
        errors.append("expected exactly 10 unique industry contexts")
    expected_counts = {"L01": 8, "L02": 16, "L03": 11, "L04": 8, "L05": 12, "L06": 10, "L07": 6, "L08": 5, "L09": 2, "L10": 2}
    for lifecycle_id, expected in expected_counts.items():
        actual = sum(1 for role in role_rows if role.get("lifecycle_id") == lifecycle_id)
        if actual != expected:
            errors.append(f"{lifecycle_id}: expected {expected} roles, got {actual}")
    for lifecycle in lifecycle_rows:
        for field in ("id", "name_zh", "question", "lead_role", "support_roles", "entry_criteria", "exit_criteria"):
            if not lifecycle.get(field):
                errors.append(f"lifecycle {lifecycle.get('id')}: missing {field}")
        for ref in [lifecycle.get("lead_role"), *lifecycle.get("support_roles", [])]:
            if ref not in role_ids:
                errors.append(f"lifecycle {lifecycle.get('id')}: unknown role {ref}")
    for role in role_rows:
        role_id = str(role.get("id", "?"))
        for field in ("lifecycle_id", "name_zh", "name_en", "aliases", "mission", "responsibilities", "kpis", "sop", "deliverables", "chain_nodes", "handoffs", "quality_gates", "human_boundaries"):
            if not role.get(field):
                errors.append(f"{role_id}: missing {field}")
        if role.get("lifecycle_id") not in lifecycle_ids:
            errors.append(f"{role_id}: invalid lifecycle")
        if len(role.get("responsibilities", [])) < 3:
            errors.append(f"{role_id}: fewer than 3 responsibilities")
        if len(role.get("kpis", [])) < 3:
            errors.append(f"{role_id}: fewer than 3 KPIs")
        kpi_ids = set()
        for index, kpi in enumerate(role.get("kpis", []), 1):
            kpi_id = str(kpi.get("id", ""))
            if not kpi_id.startswith(role_id + "-K") or kpi_id in kpi_ids:
                errors.append(f"{role_id}: invalid or duplicate KPI id {kpi_id}")
            kpi_ids.add(kpi_id)
            for field in ("name", "formula", "guardrail"):
                if not str(kpi.get(field, "")).strip():
                    errors.append(f"{role_id}: KPI {index} missing {field}")
        if len(role.get("sop", [])) < 5:
            errors.append(f"{role_id}: fewer than 5 SOP steps")
        sop_ids = set()
        for index, step in enumerate(role.get("sop", []), 1):
            sop_id = str(step.get("id", ""))
            if not sop_id.startswith(role_id + "-S") or sop_id in sop_ids:
                errors.append(f"{role_id}: invalid or duplicate SOP id {sop_id}")
            sop_ids.add(sop_id)
            for field in ("name", "input", "action", "output", "gate"):
                if not str(step.get(field, "")).strip():
                    errors.append(f"{role_id}: SOP {index} missing {field}")
        if len(role.get("deliverables", [])) < 2:
            errors.append(f"{role_id}: fewer than 2 deliverables")
        deliverable_ids = set()
        for deliverable in role.get("deliverables", []):
            deliverable_id = str(deliverable.get("id", ""))
            if not deliverable_id.startswith(role_id + "-D"):
                errors.append(f"{role_id}: invalid deliverable id {deliverable_id}")
            if deliverable_id in deliverable_ids:
                errors.append(f"{role_id}: duplicate deliverable {deliverable_id}")
            deliverable_ids.add(deliverable_id)
            if len(deliverable.get("sections", [])) < 4:
                errors.append(f"{deliverable_id}: fewer than 4 template sections")
            if len(deliverable.get("quality_checks", [])) < 2:
                errors.append(f"{deliverable_id}: fewer than 2 quality checks")
            for section in deliverable.get("sections", []):
                if not section.get("name") or not section.get("prompt"):
                    errors.append(f"{deliverable_id}: section needs name and prompt")
        if not set(role.get("chain_nodes", [])).issubset(set(CHAIN_NODES)):
            errors.append(f"{role_id}: invalid chain node")
        for direction in ("consumes_from", "delivers_to"):
            for ref in role.get("handoffs", {}).get(direction, []):
                if ref not in role_ids:
                    errors.append(f"{role_id}: unknown handoff {ref}")
        for industry_id in role.get("industry_overrides", {}):
            if industry_id not in industry_ids:
                errors.append(f"{role_id}: unknown industry override {industry_id}")
    for industry in industry_rows:
        industry_id = str(industry.get("id", "?"))
        if industry.get("base_domain") not in BASE_DOMAINS:
            errors.append(f"{industry_id}: invalid base domain")
        if industry.get("default_lifecycle") not in lifecycle_ids:
            errors.append(f"{industry_id}: invalid default lifecycle")
        compatible = industry.get("compatible_base_domains", [])
        if not compatible or industry.get("base_domain") not in compatible or not set(compatible).issubset(set(BASE_DOMAINS)):
            errors.append(f"{industry_id}: invalid compatible_base_domains {compatible}")
        for field in ("decision_focus", "stakeholders", "research_practices", "design_inputs", "prototype_forms", "verification_layers", "mandatory_gates", "human_accountabilities", "claim_boundaries", "output_exemplars"):
            if not industry.get(field):
                errors.append(f"{industry_id}: missing {field}")
        for ref in industry.get("core_roles", []):
            if ref not in role_ids:
                errors.append(f"{industry_id}: unknown core role {ref}")
    defaults = load_industries().get("defaults_by_base_domain", {})
    if set(defaults) != set(BASE_DOMAINS):
        errors.append("defaults_by_base_domain must cover all five SURE base domains")
    for domain, industry_id in defaults.items():
        if industry_id not in industry_ids:
            errors.append(f"default industry {industry_id} for {domain} does not exist")
        elif domain not in industry_index()[industry_id].get("compatible_base_domains", []):
            errors.append(f"default industry {industry_id} is incompatible with {domain}")
    return errors


def _deliverable(role: dict[str, Any], reference: str | None = None) -> dict[str, Any]:
    rows = role.get("deliverables", [])
    if not rows:
        raise ValueError(f"role {role['id']} has no deliverable")
    if not reference:
        return rows[0]
    folded = reference.casefold()
    for item in rows:
        if folded in {str(item["id"]).casefold(), str(item["name"]).casefold()}:
            return item
    raise ValueError(f"unknown deliverable {reference!r} for {role['id']}")


def render_template(
    role: dict[str, Any],
    deliverable: dict[str, Any],
    study: dict[str, Any] | None = None,
) -> str:
    study = study or {}
    decision = study.get("decision", {}) if isinstance(study.get("decision"), dict) else {}
    industry = role.get("industry_context", {})
    lines = [
        f"# {deliverable['name']}",
        "",
        "> 状态：工作模板（未填写、未复核、未签收）。本文件不是研究结论。",
        "",
        "| 字段 | 填写 |",
        "|---|---|",
        f"| 模板 ID | `{deliverable['id']}` |",
        f"| 岗位 | {role['id']} {role['name_zh']} / {role['name_en']} |",
        f"| 行业 | {industry.get('label_zh', '待确认')} |",
        "| 文档负责人 / 复核人 | 待分配 / 待分配 |",
        "| 版本 / 日期 | 待填写 / 待填写 |",
        f"| 决策问题 | {decision.get('question', '待确认')} |",
        "| 关联 chain / node / context | 待填写；必须能回到主链 |",
        "",
        "## 使用合同",
        "",
        f"- 工作目的：{deliverable.get('purpose', role['mission'])}",
        "- 输入、观察和推断分开；未知保留为空并写明补证责任，不把 null 写成 0。",
        "- 所有需求、市场、产品、商业判断只回写 `04-findings/product-reasoning.json` 与其关联需求判断；本模板不成为第二事实源。",
        "- 目标值不得由模板代填；交付、观察结果、因果、安全、法规、临床和量产状态分别复核。",
        "",
    ]
    for index, section in enumerate(deliverable.get("sections", []), 1):
        lines.extend([
            f"## {index}. {section['name']}",
            "",
            f"填写要求：{section['prompt']}",
            "",
            "> 七节点语义：`editable=false`，正式内容只从主链投影。此处不得新写市场、需求、产品或商业结论。",
            "> 专业执行记录/工作备注（非主链结论）：待填写。引用格式：`[来源/证据 ID · 定位 · 时间窗 · 配置/版本]`。",
            "",
        ])
    lines.extend(["## 质量门与签收", ""])
    for check in deliverable.get("quality_checks", []):
        lines.append(f"- [ ] {check}")
    for gate in role.get("resolved_gates", role.get("quality_gates", [])):
        lines.append(f"- [ ] {gate}")
    lines.extend([
        "- [ ] 反证、满意替代者、未覆盖人群和不能回答的问题已保留。",
        "- [ ] 下一接收岗位、所需输入、未决风险、责任人与截止条件已写清。",
        "",
        "## 专业边界",
        "",
    ])
    for boundary in role.get("resolved_human_boundaries", role.get("human_boundaries", [])):
        lines.append(f"- {boundary}")
    lines.extend([
        "",
        "> CLI/模板通过只表示结构完整；不证明市场、需求、产品、商业、临床、安全、合规、量产或因果结论。",
        "",
    ])
    return "\n".join(lines)


def validate_workplan(workplan: dict[str, Any], reasoning: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(workplan, dict) or not workplan.get("orchestration_only"):
        return ["workplan must be an orchestration_only object"]
    current_catalog_hash = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
    current_industry_hash = hashlib.sha256(INDUSTRY_PATH.read_bytes()).hexdigest()
    if workplan.get("catalog_sha256") != current_catalog_hash:
        errors.append("catalog_stale: role catalog hash differs; review and migrate the workplan")
    if workplan.get("industry_context_sha256") != current_industry_hash:
        errors.append("industry_context_stale: industry overlay hash differs; review and migrate the workplan")
    chains = {str(item.get("id")): item for item in reasoning.get("chains", []) if isinstance(item, dict)}
    assignments = workplan.get("roles", [])
    if not isinstance(assignments, list) or not assignments:
        return errors + ["workplan has no role assignments"]
    index = role_index()
    task_info = workplan.get("task") if isinstance(workplan.get("task"), dict) else {}
    if task_info.get("id") not in TASK_TYPES:
        errors.append("workplan task is missing or invalid")
    output_plan = workplan.get("output_plan") if isinstance(workplan.get("output_plan"), dict) else {}
    primary = output_plan.get("primary") if isinstance(output_plan.get("primary"), dict) else {}
    assigned_ids = {str(item.get("id")) for item in assignments if isinstance(item, dict)}
    if not primary:
        errors.append("workplan output_plan.primary is required")
    else:
        primary_role = index.get(str(primary.get("role_id")))
        if not primary_role or str(primary.get("role_id")) not in assigned_ids:
            errors.append("output_plan.primary role is not assigned")
        elif str(primary.get("deliverable_id")) not in {item["id"] for item in primary_role["deliverables"]}:
            errors.append("output_plan.primary deliverable does not belong to the primary role")
    for item in output_plan.get("supporting", []):
        role = index.get(str(item.get("role_id")))
        if not role or str(item.get("role_id")) not in assigned_ids:
            errors.append("output_plan supporting role is not assigned")
        elif str(item.get("deliverable_id")) not in {row["id"] for row in role["deliverables"]}:
            errors.append("output_plan supporting deliverable is invalid")
    expression = output_plan.get("expression") if isinstance(output_plan.get("expression"), dict) else {}
    for field in ("format", "length", "tone", "evidence", "audience", "structure", "avoid"):
        if not expression.get(field):
            errors.append(f"output_plan.expression missing {field}")
    for assignment in assignments:
        role_id = str(assignment.get("id", ""))
        role = index.get(role_id)
        if not role:
            errors.append(f"unknown workplan role {role_id}")
            continue
        owner = assignment.get("owner")
        if owner is not None and not isinstance(owner, str):
            errors.append(f"{role_id}: owner must be null or a string")
        statuses = assignment.get("sop_status", [])
        valid_steps = {item["id"] for item in role["sop"]}
        if {str(item.get("sop_id")) for item in statuses} != valid_steps:
            errors.append(f"{role_id}: SOP references do not match the catalog")
        for step in statuses:
            work_status = step.get("work_status")
            if work_status not in {"not_started", "in_progress", "blocked", "review_pending", "done"}:
                errors.append(f"{role_id}/{step.get('sop_id')}: invalid work_status {work_status}")
            if work_status != "not_started" and not owner:
                errors.append(f"{role_id}: active SOP work requires an assignment owner")
            if work_status in {"review_pending", "done"} and not step.get("reviewer"):
                errors.append(f"{role_id}/{step.get('sop_id')}: reviewer is required for {work_status}")
            if not isinstance(step.get("evidence_refs"), list):
                errors.append(f"{role_id}/{step.get('sop_id')}: evidence_refs must be a list")
        targets = assignment.get("chain_targets", [])
        if not targets:
            errors.append(f"{role_id}: no canonical chain targets")
        for target in targets:
            chain_id = str(target.get("chain_id") or "")
            chain = chains.get(chain_id)
            if not chain:
                errors.append(f"{role_id}: unknown chain target {chain_id}")
                continue
            node_id = str(target.get("node_id") or "")
            nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
            if node_id not in nodes or node_id not in role["chain_nodes"]:
                errors.append(f"{role_id}: invalid node target {chain_id}.{node_id}")
            if target.get("binding_status") != "bound":
                errors.append(f"{role_id}: target {chain_id}.{node_id} is not bound")
            edge_id = target.get("edge_id")
            if edge_id:
                parts = str(edge_id).split("->")
                if len(parts) != 2 or parts[1] != node_id or parts[0] not in CHAIN_NODES:
                    errors.append(f"{role_id}: invalid edge target {edge_id}")
        kpi_targets = assignment.get("kpi_targets", [])
        if {str(item.get("kpi_id")) for item in kpi_targets} != {item["id"] for item in role["kpis"]}:
            errors.append(f"{role_id}: KPI references do not match the catalog")
        kpi_definitions = {item["id"]: item for item in role["kpis"]}
        for target in kpi_targets:
            if target.get("target") is not None:
                for field in ("time_window", "denominator", "data_source_ref", "owner"):
                    if not target.get(field):
                        errors.append(f"{role_id}/{target.get('kpi_id')}: KPI target requires {field}")
                kpi_text = str(kpi_definitions.get(str(target.get("kpi_id")), {}).get("name", "")).casefold()
                if any(term in kpi_text for term in ("收入", "复购", "roi", "转化", "毛利", "营收", "付费", "revenue", "retention")) and not target.get("business_metric_ref"):
                    errors.append(f"{role_id}/{target.get('kpi_id')}: commercial KPI target requires business_metric_ref")
        if set(assignment.get("deliverable_refs", [])) != {item["id"] for item in role["deliverables"]}:
            errors.append(f"{role_id}: deliverable references do not match the catalog")
    return errors


def project_role_deliverable(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    evidence: dict[str, Any],
    role_ref: str,
    industry: str | None = None,
    deliverable_ref: str | None = None,
    audit_status: str = "not_run",
    workplan: dict[str, Any] | None = None,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Project canonical chain fields into a role deliverable; never author findings."""
    if not isinstance(reasoning, dict) or not isinstance(reasoning.get("chains"), list):
        raise ValueError("role delivery requires 04-findings/product-reasoning.json with a chains list")
    route = study.get("route", {}) if isinstance(study.get("route"), dict) else {}
    base_domain = str(study.get("product_domain") or route.get("domain") or "software")
    stored_industry = (workplan or {}).get("industry", {}).get("id") or study.get("industry_context") or route.get("industry_context", {}).get("id")
    industry_id = normalize_industry(industry or str(stored_industry or detect_industry(str(study.get("title", "")), base_domain)["id"]))
    role = resolve_role(role_ref, industry_id)
    deliverable = _deliverable(role, deliverable_ref)
    nodes_by_chain: dict[str, list[str]] = {}
    if workplan is not None:
        workplan_errors = validate_workplan(workplan, reasoning)
        if workplan_errors:
            raise ValueError("invalid role workplan: " + "; ".join(workplan_errors[:8]))
        assignments = [item for item in workplan.get("roles", []) if item.get("id") == role["id"]]
        if not assignments:
            raise ValueError(f"role {role['id']} is not assigned in the study workplan")
        for target in assignments[0].get("chain_targets", []):
            target_chain = str(target.get("chain_id"))
            if chain_id and target_chain != str(chain_id):
                continue
            nodes_by_chain.setdefault(target_chain, []).append(str(target.get("node_id")))
        if not nodes_by_chain:
            raise ValueError(f"role {role['id']} has no workplan target for chain {chain_id or 'requested'}")
    else:
        available_ids = [str(item.get("id")) for item in reasoning.get("chains", []) if isinstance(item, dict)]
        if chain_id and str(chain_id) not in available_ids:
            raise ValueError(f"unknown chain {chain_id!r}; available: {', '.join(available_ids)}")
        if len(available_ids) > 1 and not chain_id:
            raise ValueError("multiple chains exist; pass --chain or create a bound role workplan")
        selected = str(chain_id) if chain_id else available_ids[0]
        nodes_by_chain[selected] = list(role["chain_nodes"])
    records = evidence.get("records", []) if isinstance(evidence, dict) else []
    by_id = {str(item.get("record_id")): item for item in records if isinstance(item, dict)}
    labels = {"scene": "场景", "user": "用户", "pain": "痛点", "need": "需求", "feature": "特性", "product": "产品", "business": "商业"}
    lines = [
        f"# {deliverable['name']}：{study.get('title', '')}",
        "",
        "> 状态：主链只读投影（未签收）。岗位工作备注与主链结论分区保存。",
        f"> 审计状态：`{audit_status}`；审计未通过时不得把本文件作为已审核结论或放行依据。",
        "",
        f"- 岗位：{role['id']} {role['name_zh']} / {role['name_en']}",
        f"- 行业：{role['industry_context']['label_zh']}",
        f"- 模板：`{deliverable['id']}`；目的：{deliverable.get('purpose', role['mission'])}",
        "- 唯一语义来源：`04-findings/product-reasoning.json`；本文件重开时以主链重新投影为准。",
        "",
    ]
    if workplan and isinstance(workplan.get("output_plan"), dict):
        lines.extend(_output_contract_lines(workplan["output_plan"]))
    lines.extend(["## 1. 主链只读投影", ""])
    projected_chains = []
    cited_ids: list[str] = []
    source_refs: list[str] = []
    for chain in reasoning.get("chains", []):
        if not isinstance(chain, dict):
            continue
        current_chain_id = str(chain.get("id") or "PR?")
        if current_chain_id not in nodes_by_chain:
            continue
        projected_chains.append(current_chain_id)
        lines.extend([
            f"### {current_chain_id} {chain.get('title', '')}",
            "",
            f"- chain 状态：`{chain.get('status', 'unknown')}`；context：`{chain.get('context_key', '未填写')}`；需求判断：`{chain.get('demand_judgment_id', '未关联')}`",
            "- 这只是 chain 的选择/研究状态，不代表岗位交付、工程、临床、安全、合规、量产或因果状态。",
            "",
        ])
        nodes = chain.get("nodes", {}) if isinstance(chain.get("nodes"), dict) else {}
        for node_name in nodes_by_chain[current_chain_id]:
            node = nodes.get(node_name, {}) if isinstance(nodes.get(node_name, {}), dict) else {}
            source_ref = f"04-findings/product-reasoning.json#chains/{current_chain_id}/nodes/{node_name}"
            source_refs.append(source_ref)
            evidence_ids = [str(item) for item in node.get("evidence_ids", [])]
            cited_ids.extend(evidence_ids)
            lines.extend([
                f"#### {labels[node_name]} `{current_chain_id}.{node_name}`",
                "",
                f"- 来源：`{source_ref}`",
                f"- statement：{node.get('statement') or '主链尚未填写'}",
                f"- rationale：{node.get('rationale') or '主链尚未填写'}",
                f"- status：`{node.get('status', 'unknown')}`",
                f"- assumptions：{'；'.join(str(item) for item in node.get('assumptions', [])) or '主链尚未填写'}",
                f"- evidence_ids：{', '.join(evidence_ids) or '无'}",
                "",
            ])
        for item in chain.get("counter_evidence_ids", []):
            cited_ids.append(str(item))
    if not projected_chains:
        raise ValueError("role delivery found no product-reasoning chains to project")
    lines.extend(["## 2. 支撑证据与反证索引", "", "| ID | 级别/角色 | 来源 | 原文依据（截断） |", "|---|---|---|---|"])
    for record_id in list(dict.fromkeys(cited_ids)):
        record = by_id.get(record_id)
        if not record:
            lines.append(f"| `{record_id}` | 主链引用未在证据台账解析 | 待修复 | 不得据此补写结论 |")
            continue
        basis = str(record.get("evidence_basis") or record.get("text") or record.get("normalized_text") or "")[:160].replace("|", "\\|").replace("\n", " ")
        source = str(record.get("source_ref") or record.get("source_url") or "未填写")
        lines.append(f"| `{record_id}` | {record.get('evidence_level', '?')} / {record.get('corpus_role', '?')} | {source} | {basis} |")
    if not cited_ids:
        lines.append("| — | — | — | 相关主链节点尚未引用证据 |")
    lines.extend(["", "## 3. 模板章节与唯一来源映射", "", "以下仅规定每个工作章节可引用的主链位置，不在章节中生成第二套语义。", ""])
    for index, section in enumerate(deliverable.get("sections", []), 1):
        lines.extend([
            f"### 3.{index} {section['name']}",
            "",
            f"- 工作要求：{section['prompt']}",
            "- 七节点语义：`editable=false`；只能从以下来源投影，不能在本节独立编辑。",
            f"- 可引用来源：{', '.join('`' + item + '`' for item in source_refs)}",
            "- 工作结论必须回写主链及关联需求判断后，再重新生成正式投影。",
            "",
        ])
    lines.extend([
        "## 4. 岗位工作备注（不是主链结论）",
        "",
        "- 文档 Owner / 复核人：待分配 / 待分配",
        "- 适用配置、样本、时间窗与分母：仅引用主链/证据已有值；缺口待填写",
        "- 下一岗位、交接版本、拒收条件与重开触发器：待填写",
        "- 工作备注：待填写；不得在此处新写市场、需求、产品或商业结论",
        "",
        "## 5. 质量门与专业边界",
        "",
    ])
    for check in deliverable.get("quality_checks", []):
        lines.append(f"- [ ] {check}")
    for gate in role.get("resolved_gates", role.get("quality_gates", [])):
        lines.append(f"- [ ] {gate}")
    for boundary in role.get("resolved_human_boundaries", role.get("human_boundaries", [])):
        lines.append(f"- {boundary}")
    lines.extend([
        "",
        "## 边界",
        "",
        "> 主链投影不等于专业签收；decided 不等于 release-ready，E3 不等于发布，E5 不等于因果。本文不证明市场、需求、产品、商业、临床、安全、合规、量产或因果结论。",
        "",
    ])
    return {
        "markdown": "\n".join(lines),
        "role_id": role["id"],
        "deliverable_id": deliverable["id"],
        "industry_id": industry_id,
        "projected_chain_ids": projected_chains,
        "source_refs": source_refs,
        "catalog_sha256": (workplan or {}).get("catalog_sha256") or hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "workplan_bound": workplan is not None,
        "canonical_projection": True,
        "work_notes_separate": True,
    }


def project_lifecycle(
    study: dict[str, Any],
    reasoning: dict[str, Any] | None,
    workplan: dict[str, Any] | None = None,
    audit_status: str = "not_run",
) -> dict[str, Any]:
    """Render the 10-module navigation board without adding business semantics."""
    if workplan is not None:
        if not isinstance(reasoning, dict):
            raise ValueError("lifecycle workplan requires canonical reasoning")
        errors = validate_workplan(workplan, reasoning)
        if errors:
            raise ValueError("invalid role workplan: " + "; ".join(errors[:8]))
    industry_id = (workplan or {}).get("industry", {}).get("id") or study.get("industry_context") or (study.get("route", {}) or {}).get("industry_context", {}).get("id")
    industry = industry_index().get(str(industry_id)) if industry_id else None
    assignments = (workplan or {}).get("roles", [])
    by_role = {str(item.get("id")): item for item in assignments}
    index = role_index()
    lines = [
        f"# 产品全生命周期岗位导航：{study.get('title', '')}",
        "",
        "> 状态：岗位与工作流投影，不是产品/商业结论或发布看板。",
        f"> 审计状态：`{audit_status}`；行业：{industry['label_zh'] if industry else '待确认'}。",
        "",
        f"- 主链：`04-findings/product-reasoning.json`；workplan：{'已绑定 ' + str((workplan or {}).get('chain_id')) if workplan else '未生成'}",
        f"- 本次任务：{(workplan or {}).get('task', {}).get('label', '未指定')}；主交付：{(workplan or {}).get('output_plan', {}).get('primary', {}).get('name', '未指定')}",
        "- L10 为横切基础设施；任何反证都可重开上游，不用综合完成率抵消单项失败。",
        "",
    ]
    status_totals: dict[str, int] = {}
    for lifecycle in lifecycles():
        lines.extend([
            f"## {lifecycle['id']} {lifecycle['name_zh']}",
            "",
            f"- 决策问题：{lifecycle['question']}",
            f"- 入口：{'；'.join(lifecycle['entry_criteria'])}",
            f"- 出口：{'；'.join(lifecycle['exit_criteria'])}",
            f"- 牵头：{lifecycle['lead_role']} {index[lifecycle['lead_role']]['name_zh']}",
            f"- 协作：{', '.join(item + ' ' + index[item]['name_zh'] for item in lifecycle['support_roles'])}",
            "",
            "| 岗位 | 主责产出 | Owner | SOP 作业状态 |",
            "|---|---|---|---|",
        ])
        module_roles = [lifecycle["lead_role"], *lifecycle["support_roles"]]
        for role_id in module_roles:
            role = index[role_id]
            assignment = by_role.get(role_id)
            counts: dict[str, int] = {}
            if assignment:
                for step in assignment.get("sop_status", []):
                    value = str(step.get("work_status", "not_started"))
                    counts[value] = counts.get(value, 0) + 1
                    status_totals[value] = status_totals.get(value, 0) + 1
            status = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) if counts else "未纳入 workplan"
            lines.append(f"| {role_id} {role['name_zh']} | {'；'.join(item['name'] for item in role['deliverables'][:2])} | {(assignment or {}).get('owner') or '待分配'} | {status} |")
        lines.append("")
    lines.extend(["## 实际交接边（仅 workplan 已分配岗位）", ""])
    edges = []
    for assignment in assignments:
        source_id = str(assignment.get("id"))
        for target_id in assignment.get("handoff_refs", {}).get("delivers_to", []):
            if target_id not in by_role:
                continue
            edges.append((source_id, target_id))
            lines.append(f"- {source_id} → {target_id}：交付物引用、版本、反证/缺口、接收与重开条件须在项目交接中确认。")
    if not edges:
        lines.append("- 尚无已绑定岗位交接；先确认主链并生成 workplan。")
    lines.extend([
        "",
        "## 边界",
        "",
        "本导航不证明市场、需求、产品、商业、临床、安全、合规、量产或因果结论；SOP 状态不是证据等级，decided 不等于 release-ready。",
        "",
    ])
    return {
        "markdown": "\n".join(lines),
        "workplan_bound": workplan is not None,
        "catalog_sha256": (workplan or {}).get("catalog_sha256") or hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "assignment_count": len(assignments),
        "handoff_edge_count": len(edges),
        "work_status_counts": status_totals,
    }


def role_markdown(role: dict[str, Any]) -> str:
    lifecycle = lifecycle_index()[role["lifecycle_id"]]
    lines = [
        f"# {role['id']} {role['name_zh']} / {role['name_en']}",
        "",
        f"**使命：** {role['mission']}",
        "",
        f"- 生命周期：{lifecycle['id']} {lifecycle['name_zh']} — {lifecycle['question']}",
        f"- 主链映射：{' → '.join(role['chain_nodes'])}",
        f"- 常见岗位名称：{', '.join(role.get('aliases', []))}",
        "",
    ]
    if role.get("industry_context"):
        industry = role["industry_context"]
        lines.extend([
            f"## 行业化：{industry['label_zh']}",
            "",
            f"- 决策重点：{'；'.join(industry['decision_focus'])}",
            f"- 研究/服务对象：{'；'.join(industry['stakeholders'])}",
            f"- 设计输入：{'；'.join(industry['design_inputs'])}",
            f"- 原型形式：{'；'.join(industry['prototype_forms'])}",
            f"- 验证层：{' → '.join(industry['verification_layers'])}",
            "",
        ])
        if role.get("industry_override", {}).get("practice"):
            lines.extend([f"**本岗位行业实践：** {role['industry_override']['practice']}", ""])
    lines.extend(["## 岗位职责", ""])
    lines.extend(f"- {item}" for item in role["responsibilities"])
    lines.extend(["", "## KPI（定义，不预设目标）", "", "| KPI | 计算与观察口径 | 反作弊/解释护栏 |", "|---|---|---|"])
    for item in role["kpis"]:
        lines.append(f"| {item['name']} | {item['formula']} | {item['guardrail']} |")
    lines.extend(["", "## 标准 SOP", "", "| 步骤 | 工作 | 输入 | 动作 | 输出 | 质量门 |", "|---|---|---|---|---|---|"])
    for index, step in enumerate(role["sop"], 1):
        lines.append(f"| {index} | {step['name']} | {step['input']} | {step['action']} | {step['output']} | {step['gate']} |")
    lines.extend(["", "## 核心产出与模板", ""])
    for item in role["deliverables"]:
        lines.extend([
            f"### {item['id']} {item['name']}",
            "",
            f"目的：{item.get('purpose', role['mission'])}",
            "",
            f"模板章节：{' → '.join(section['name'] for section in item['sections'])}",
            "",
            "验收：" + "；".join(item["quality_checks"]),
            "",
        ])
    handoffs = role.get("handoffs", {})
    index = role_index()
    lines.extend([
        "## 交接",
        "",
        "- 上游：" + ", ".join(f"{item} {index[item]['name_zh']}" for item in handoffs.get("consumes_from", []) if item in index),
        "- 下游：" + ", ".join(f"{item} {index[item]['name_zh']}" for item in handoffs.get("delivers_to", []) if item in index),
        "",
        "## 人工与专业边界",
        "",
    ])
    lines.extend(f"- {item}" for item in role.get("resolved_human_boundaries", role["human_boundaries"]))
    lines.extend(["", "> 此岗位卡用于组织工作，不自动产生或批准任何产品/商业结论。", ""])
    return "\n".join(lines)


def _output_contract_lines(output_plan: dict[str, Any], heading: str = "##") -> list[str]:
    expression = output_plan["expression"]
    primary = output_plan["primary"]
    lines = [
        f"{heading} 输出与表达合同",
        "",
        f"- 主交付：**{primary['name']}**（{primary['role_id']} {primary['role_name']}）",
        f"- 文档格式：{expression['format']}",
        f"- 建议篇幅：{expression['length']}",
        f"- 主要读者：{'、'.join(expression['audience'])}",
        f"- 表达语气：{expression['tone']}",
        f"- 证据呈现：{expression['evidence']}",
        f"- 语言：{expression['language']}",
        "",
        "**内容结构**",
        "",
    ]
    lines.extend(f"{index}. {section}" for index, section in enumerate(expression["structure"], 1))
    if output_plan.get("supporting"):
        lines.extend(["", "**必要支撑产出**", ""])
        for item in output_plan["supporting"]:
            lines.append(f"- {item['role_id']} {item['role_name']}：{item['name']}（{item['reason']}）")
    if expression.get("industry_output_exemplars"):
        lines.extend(["", "**行业优先产出形态**", ""])
        lines.extend(f"- {item}" for item in expression["industry_output_exemplars"])
    lines.extend(["", "**表达禁忌**", ""])
    lines.extend(f"- {item}" for item in expression["avoid"])
    lines.extend(["", f"> {output_plan['note']}", ""])
    return lines


def recommendation_markdown(plan: dict[str, Any]) -> str:
    task = plan["task"]
    scope = plan["scope"]
    lines = [
        f"# 岗位与输出编排：{plan['goal']}",
        "",
        f"- 行业：{plan['industry']['label_zh']}（`{plan['industry']['id']}`）",
        f"- 任务：**{task['label']}**（`{task['id']}`，识别来源 `{task['source']}`）",
        f"- 协作规模：`{scope['mode']}`，上限 {scope['cap']} 个岗位；本次 {scope['selected_count']} 个",
        f"- 生命周期：{', '.join(item['id'] + ' ' + item['name_zh'] for item in plan['lifecycles'])}",
        f"- 牵头：{plan['lead_role_id']}",
        "",
        "## 最小充分团队",
        "",
        "| 岗位 | 分工 | 为什么需要 | 主责产出 | 负责人 |",
        "|---|---|---|---|---|",
    ]
    for item in plan["assignments"]:
        lines.append(f"| {item['id']} {item['name_zh']} | {item['assignment']} | {item['reason']} | {'；'.join(item['primary_deliverables'])} | {item['owner'] or '待分配'} |")
    if plan.get("deferred_roles"):
        lines.extend(["", "## 本轮暂不纳入", ""])
        for item in plan["deferred_roles"][:8]:
            lines.append(f"- {item['id']} {item['name_zh']}：{item['reason']}")
        if len(plan["deferred_roles"]) > 8:
            lines.append(f"- 另有 {len(plan['deferred_roles']) - 8} 个候选岗位按任务范围推迟。")
    lines.extend([""])
    lines.extend(_output_contract_lines(plan["output_plan"]))
    lines.extend(["## 行业质量门", ""])
    lines.extend(f"- {item}" for item in plan["industry_gates"])
    lines.extend(["", "## 边界", ""])
    lines.extend(f"- {item}" for item in plan["claim_boundaries"])
    lines.extend(["", plan["note"], ""])
    return "\n".join(lines)


def _workplan_markdown(
    plan: dict[str, Any],
    template_paths: dict[str, str],
    resolved_roles: list[dict[str, Any]],
) -> str:
    definitions = {role["id"]: role for role in resolved_roles}
    profile = industry_index()[plan["industry"]["id"]]
    task = plan.get("task", {})
    scope = plan.get("scope", {})
    role_outputs = {
        item["role_id"]: item["name"]
        for item in plan.get("output_plan", {}).get("role_work_outputs", [])
    }
    lines = [
        f"# 岗位执行包：{plan['study_id']}",
        "",
        "> 状态：分工与执行草案。负责人、目标值、时间盒和签收人均待团队确认。",
        "",
        f"- 行业：{plan['industry']['label_zh']} / 基础研究域：{plan['base_domain']}",
        f"- 任务：{task.get('label', '待确认')}（`{task.get('id', 'unknown')}`）",
        f"- 协作规模：`{scope.get('mode', 'explicit')}`；纳入 {len(plan['roles'])} 个岗位",
        f"- 决策合同：`{plan['decision_ref']}`",
        f"- 唯一推理真值：`{plan['canonical_reasoning']}`",
        f"- 岗位目录 SHA-256：`{plan['catalog_sha256']}`",
        "- 本执行包只保存目录引用和项目状态，不复制岗位定义或主链结论；SOP 完成不等于证据充分或专业放行。",
        "",
    ]
    if plan.get("output_plan"):
        lines.extend(_output_contract_lines(plan["output_plan"]))
    lines.extend([
        "## RACI、主链绑定与交接",
        "",
        "| 岗位 | RACI | 主链绑定 | 本轮主责产出 | Owner |",
        "|---|---|---|---|---|",
    ])
    for assignment in plan["roles"]:
        role = definitions[assignment["id"]]
        bindings = "; ".join(
            f"{item['chain_id'] or '待指定 chain'}:{item['node_id']}:{item['edge_id'] or 'node'}"
            for item in assignment["chain_targets"]
        )
        lines.append(f"| {role['id']} {role['name_zh']} | {assignment['assignment']} | {bindings} | {role_outputs.get(role['id'], '按执行包裁剪')} | {assignment['owner'] or '待分配'} |")
    lines.extend(["", "## KPI 目标合同", "", "| 岗位 | KPI | 目标 | 口径与护栏 |", "|---|---|---|---|"])
    for assignment in plan["roles"]:
        role = definitions[assignment["id"]]
        kpi_definitions = {item["id"]: item for item in role["kpis"]}
        for target in assignment["kpi_targets"]:
            kpi = kpi_definitions[target["kpi_id"]]
            lines.append(f"| {role['id']} | {kpi['id']} {kpi['name']} | 待确认（null，不是 0） | {kpi['formula']}；{kpi['guardrail']} |")
    for assignment in plan["roles"]:
        role = definitions[assignment["id"]]
        statuses = {item["sop_id"]: item for item in assignment["sop_status"]}
        lines.extend(["", f"## {role['id']} {role['name_zh']} SOP", "", "| # | 工作 | 输入 | 输出 | 通过条件 | 状态 |", "|---|---|---|---|---|---|"])
        for index, step in enumerate(role["sop"], 1):
            status = statuses.get(step["id"], {}).get("work_status", "not_started")
            lines.append(f"| {index} | {step['name']} | {step['input']} | {step['output']} | {step['gate']} | {status} |")
        generated = [item for item in role["deliverables"] if item["id"] in template_paths]
        if generated:
            lines.extend(["", "本轮交付模板："])
            for item in generated:
                path = template_paths[item["id"]]
                lines.append(f"- `{item['id']}` [{item['name']}]({path})")
        else:
            lines.extend(["", "本轮未为该岗位单独生成模板；按输出合同和岗位目录引用执行。"])
    lines.extend(["", "## 行业与专业放行门", ""])
    lines.extend(f"- [ ] {item}" for item in profile["mandatory_gates"])
    lines.extend(f"- [ ] {item}" for item in profile["human_accountabilities"])
    lines.extend(["", "> 任何阶段均可因反证回到上游；不得为了提高完成率删除反例或降低门槛。", ""])
    return "\n".join(lines)


def scaffold_workplan(
    study_dir: Path,
    role_refs: Iterable[str] | None = None,
    industry: str | None = None,
    force: bool = False,
    chain_id: str | None = None,
    task: str | None = None,
    scale: str | None = None,
    all_templates: bool = False,
) -> dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    catalog_errors = validate_catalog()
    if catalog_errors:
        raise ValueError("role catalog is invalid: " + "; ".join(catalog_errors[:5]))
    study = json.loads((study_dir / "study.json").read_text(encoding="utf-8"))
    if not isinstance(study, dict):
        raise ValueError("study.json must contain an object")
    route = study.get("route", {}) if isinstance(study.get("route"), dict) else {}
    base_domain = str(study.get("product_domain") or route.get("domain") or "software")
    if industry:
        industry_id = normalize_industry(industry)
    else:
        stored = study.get("industry_context") or route.get("industry_context", {}).get("id")
        industry_id = normalize_industry(str(stored)) if stored else detect_industry(str(study.get("title", "")), base_domain)["id"]
    protected_paths = {
        "reasoning": study_dir / "04-findings/product-reasoning.json",
        "judgments": study_dir / "04-findings/demand-judgments.json",
        "evidence": study_dir / "02-data/evidence.jsonl",
    }
    protected_before = {name: path.read_bytes() if path.exists() else None for name, path in protected_paths.items()}
    reasoning = json.loads(protected_paths["reasoning"].read_text(encoding="utf-8"))
    chains = reasoning.get("chains", []) if isinstance(reasoning, dict) else []
    chains = [item for item in chains if isinstance(item, dict)] if isinstance(chains, list) else []
    if not chains:
        raise ValueError("role scaffold requires at least one canonical product-reasoning chain")
    if chain_id:
        matching = [item for item in chains if str(item.get("id")) == str(chain_id)]
        if not matching:
            raise ValueError(f"unknown chain {chain_id!r}; available: {', '.join(str(item.get('id')) for item in chains)}")
        selected_chain = matching[0]
    elif len(chains) == 1:
        selected_chain = chains[0]
    else:
        raise ValueError("multiple canonical chains exist; pass --chain PRxx for the role workplan")
    selected_chain_id = str(selected_chain.get("id") or "")
    if not selected_chain_id:
        raise ValueError("canonical chain id is required for role workplan targets")
    chain_nodes = selected_chain.get("nodes", {}) if isinstance(selected_chain.get("nodes"), dict) else {}
    goal = str(study.get("decision", {}).get("question") or study.get("title") or "产品研究")
    stage = str(study.get("lifecycle_stage") or route.get("stage") or "discovery")
    task_info = infer_task(goal, stage, task)
    refs = [role_refs] if isinstance(role_refs, str) else list(role_refs or [])
    recommendation: dict[str, Any] | None = None
    if not refs:
        recommendation = recommend_roles(
            goal,
            industry_id,
            stage,
            base_domain=base_domain,
            task=task,
            scale=scale,
        )
        refs = [item["id"] for item in recommendation["assignments"]]
        lead_id = recommendation["lead_role_id"]
        output_plan = recommendation["output_plan"]
        scope = recommendation["scope"]
        deferred_roles = recommendation["deferred_roles"]
        task_info = recommendation["task"]
    else:
        normalized_ids = list(dict.fromkeys(normalize_role(item) for item in refs))
        refs = normalized_ids
        lead_id = normalized_ids[0]
        profile_for_output = industry_index()[industry_id]
        output_plan = _build_output_plan(str(task_info["id"]), normalized_ids, lead_id, profile_for_output, goal)
        scope = {
            "mode": "explicit",
            "cap": len(normalized_ids),
            "source": "explicit_roles",
            "selected_count": len(normalized_ids),
            "deferred_count": 0,
            "rule": "用户显式指定岗位；仍按同一个任务输出合同裁剪模板。",
        }
        deferred_roles = []
    resolved = [resolve_role(ref, industry_id) for ref in refs]
    profile = industry_index()[industry_id]
    plan_roles = []
    for role in resolved:
        available_nodes = [node for node in role["chain_nodes"] if node in chain_nodes]
        if not available_nodes:
            raise ValueError(f"role {role['id']} has no supported node in chain {selected_chain_id}")
        targets = []
        for node in available_nodes:
            index = CHAIN_NODES.index(node)
            previous = CHAIN_NODES[index - 1] if index else None
            targets.append({
                "chain_id": selected_chain_id,
                "node_id": node,
                "edge_id": f"{previous}->{node}" if previous in available_nodes else None,
                "binding_status": "bound",
            })
        plan_roles.append({
            "id": role["id"],
            "catalog_ref": f"assets/role-catalog.json#roles/{role['id']}",
            "assignment": "accountable" if role["id"] == lead_id else "responsible_or_consulted",
            "owner": None,
            "chain_targets": targets,
            "kpi_targets": [{
                "kpi_id": item["id"], "baseline": None, "target": None,
                "time_window": None, "denominator": None, "data_source_ref": None, "owner": None,
                "business_metric_ref": None,
            } for item in role["kpis"]],
            "sop_status": [{
                "sop_id": step["id"], "work_status": "not_started", "evidence_refs": [], "reviewer": None,
            } for step in role["sop"]],
            "deliverable_refs": [item["id"] for item in role["deliverables"]],
            "handoff_refs": role["handoffs"],
        })
    plan = {
        "schema_version": "1.0",
        "study_id": study.get("study_id", study_dir.name),
        "base_domain": base_domain,
        "industry": {"id": industry_id, "label_zh": profile["label_zh"]},
        "industry_context_ref": f"assets/industry-contexts.json#industries/{industry_id}",
        "catalog_schema_version": load_catalog().get("schema_version"),
        "catalog_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "industry_context_sha256": hashlib.sha256(INDUSTRY_PATH.read_bytes()).hexdigest(),
        "lead_role_id": lead_id,
        "chain_id": selected_chain_id,
        "task": task_info,
        "scope": scope,
        "output_plan": output_plan,
        "deferred_roles": deferred_roles,
        "all_templates": bool(all_templates),
        "decision_ref": "study.json#decision",
        "canonical_reasoning": "04-findings/product-reasoning.json",
        "orchestration_only": True,
        "selection_policy": "minimum_sufficient",
        "roles": plan_roles,
    }
    out_dir = study_dir / "01-sources" / "role-workbench"
    if out_dir.exists():
        raise ValueError("stateful role workbench already exists; refusing to overwrite it (including --force)")
    sources_dir = out_dir.parent
    sources_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".role-workbench-", dir=str(sources_dir)))
    final_template_dir = out_dir / "templates"
    try:
        template_dir = temp_dir / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        template_paths: dict[str, str] = {}
        output_ids = {str(output_plan.get("primary", {}).get("deliverable_id"))}
        output_ids.update(str(item.get("deliverable_id")) for item in output_plan.get("supporting", []))
        output_ids.discard("None")
        for role in resolved:
            for deliverable in role["deliverables"]:
                if not all_templates and deliverable["id"] not in output_ids:
                    continue
                filename = f"{deliverable['id']}.md"
                template_paths[deliverable["id"]] = f"templates/{filename}"
                (template_dir / filename).write_text(render_template(role, deliverable, study), encoding="utf-8")
        (temp_dir / "workplan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp_dir / "workplan.md").write_text(_workplan_markdown(plan, template_paths, resolved), encoding="utf-8")
        for name, path in protected_paths.items():
            after = path.read_bytes() if path.exists() else None
            if protected_before[name] != after:
                raise ValueError(f"role scaffold must not modify canonical {name}")
        os.replace(str(temp_dir), str(out_dir))
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    return {
        "status": "created",
        "study_dir": str(study_dir),
        "industry_id": industry_id,
        "chain_id": selected_chain_id,
        "role_ids": [role["id"] for role in resolved],
        "lead_role_id": lead_id,
        "task": task_info,
        "scope": scope,
        "primary_output": output_plan.get("primary"),
        "workplan": str(out_dir / "workplan.json"),
        "workplan_markdown": str(out_dir / "workplan.md"),
        "templates": [str(final_template_dir / Path(path).name) for path in template_paths.values()],
        "canonical_reasoning_unchanged": True,
        "demand_judgments_unchanged": True,
        "evidence_unchanged": True,
        "note": "已原子生成岗位 SOP/KPI/交接与模板；负责人、目标、证据和专业签收仍待人工完成。",
    }


def command_roles(args: Any) -> int:
    as_json = bool(getattr(args, "json", False))
    try:
        action = args.action
        if action == "list":
            rows = list_roles(getattr(args, "lifecycle", None), getattr(args, "industry", None), getattr(args, "query", None))
            result = {
                "catalog_version": load_catalog().get("schema_version"),
                "updated_at": load_catalog().get("updated_at"),
                "count": len(rows),
                "roles": rows,
                "lifecycles": lifecycles(),
                "industries": [{key: value for key, value in item.items() if key != "keywords"} for item in industries()],
                "note": "80 个岗位族是工作分类，不等于 80 个互斥正式职位；小团队可兼任但质量门不可合并掉。",
            }
            if as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"# Askovo 岗位目录（{len(rows)}）\n")
                print("| ID | 岗位族 | 生命周期 | 使命 | 核心产出 |")
                print("|---|---|---|---|---|")
                for item in rows:
                    print(f"| {item['id']} | {item['name_zh']} / {item['name_en']} | {item['lifecycle_id']} | {item['mission']} | {'；'.join(item['primary_deliverables'])} |")
        elif action == "show":
            role = resolve_role(args.role, getattr(args, "industry", None))
            if as_json:
                print(json.dumps(role, ensure_ascii=False, indent=2))
            else:
                print(role_markdown(role))
        elif action == "recommend":
            result = recommend_roles(
                args.goal,
                getattr(args, "industry", None),
                getattr(args, "stage", None),
                getattr(args, "lifecycle", None),
                getattr(args, "base_domain", None),
                task=getattr(args, "task", None),
                scale=getattr(args, "scale", None),
            )
            if as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(recommendation_markdown(result))
        elif action == "scaffold":
            result = scaffold_workplan(
                Path(args.study_dir),
                getattr(args, "role", []) or [],
                getattr(args, "industry", None),
                bool(getattr(args, "force", False)),
                getattr(args, "chain", None),
                task=getattr(args, "task", None),
                scale=getattr(args, "scale", None),
                all_templates=bool(getattr(args, "all_templates", False)),
            )
            if as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif action == "template":
            role = resolve_role(args.role, getattr(args, "industry", None))
            deliverable = _deliverable(role, getattr(args, "deliverable", None))
            content = render_template(role, deliverable)
            output = getattr(args, "output", None)
            if output:
                path = Path(output).resolve()
                if path.exists() and not getattr(args, "force", False):
                    raise ValueError(f"refusing to overwrite {path}; use --force")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                result = {"status": "created", "role_id": role["id"], "deliverable_id": deliverable["id"], "output": str(path), "review_status": "unreviewed"}
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif as_json:
                print(json.dumps({"role_id": role["id"], "deliverable_id": deliverable["id"], "markdown": content, "review_status": "unreviewed"}, ensure_ascii=False, indent=2))
            else:
                print(content)
        else:
            raise ValueError(f"unknown roles action {action!r}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        if as_json:
            print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"askovo roles: {exc}", file=sys.stderr)
        return 2

"""Static web reading surface for a delivered study (``askovo deliver --kind web``).

The study already produces complete artifacts (plan.md, report.md, analysis.md);
what this module adds is a *reading path* over the same canonical chain: numbers
and charts first, then the judgment, then the utterances behind it, then the
method archive. It writes one self-contained ``index.html`` plus a local
``assets/`` directory, with no CDN, no external request and no build step.

Three reading guarantees, all deterministic projections:

1. **Reading order** — page header → how to read → time layers → conclusion →
   seven nodes → evidence wall → distributions → reusable playbook → risks →
   method archive → boundary. Data, charts, quotes, source links and reusable
   moves sit on one path instead of in separate files.
2. **Time layers** — "now: numbers and charts" (latest data input, evidence
   count, delta version, audit time) is shown separately from "when the
   judgment was formed" (canonical chain write time, audit time, evidence time
   span). When evidence is newer than the chain, the page says so in plain
   language instead of quietly mixing the two.
3. **Business-facing evidence labels** — every record and every section carries
   one of four labels: 事实 / 推导 / 自述 / 我的判断. The E0–E5 grades,
   ``behavior_kind`` and qualification flags stay in the method archive, so the
   body reads like a business document while the audit trail stays intact.

Nothing here creates or upgrades a claim: the page renders ``study.json``,
``04-findings/product-reasoning.json`` and the evidence store as they are, and
the label mapping is a projection of fields that already exist.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

OUTPUT_SUBDIR = Path("06-report") / "web"
ASSET_SUBDIR = "assets"
MAX_ASSET_BYTES = 8 * 1024 * 1024

TAG_FACT = "事实"
TAG_DERIVED = "推导"
TAG_SELF = "自述"
TAG_JUDGMENT = "我的判断"

NODE_ORDER = ("scene", "user", "pain", "need", "feature", "product", "business")
NODE_LABELS = {
    "scene": "场景",
    "user": "用户",
    "pain": "痛点",
    "need": "需求",
    "feature": "特性",
    "product": "产品",
    "business": "商业",
}
NODE_QUESTIONS = {
    "scene": "什么时候、在什么环境下发生",
    "user": "谁有这个需求、他在决策里是什么角色",
    "pain": "现在怎么办、痛在哪、不解决的后果",
    "need": "他要的结果是什么、怎么衡量做好了",
    "feature": "哪些特性能满足、验收条件是什么",
    "product": "推演出的产品形态、范围和明确不做",
    "business": "卖给谁、怎么收钱、什么情况该重审",
}
NODE_FIELDS: dict[str, list[tuple[str, str]]] = {
    "scene": [("什么时候发生（触发）", "trigger"), ("在什么环境下", "environment"),
              ("用户当时在做什么（任务背景）", "task_context")],
    "user": [("角色", "role"), ("现状", "state"), ("在决策中的角色", "decision_role")],
    "pain": [("现在的替代做法", "current_substitute"), ("代价", "friction_cost"),
             ("不解决的后果", "consequence")],
    "need": [("期望的结果", "desired_outcome"), ("约束", "constraints"),
             ("怎么衡量做好了", "measure")],
    "feature": [("特性", "capability"), ("生效条件与验收", "acceptance_conditions"),
                ("考虑过的替代做法", "alternatives_considered")],
    "product": [("形态", "form"), ("范围", "scope"), ("明确不做", "non_goals"),
                ("上线验收", "acceptance_criteria")],
    "business": [("市场边界", "market_definition"), ("目标人群", "target_segment"),
                 ("付费者", "payer"), ("定位", "positioning"), ("渠道", "channels"),
                 ("定价方向", "pricing_hypothesis"), ("成本结构", "cost_drivers")],
}

# Label mapping (documented on the page itself). Content feature first: what the
# record actually captures; the E grade is only a fallback and never overrides
# an explicit behavior_kind.
FACT_BEHAVIOR_KINDS = {"problem_behavior", "solution_acceptance",
                       "commercial_transaction", "attention_metric"}
SELF_BEHAVIOR_KINDS = {"statement", "commercial_intent"}
FACT_LEVELS = {"E2", "E3", "E5"}
SELF_LEVELS = {"E0", "E1", "E4+", "E4-"}
ATTENTION_KINDS = {"attention_metric"}

OBSERVED_LEVELS = {"E2", "E3", "E4", "E4+", "E5"}
COMMERCIAL_LEVELS = {"E4", "E4+", "E5"}
ACCEPTANCE_LEVELS = {"E3", "E4", "E4+", "E5"}
SOURCE_LABELS = {
    "hackernews": "Hacker News",
    "reddit_arctic_shift": "Reddit（历史归档）",
    "reddit": "Reddit",
    "stackexchange": "Stack Exchange",
}
ROLE_LABELS = {
    "open_scene": "场景与问题自述",
    "direct_solution": "解法使用与接受",
    "substitute_rejector": "替代、放弃与拒绝",
    "post_purchase_support": "已购后的使用与维护",
    "control": "对照与不认同",
}
STATUS_LABELS = {
    "draft": "草稿",
    "hypothesis": "假设",
    "needs-validation": "待验证",
    "validated": "已验证（仍需人工复核）",
    "decided": "已定（记录的是选择）",
    "rejected": "已否决",
    "deprioritized": "暂缓",
}
DATA_GLOBS = ("02-data/evidence.jsonl", "02-data/normalized.jsonl",
              "02-data/screened-*.jsonl", "02-data/raw/**/*.jsonl")
REASONING_RELATIVE = "04-findings/product-reasoning.json"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _flat(value: Any) -> str:
    """Render a node field as one readable line, lists/dicts included."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                text = (item.get("definition") or item.get("criteria") or item.get("name")
                        or item.get("metric") or json.dumps(item, ensure_ascii=False))
                parts.append(str(text))
            else:
                parts.append(str(item))
        return "；".join(part for part in parts if part.strip())
    if isinstance(value, dict):
        return "；".join(f"{key}：{_flat(item)}" for key, item in value.items() if _flat(item))
    return str(value).strip()


def _iso(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _newest(paths: list[Path]) -> tuple[float | None, str]:
    best: tuple[float | None, str] = (None, "")
    for path in paths:
        stamp = _mtime(path)
        if stamp is not None and (best[0] is None or stamp > best[0]):
            best = (stamp, path.name)
    return best


def _data_files(study_dir: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in DATA_GLOBS:
        found.extend(sorted(path for path in study_dir.glob(pattern) if path.is_file()))
    return list(dict.fromkeys(found))


def _review_status(chains: list[dict[str, Any]]) -> str:
    for chain in chains:
        review = chain.get("human_review")
        if isinstance(review, dict) and review.get("status"):
            return str(review["status"])
    return ""


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Evidence labels and strength (canonical helpers are injected by sure_engine)
# ---------------------------------------------------------------------------

def label_for(record: dict[str, Any], qualification: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return (label, reason) for one record — 事实 / 自述.

    The projection prefers ``behavior_kind`` (what the record captures) and uses
    the E grade only as a fallback, so an API-verifiable attention metric is a
    fact about scale, never a fact about demand.
    """
    record_id = str(record.get("record_id") or "")
    info = (qualification or {}).get(record_id) or {}
    kind = str(info.get("behavior_kind") or record.get("behavior_kind") or "").strip().lower()
    level = str(record.get("evidence_level") or "").strip().upper()
    if kind in FACT_BEHAVIOR_KINDS:
        if kind in ATTENTION_KINDS:
            return TAG_FACT, "注意力指标：只描述规模，不证明需求或付费"
        if kind == "commercial_transaction":
            return TAG_FACT, "成交或付费记录"
        if kind == "solution_acceptance":
            return TAG_FACT, "方案被接受或使用"
        return TAG_FACT, "问题行为记录"
    if kind in SELF_BEHAVIOR_KINDS:
        return TAG_SELF, "自述或意愿，不是已发生的行为"
    if level in FACT_LEVELS:
        return TAG_FACT, f"{level}：行为或接受记录"
    if level in SELF_LEVELS:
        if level == "E4+":
            return TAG_SELF, "价格或购买意愿自述，不是付费行为"
        if level == "E4-":
            return TAG_SELF, "拒绝/退订等反向自述"
        return TAG_SELF, f"{level}：场景或任务陈述"
    return TAG_SELF, "未标注等级，按自述处理"


def label_counts(records: list[dict[str, Any]],
                 qualification: dict[str, Any] | None = None) -> dict[str, int]:
    """Count how many records project to each reading label (事实/自述)."""
    counts = {TAG_FACT: 0, TAG_SELF: 0}
    for record in records:
        label, _ = label_for(record, qualification)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _observed_levels(node_name: str | None) -> set[str]:
    if node_name == "business":
        return COMMERCIAL_LEVELS
    if node_name in {"feature", "product"}:
        return ACCEPTANCE_LEVELS
    return OBSERVED_LEVELS


def _fallback_strength(records: list[dict[str, Any]], node_name: str | None = None) -> tuple[str, str, str]:
    """Compact fallback; the engine injects the canonical ``_plan_strength``."""
    levels = _observed_levels(node_name)
    lead_levels = levels if node_name in {"business", "feature", "product"} else levels | {"E1"}
    observed = [r for r in records if str(r.get("evidence_level") or "").upper() in levels]
    leads = [r for r in records if str(r.get("evidence_level") or "").upper() in lead_levels]
    families = {str(r.get("source_family") or "未记录") for r in observed}
    if len(observed) >= 2 and len(families) >= 2:
        return "●", "已观察到", f"多个来源族观察：{len(families)} 个来源族 · {len(observed)} 条记录；相关性未证明独立"
    if leads:
        return "◐", "有线索", f"线索 {len(leads)} 条；未达多个来源族观察"
    return "○", "假设（待验证）", "尚无采集到的直接记录"


def _fallback_source_label(record: dict[str, Any]) -> str:
    family = str(record.get("source_family") or "").strip()
    family = SOURCE_LABELS.get(family, family)
    source_ref = str(record.get("source_ref") or "").strip()
    if source_ref:
        return f"{family}（{source_ref[:40]}）" if family else source_ref[:40]
    return family or "未记录来源"


def _fallback_time_span(records: list[dict[str, Any]]) -> str:
    stamps: list[str] = []
    for record in records:
        for field in ("source_time", "collected_at"):
            value = str(record.get(field) or "").strip()
            if value:
                stamps.append(value[:10])
    return f"{min(stamps)}–{max(stamps)}" if stamps else ""


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------

def _pill(text: str, tone: str = "neutral") -> str:
    return f'<span class="pill pill-{_esc(tone)}">{_esc(text)}</span>'


def _tag(label: str, reason: str = "") -> str:
    tone = {TAG_FACT: "fact", TAG_DERIVED: "derived", TAG_SELF: "self",
            TAG_JUDGMENT: "judgment"}.get(label, "neutral")
    title = f' title="{_esc(reason)}"' if reason else ""
    return f'<span class="tag tag-{tone}"{title}>{_esc(label)}</span>'


def _bar_chart(title: str, counts: dict[str, int], unit: str = "条") -> str:
    if not counts:
        return ""
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top = max(count for _, count in items) or 1
    rows: list[str] = []
    for index, (name, count) in enumerate(items):
        y = index * 30
        width = max(4.0, 460.0 * count / top)
        rows.append(
            f'<text class="chart-label" x="0" y="{y + 14}">{_esc(name)}</text>'
            f'<rect class="chart-bar" x="170" y="{y + 2}" width="{width:.1f}" height="16" rx="3"></rect>'
            f'<text class="chart-value" x="{170 + width + 8:.1f}" y="{y + 15}">{count}{_esc(unit)}</text>'
        )
    height = len(items) * 30 + 6
    return (
        f'<figure class="chart"><figcaption>{_esc(title)}</figcaption>'
        f'<svg viewBox="0 0 700 {height}" role="img" aria-label="{_esc(title)}">'
        + "".join(rows)
        + "</svg></figure>"
    )


def _cite_index(chains: list[dict[str, Any]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for chain in chains:
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for name in NODE_ORDER:
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            for record_id in node.get("evidence_ids") or []:
                bucket = index.setdefault(str(record_id), [])
                label = NODE_LABELS.get(name, name)
                if label not in bucket:
                    bucket.append(label)
        for record_id in chain.get("counter_evidence_ids") or []:
            bucket = index.setdefault(str(record_id), [])
            if "反面信号" not in bucket:
                bucket.append("反面信号")
    return index


def _copy_asset(study_dir: Path, out_dir: Path, record: dict[str, Any],
                warnings: list[str]) -> dict[str, Any] | None:
    reference = str(record.get("capture_screenshot_ref") or "").strip()
    if not reference:
        return None
    candidate = Path(reference)
    if not candidate.is_absolute():
        candidate = study_dir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        warnings.append(f"{record.get('record_id')}：截图路径无法解析（{reference}）")
        return None
    try:
        inside = resolved.is_relative_to(study_dir)
    except (OSError, ValueError):
        inside = False
    if not inside or not resolved.is_file():
        warnings.append(f"{record.get('record_id')}：截图不存在，未复制（{reference}）")
        return None
    try:
        size = resolved.stat().st_size
    except OSError:
        size = 0
    if size > MAX_ASSET_BYTES:
        warnings.append(f"{record.get('record_id')}：截图超过 8MB，未复制（{reference}）")
        return None
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()[:12]
    suffix = re.sub(r"[^A-Za-z0-9._-]", "-", resolved.name)[:60] or "capture.png"
    target_dir = out_dir / ASSET_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}-{suffix}"
    try:
        target.write_bytes(resolved.read_bytes())
    except OSError as exc:
        warnings.append(f"{record.get('record_id')}：截图复制失败（{exc}）")
        return None
    return {
        "record_id": str(record.get("record_id") or ""),
        "source_ref": reference,
        "relative_path": f"{ASSET_SUBDIR}/{target.name}",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "bytes": size,
    }


# ---------------------------------------------------------------------------
# Chain selection
# ---------------------------------------------------------------------------

def _decision_module() -> Any:
    """``decision_review`` loaded lazily.

    ``sure_engine`` imports this module at load time and ``decision_review``
    imports ``sure_engine``, so a top-level import here would be circular. At
    render time both are normally loaded already; for embedders that load
    ``sure_engine``/``web_surface`` by path the scripts directory is added
    temporarily so the canonical module can be imported.
    """
    try:
        import decision_review
        return decision_review
    except ModuleNotFoundError as exc:
        if exc.name != "decision_review":
            return None
    hint = str(Path(__file__).resolve().parent)
    added = hint not in sys.path
    if added:
        sys.path.insert(0, hint)
    try:
        import decision_review
        return decision_review
    except Exception:
        return None
    finally:
        if added and hint in sys.path:
            sys.path.remove(hint)


def _select_chain(chains: list[dict[str, Any]], records: list[dict[str, Any]]
                  ) -> tuple[dict[str, Any] | None, str]:
    """The one chain-selection rule shared with brief and the evidence page.

    ``chains[0]`` is never a default. If ``decision_review`` is unreachable the
    same rule is applied locally: a single chain selects itself, several chains
    require the latest DecisionRecord to name one.
    """
    module = _decision_module()
    if module is not None:
        try:
            return module.select_chain(chains, records=records)
        except Exception:
            pass
    items = [chain for chain in chains if isinstance(chain, dict)]
    if len(items) == 1:
        return items[0], "single"
    named = [record for record in records
             if isinstance(record, dict) and str(record.get("chain_id") or "").strip()]
    if not named:
        return None, "undecided"

    def version(record: dict[str, Any]) -> int:
        try:
            return int(record.get("version") or 0)
        except (TypeError, ValueError):
            return 0

    latest = max(named, key=lambda record: (version(record), str(record.get("recorded_at") or "")))
    target = str(latest.get("chain_id") or "")
    for chain in items:
        if str(chain.get("id") or "") == target:
            return chain, "decision"
    return None, "missing_decision"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _header(study: dict[str, Any], audit_status: str, chains: list[dict[str, Any]],
            records: list[dict[str, Any]], layers: dict[str, Any],
            selected: dict[str, Any] | None = None, selection: str = "") -> str:
    title = str(study.get("title") or "研究交付")
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    question = str(decision.get("question") or "").strip() or "研究问题未登记"
    headline = ""
    if isinstance(selected, dict):
        nodes = selected.get("nodes") if isinstance(selected.get("nodes"), dict) else {}
        business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
        if business.get("statement"):
            headline = str(business.get("statement"))
    if not headline:
        if selection == "missing_decision":
            headline = ("最新 DecisionRecord 指向的候选链在当前研究中不存在；"
                        "本页不默认回退第一条，请先修复研究文件或重新记录决定。")
        elif len(chains) > 1:
            headline = (f"研究含 {len(chains)} 条候选主链，尚无 DecisionRecord 选中；"
                        "本页不默认展开第一条，请用 `askovo brief --chain <CHAIN_ID>` 明确选择。")
        else:
            headline = "尚未形成七节点商业结论；当前页面只呈现已登记的场景、用户、痛点和需求线索。"
    families = {str(record.get("source_family") or "未记录") for record in records}
    pills = [
        _pill(f"证据 {len(records)} 条 · 来源族 {len(families)}", "neutral"),
        _pill(f"审计 {audit_status}", "ok" if audit_status == "pass" else "warn"),
        _pill(f"数据截至 {layers['data_at'] or '无数据'}", "neutral"),
    ]
    if layers["number_stale"]:
        pills.append(_pill("数字比判断新", "warn"))
    if layers["delta_stale"]:
        pills.append(_pill("增量待重审", "warn"))
    return f"""<header class="hero">
  <p class="kicker">Askovo 研究阅读面</p>
  <h1>{_esc(title)}</h1>
  <p class="question">{_esc(question)}</p>
  <p class="headline">{_esc(headline)}</p>
  <div class="pills">{''.join(pills)}</div>
</header>"""


def _how_to_read() -> str:
    return f"""<section id="read">
  <h2>怎么读这一页</h2>
  <div class="legend">
    <div class="legend-item">{_tag(TAG_FACT)}<span>已经发生的事：有人做过、接受过、付过钱，或一个可核实的规模数字。</span></div>
    <div class="legend-item">{_tag(TAG_SELF)}<span>别人说的：自述、意愿、抱怨。能说明方向，不能当成行为。</span></div>
    <div class="legend-item">{_tag(TAG_DERIVED)}<span>从事实和自述推出来的判断：七节点的结论与理由。</span></div>
    <div class="legend-item">{_tag(TAG_JUDGMENT)}<span>我们做的选择：做哪条链、先验证什么、什么情况算错。</span></div>
  </div>
  <p class="note">证据分级 E0–E5、行为类型和资格标记仍然完整保留，集中在页尾的<strong>方法档案</strong>里。正文只回答业务问题：看到什么、说明什么、下一步做什么。</p>
  <p class="note"><strong>数字比文字更新得快。</strong>下面的“现在”卡片读的是最新数据文件，“判断形成于”卡片读的是判断链最后一次写入的时间。两者不一致时，以数字和图表为准，并重新生成交付。</p>
</section>"""


def _time_section(layers: dict[str, Any]) -> str:
    stale_block = ""
    if layers["number_stale"]:
        stale_block = f"""<div class="alert alert-warn">
      <strong>数字已更新，结论文字尚未重算。</strong>
      <p>证据文件（{_esc(layers['data_source'] or '数据目录')}）比判断链（{_esc(layers['reasoning_at'] or '未写入')}）更新。
      本页的数字、图表和证据墙是当前值；结论与七节点文字仍是上一版。</p>
      <pre><code>{_esc(layers['reproduce_command'])}</code></pre>
    </div>"""
    if layers["delta_stale"]:
        stale_block += f"""<div class="alert alert-warn">
      <strong>增量研究有未处理的来源变化。</strong>
      <p>{_esc(layers['delta_action'] or '先修复来源并重跑增量同步')}</p>
    </div>"""
    delta_line = "未启用增量研究（`askovo delta sync`）"
    if layers["delta_versions"]:
        delta_line = (f"第 {layers['delta_versions']} 版 · {layers['delta_at'] or '时间未记录'}"
                      + ("（待重审）" if layers["delta_needs_review"] else ""))
    return f"""<section id="time">
  <h2>现在与判断形成时间</h2>
  <div class="time-grid">
    <div class="time-card time-now">
      <h3>现在：数字与图表</h3>
      <dl>
        <dt>数据截至</dt><dd>{_esc(layers['data_at'] or '未采集')}</dd>
        <dt>证据</dt><dd>{layers['record_count']} 条 · {layers['family_count']} 个来源族（相关性未证明独立）</dd>
        <dt>证据时间跨度</dt><dd>{_esc(layers['evidence_span'] or '未记录')}</dd>
        <dt>增量版本</dt><dd>{_esc(delta_line)}</dd>
        <dt>结构审计</dt><dd>{_esc(layers['audit_status'])} · {_esc(layers['audit_at'] or '未运行')}</dd>
      </dl>
    </div>
    <div class="time-card time-then">
      <h3>判断形成于</h3>
      <dl>
        <dt>判断链最后写入</dt><dd>{_esc(layers['reasoning_at'] or '尚未建立')}</dd>
        <dt>审计生成</dt><dd>{_esc(layers['audit_at'] or '未运行')}</dd>
        <dt>人工复核</dt><dd>{_esc(layers['review'] or '未记录')}</dd>
        <dt>交付重跑命令</dt><dd><code>{_esc(layers['reproduce_command'])}</code></dd>
      </dl>
    </div>
  </div>
  {stale_block}
</section>"""


def _conclusion_section(chains: list[dict[str, Any]], strengths: dict[str, tuple[str, str, str]],
                        study: dict[str, Any], selected: dict[str, Any] | None = None,
                        selection: str = "") -> str:
    if not chains:
        return """<section id="conclusion">
  <h2>结论与推进建议</h2>
  <p class="empty">尚未建立七节点推理，因此没有可呈现的结论。先用 `askovo do` 建立研究框架并采集数据，再重新生成本页。</p>
</section>"""
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    blocks: list[str] = []
    for chain in chains:
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        business = nodes.get("business") if isinstance(nodes.get("business"), dict) else {}
        marker, strength, detail = strengths.get(str(chain.get("id")), ("○", "假设", ""))
        gate = business.get("gate") if isinstance(business.get("gate"), dict) else {}
        prioritization = chain.get("prioritization") if isinstance(chain.get("prioritization"), dict) else {}
        rows = [
            ("做什么", business.get("statement") or "待填写"),
            ("卖给谁", business.get("target_segment") or "待确认"),
            ("谁付钱", business.get("payer") or "待确认"),
            ("怎么收钱", business.get("pricing_hypothesis") or "待验证"),
            ("先验证什么", chain.get("next_test") or "未登记下一验证"),
            ("什么情况算错", chain.get("failure_condition") or "未登记失败线"),
        ]
        body = "".join(
            f"<dt>{_esc(label)}</dt><dd>{_esc(_flat(value))}</dd>" for label, value in rows
        )
        status = str(chain.get("status") or "")
        gate_line = ""
        if gate:
            gate_line = (f"<p class=\"meta\">资源门禁：{_esc(gate.get('stage') or '待确认')} · "
                         f"{_esc(gate.get('decision') or '待确认')} · 负责人 {_esc(gate.get('owner') or '待确认')}"
                         f" · 复审条件 {_esc(gate.get('revisit_trigger') or '待确认')}</p>")
        rationale = prioritization.get("rationale") or prioritization.get("method") or ""
        current = ""
        if isinstance(selected, dict) and str(chain.get("id") or "") == str(selected.get("id") or ""):
            label = "当前决定" if selection == "decision" else "唯一主线"
            current = " " + _pill(label, "ok")
        blocks.append(f"""<article class="chain-card">
      <h3>{_tag(TAG_JUDGMENT)} <span class="chain-id">{_esc(chain.get('id') or 'PR?')}</span> {_esc(chain.get('title') or '未命名主线')}{current}</h3>
      <p class="meta">链状态：{_esc(STATUS_LABELS.get(status, status or '未记录'))} · 整体依据强度：{_esc(marker)} {_esc(strength)}</p>
      <dl class="kv">{body}</dl>
      {f'<p class="meta">为什么选它：{_esc(_flat(rationale))}</p>' if rationale else ''}
      {gate_line}
      <p class="meta">依据强度怎么算：{_esc(detail)}</p>
    </article>""")
    owner = str(decision.get("owner") or "待确认")
    deadline = str(decision.get("deadline") or "未设置")
    return f"""<section id="conclusion">
  <h2>结论与推进建议</h2>
  <p class="note">这一节是{_tag(TAG_JUDGMENT)}：它记录的是选择，不证明发布、因果或商业成功。负责人 {_esc(owner)} · 截止 {_esc(deadline)}。</p>
  {''.join(blocks)}
</section>"""


def _node_section(name: str, node: dict[str, Any], records: list[dict[str, Any]],
                  strength: tuple[str, str, str], basis: str) -> str:
    marker, strength_label, detail = strength
    rows: list[str] = []
    for label, key in NODE_FIELDS.get(name, []):
        value = node.get(key)
        if key == "time_window":
            geographies = node.get("geographies")
            geo = "、".join(str(item) for item in geographies) if isinstance(geographies, list) else ""
            text = f"{geo}；{_flat(value)}" if geo else _flat(value)
        else:
            text = _flat(value)
        if text:
            rows.append(f"<dt>{_esc(label)}</dt><dd>{_esc(text)}</dd>")
    if name == "user":
        business = node.get("segments")
        if isinstance(business, list) and business:
            segments = "；".join(
                f"{item.get('id', '分层')}：{item.get('criteria', '')}（付费者：{item.get('payer', '待确认')}）"
                for item in business if isinstance(item, dict)
            )
            if segments:
                rows.append(f"<dt>用户分层</dt><dd>{_esc(segments)}</dd>")
    if name == "business":
        metrics = node.get("success_metrics")
        if isinstance(metrics, list) and metrics:
            rendered = []
            for metric in metrics:
                if isinstance(metric, dict):
                    rendered.append(
                        f"{metric.get('metric_id', '指标')}：{metric.get('definition', '')}"
                        f"（口径 {metric.get('numerator', '—')}/{metric.get('denominator', '—')}，"
                        f"窗口 {metric.get('window', '待确认')}，护栏 {metric.get('guardrail', '待确认')}）"
                    )
            if rendered:
                rows.append(f"<dt>成功指标</dt><dd>{_esc('；'.join(rendered))}</dd>")
        pricing = node.get("pricing")
        if isinstance(pricing, list) and pricing:
            rendered = []
            for price in pricing:
                if isinstance(price, dict):
                    parts = [str(price.get(field)) for field in
                             ("model", "amount", "currency", "unit", "term", "note")
                             if price.get(field) not in (None, "")]
                    rendered.append("，".join(parts) or "记录未含金额")
                else:
                    rendered.append(str(price))
            rows.append(f"<dt>记录的价格点</dt><dd>{_esc('；'.join(rendered))}</dd>")
    statement = str(node.get("statement") or "待填写")
    rationale = str(node.get("rationale") or "").strip()
    assumptions = node.get("assumptions")
    assumption_html = ""
    if isinstance(assumptions, list) and assumptions:
        assumption_html = ("<p class=\"meta\">尚未验证的假设："
                           + _esc("；".join(str(item) for item in assumptions)) + "</p>")
    quotes = _quotes(name, records)
    return f"""<article class="node-card" id="node-{name}">
    <h3><span class="node-name">{_esc(NODE_LABELS.get(name, name))}</span> <span class="node-q">{_esc(NODE_QUESTIONS.get(name, ''))}</span></h3>
    <p class="node-statement">{_tag(TAG_DERIVED)} <strong>{_esc(statement)}</strong></p>
    {f'<dl class="kv">{"".join(rows)}</dl>' if rows else '<p class="meta">该环节的业务字段尚未填写。</p>'}
    {f'<p class="meta">为什么这么判断：{_esc(rationale)}</p>' if rationale else ''}
    {assumption_html}
    <p class="strength">{_esc(marker)} {_esc(strength_label)} · {_esc(detail)}</p>
    <p class="basis">{_esc(basis)}</p>
    {quotes}
  </article>"""


def _quotes(name: str, records: list[dict[str, Any]], limit: int = 2) -> str:
    cards: list[str] = []
    seen: set[str] = set()
    for record in records:
        if len(cards) >= limit:
            break
        text = str(record.get("text_excerpt") or record.get("text") or "").strip()
        kind = "原话"
        if len(text) < 8:
            text = str(record.get("friction_cost") or record.get("scene_trigger")
                       or record.get("task_outcome") or "").strip()
            kind = "典型情况"
        if len(text) < 8 or text[:40] in seen:
            continue
        seen.add(text[:40])
        when = str(record.get("source_time") or record.get("collected_at") or "").strip()
        meta = _fallback_source_label(record) + (f" · {when}" if when else "")
        cards.append(f"<blockquote><p>{_esc(text)}</p><footer>{_esc(kind)} · {_esc(meta)}</footer></blockquote>")
    if not cards:
        return ""
    return '<div class="quotes">' + "".join(cards) + "</div>"


def _chain_section(chains: list[dict[str, Any]], records: list[dict[str, Any]],
                   by_id: dict[str, dict[str, Any]], strengths: dict[str, tuple[str, str, str]],
                   helpers: dict[str, Callable],
                   selected: dict[str, Any] | None = None, selection: str = "") -> str:
    if not chains:
        return """<section id="chain">
  <h2>七节点推理</h2>
  <p class="empty">尚未建立七节点推理（场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业）。运行 `askovo do` 建立框架，补齐后再生成。</p>
</section>"""
    if isinstance(selected, dict):
        detail = [selected]
    elif len(chains) == 1:
        detail = chains
    else:
        detail = []
    strength_fn = helpers.get("strength") or _fallback_strength
    basis_fn = helpers.get("basis") or (lambda items: f"数据基础：{len(items)} 条语料" if items else "数据基础：本节暂无采集数据")
    parts: list[str] = []
    if len(chains) > 1 and detail:
        if selection == "decision":
            note = (f"本页展开最新 DecisionRecord 选中的一条主线；其余 {len(chains) - 1} 条候选链的状态、"
                    "下一步与失败线见上一节。")
        else:
            note = (f"本页展开显式选中的一条主线；其余 {len(chains) - 1} 条候选链的状态、"
                    "下一步与失败线见上一节。")
        parts.append(f'<p class="note">{note}</p>')
    elif not detail:
        if selection == "missing_decision":
            note = (f"最新 DecisionRecord 指向的候选链不在当前的 {len(chains)} 条链中；"
                    "本页不默认回退第一条，请先修复研究文件或重新记录决定。")
        else:
            note = (f"研究含 {len(chains)} 条候选主链，尚无 DecisionRecord 选中；本页不默认展开第一条。"
                    "请用 `askovo brief --chain <CHAIN_ID>` 明确选择。")
        parts.append(f'<p class="note">{note}</p>')
    for chain in detail:
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for name in NODE_ORDER:
            node = nodes.get(name)
            if not isinstance(node, dict):
                node = {}
            node_records = []
            seen: set[str] = set()
            for record_id in node.get("evidence_ids") or []:
                record = by_id.get(str(record_id))
                if record is not None and str(record_id) not in seen:
                    node_records.append(record)
                    seen.add(str(record_id))
            strength = strength_fn(node_records, name)
            parts.append(_node_section(name, node, node_records, strength, basis_fn(node_records)))
    return f"""<section id="chain">
  <h2>七节点推理</h2>
  <p class="note">{_tag(TAG_DERIVED)} 每个环节都标注依据强度：● 已观察到（多个来源族观察，相关性未证明独立）· ◐ 有线索（单案例或口头线索）· ○ 假设（尚无采集记录）。</p>
  {''.join(parts)}
</section>"""


def _evidence_section(records: list[dict[str, Any]], by_id_cites: dict[str, list[str]],
                      labels: dict[str, tuple[str, str]], assets: dict[str, dict[str, Any]],
                      qualification: dict[str, Any]) -> str:
    if not records:
        return """<section id="evidence">
  <h2>证据墙</h2>
  <p class="empty">还没有进入判断的证据记录。这不等于没有需求，只表示还没研究到。</p>
</section>"""
    cards: list[str] = []

    def order(record: dict[str, Any]) -> tuple[int, str]:
        record_id = str(record.get("record_id") or "")
        digits = re.sub(r"\D", "", record_id)
        return (int(digits) if digits else 10 ** 9, record_id)

    for record in sorted(records, key=order):
        record_id = str(record.get("record_id") or "")
        label, reason = labels.get(record_id, (TAG_SELF, "未标注"))
        text = str(record.get("text_excerpt") or record.get("text") or "").strip()
        if not text:
            text = str(record.get("scene_trigger") or record.get("task_outcome")
                       or record.get("friction_cost") or "").strip()
        if not text:
            text = "（该记录只包含结构化编码字段）"
        url = str(record.get("source_url") or "").strip()
        when = str(record.get("source_time") or record.get("collected_at") or "").strip()
        cites = by_id_cites.get(record_id) or []
        asset = assets.get(record_id)
        thumb = (f'<figure class="thumb"><img src="{_esc(asset["relative_path"])}" '
                 f'alt="记录 {_esc(record_id)} 的来源截图" loading="lazy">'
                 f'<figcaption>来源截图（已本地复制）</figcaption></figure>') if asset else ""
        link = f'<a href="{_esc(url)}" rel="noopener noreferrer">原帖/来源</a>' if url else ""
        info = (qualification.get("records") or {}).get(record_id) or {}
        technical = " · ".join(
            part for part in (
                str(record.get("evidence_level") or ""),
                str(info.get("behavior_kind") or ""),
                str(info.get("measurement_integrity") or ""),
                str(info.get("claim_eligibility") or ""),
            ) if part
        )
        cards.append(f"""<article class="evidence-card">
      <header><span class="record-id">{_esc(record_id)}</span> {_tag(label, reason)}</header>
      <p class="excerpt">{_esc(text[:600])}</p>
      <p class="meta">{_esc(_fallback_source_label(record))}{f' · {_esc(when)}' if when else ''}{f' · {link}' if link else ''}</p>
      {f'<p class="meta">被引用：{_esc(" / ".join(cites))}</p>' if cites else '<p class="meta">尚未被任何节点引用</p>'}
      {thumb}
      <footer class="tech">{_esc(technical)}</footer>
    </article>""")
    return f"""<section id="evidence">
  <h2>证据墙</h2>
  <p class="note">原文摘录、来源、时间和被哪些环节引用，放在一起看。{_tag(TAG_FACT)} 是已发生的行为，{_tag(TAG_SELF)} 是自述；分级代码只在卡片底部小字出现。</p>
  <div class="evidence-grid">{''.join(cards)}</div>
</section>"""


def _chart_section(records: list[dict[str, Any]], qualification: dict[str, Any],
                   chains: list[dict[str, Any]]) -> str:
    families: dict[str, int] = {}
    roles: dict[str, int] = {}
    labels: dict[str, int] = {}
    for record in records:
        family = str(record.get("source_family") or "未记录").strip() or "未记录"
        family = SOURCE_LABELS.get(family, family)
        families[family] = families.get(family, 0) + 1
        role = str(record.get("corpus_role") or "").strip()
        label = ROLE_LABELS.get(role, "其他/未标注")
        roles[label] = roles.get(label, 0) + 1
    for record in records:
        label, _ = label_for(record, qualification.get("records") or {})
        labels[label] = labels.get(label, 0) + 1
    coverage: dict[str, int] = {}
    for name in NODE_ORDER:
        covered = False
        for chain in chains:
            nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            if node.get("evidence_ids"):
                covered = True
                break
        coverage[NODE_LABELS[name]] = 1 if covered else 0
    charts = [
        _bar_chart("来源构成", families),
        _bar_chart("语料用途", roles),
        _bar_chart("证据标签分布", labels),
    ]
    covered = sum(coverage.values())
    coverage_html = "".join(
        f'<li class="{"on" if coverage[name] else "off"}">{_esc(name)}</li>' for name in NODE_LABELS.values()
    )
    if not records:
        return """<section id="charts">
  <h2>数据分布</h2>
  <p class="empty">还没有证据记录，因此没有可画的图。</p>
</section>"""
    return f"""<section id="charts">
  <h2>数据分布</h2>
  <p class="note">这些数字说明“看了多少、看到哪几类人”，不代表人群比例，也不能外推市场规模。图表读的是最新数据文件，可能比下面的判断文字更新。</p>
  <div class="charts">{''.join(chart for chart in charts if chart)}</div>
  <h3>七节点覆盖</h3>
  <p class="meta">{covered}/7 个环节已挂上证据。</p>
  <ul class="coverage">{coverage_html}</ul>
</section>"""


def _playbook_section(study: dict[str, Any], chains: list[dict[str, Any]],
                      records: list[dict[str, Any]], funnel: dict[str, Any],
                      route: dict[str, Any]) -> str:
    methods = study.get("selected_methods") or []
    methods_text = "、".join(str(item) for item in methods) if isinstance(methods, list) and methods else "未登记"
    cited: set[str] = set()
    for chain in chains:
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for name in NODE_ORDER:
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            cited.update(str(value) for value in node.get("evidence_ids") or [])
        cited.update(str(value) for value in chain.get("counter_evidence_ids") or [])
    raw = funnel.get("raw_records")
    screened = funnel.get("screened_records")
    steps = []
    if raw:
        steps.append(f"原始 {raw} 条")
    if screened:
        steps.append(f"筛选 {screened} 条")
    steps.append(f"编码 {len(records)} 条")
    steps.append(f"进入判断 {len(cited)} 条")
    funnel_text = " → ".join(steps)

    lanes: list[str] = []
    changes: list[str] = []
    for chain in chains:
        log = chain.get("change_log")
        if isinstance(log, list):
            for entry in log:
                if not isinstance(entry, dict):
                    continue
                changes.append(
                    f"<li><code>{_esc(entry.get('base_version') or '?')} → {_esc(entry.get('new_version') or '?')}</code>"
                    f"：{_esc(entry.get('impact') or '')}"
                    f"{'（触发证据：' + _esc(', '.join(str(item) for item in entry.get('reason_evidence_ids') or [])) + '）' if entry.get('reason_evidence_ids') else ''}"
                    f"<br><span class=\"meta\">{_esc(entry.get('decision') or '')}</span></li>"
                )
        prioritization = chain.get("prioritization") if isinstance(chain.get("prioritization"), dict) else {}
        if prioritization.get("method") or prioritization.get("rationale"):
            lanes.append(
                f"<li><strong>{_esc(chain.get('id') or 'PR?')}</strong> 的排序方法："
                f"{_esc(prioritization.get('method') or '')}"
                f"{'；' + _esc(prioritization.get('rationale') or '') if prioritization.get('rationale') else ''}</li>"
            )
    next_actions: list[str] = []
    for chain in chains:
        if chain.get("next_test"):
            next_actions.append(f"<li><strong>下一步验证（{_esc(chain.get('id') or 'PR?')}）</strong>：{_esc(chain.get('next_test'))}</li>")
        if chain.get("failure_condition"):
            next_actions.append(f"<li><strong>失败线（{_esc(chain.get('id') or 'PR?')}）</strong>：{_esc(chain.get('failure_condition'))}</li>")
        gaps = chain.get("gaps")
        if isinstance(gaps, list) and gaps:
            next_actions.append(
                f"<li><strong>仍未知（{_esc(chain.get('id') or 'PR?')}）</strong>："
                + _esc("；".join(str(item) for item in gaps[:3])) + "</li>"
            )
    if not next_actions:
        next_actions.append("<li>尚未登记下一步验证；先写下最便宜、最能改变决策的那个动作。</li>")
    return f"""<section id="playbook">
  <h2>可复用打法</h2>
  <p class="note">这一节回答“下次照着做什么”。全部内容来自本次研究已登记的路径、漏斗、变更记录和下一步，不新增判断。</p>
  <div class="playbook-grid">
    <div class="playbook-card">
      <h3>研究路径</h3>
      <dl class="kv">
        <dt>产品类型 / 阶段</dt><dd>{_esc(route.get('domain_label') or study.get('product_domain') or '未登记')} · {_esc(route.get('stage_label') or study.get('lifecycle_stage') or '未登记')}</dd>
        <dt>使用的方法</dt><dd>{_esc(methods_text)}</dd>
        <dt>语料漏斗</dt><dd>{_esc(funnel_text)}</dd>
        <dt>来源族</dt><dd>{len({str(r.get('source_family') or '未记录') for r in records})} 个（相关性未证明独立）</dd>
      </dl>
    </div>
    <div class="playbook-card">
      <h3>判断是怎么形成的</h3>
      <ul class="lane-list">{''.join(lanes) or '<li>链上没有登记排序方法或变更记录。</li>'}</ul>
      {f'<h3>版本变更</h3><ul class="lane-list">{"".join(changes)}</ul>' if changes else ''}
    </div>
    <div class="playbook-card wide">
      <h3>下次直接复用的动作</h3>
      <ul class="lane-list">{''.join(next_actions)}</ul>
    </div>
  </div>
</section>"""


def _risk_section(chains: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> str:
    blocks: list[str] = []
    for chain in chains:
        alternatives = chain.get("alternative_explanations")
        counter_ids = chain.get("counter_evidence_ids")
        items: list[str] = []
        if isinstance(alternatives, list):
            items.extend(f"<li>还没被排除的替代解释：{_esc(item)}</li>" for item in alternatives if str(item).strip())
        if isinstance(counter_ids, list):
            for record_id in counter_ids:
                record = by_id.get(str(record_id))
                if record is None:
                    items.append(f"<li>反面信号 <code>{_esc(record_id)}</code>（记录未在证据库中找到）</li>")
                    continue
                excerpt = str(record.get("text_excerpt") or record.get("text") or record.get("evidence_basis") or "")[:120]
                items.append(f"<li>反面信号 <code>{_esc(record_id)}</code>：{_esc(excerpt)}</li>")
        if not items:
            items.append("<li>没有登记替代解释或反面信号——这本身是一个缺口。</li>")
        blocks.append(
            f"<article class=\"risk-card\"><h3>{_esc(chain.get('id') or 'PR?')} · {_esc(chain.get('title') or '')}</h3>"
            f"<ul>{''.join(items)}</ul></article>"
        )
    if not chains:
        return """<section id="risks">
  <h2>风险与下一步</h2>
  <p class="empty">建立七节点推理后，本节给出替代解释、反面信号与下一步验证。</p>
</section>"""
    return f"""<section id="risks">
  <h2>风险与下一步</h2>
  {''.join(blocks)}
</section>"""


def _method_section(records: list[dict[str, Any]], qualification: dict[str, Any],
                    audit_info: dict[str, Any], layers: dict[str, Any],
                    warnings: list[str]) -> str:
    level_counts: dict[str, int] = {}
    integrity: dict[str, int] = {}
    for record in records:
        level = str(record.get("evidence_level") or "未标注").strip() or "未标注"
        level_counts[level] = level_counts.get(level, 0) + 1
    integrity = dict((qualification.get("counts") or {}).get("measurement_integrity") or {})
    behavior = dict((qualification.get("counts") or {}).get("behavior_kind") or {})
    eligibility = dict((qualification.get("counts") or {}).get("claim_eligibility") or {})

    def table(title: str, counts: dict[str, int]) -> str:
        if not counts:
            return ""
        rows = "".join(
            f"<tr><td>{_esc(name)}</td><td class=\"num\">{count}</td></tr>"
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )
        return (f"<h4>{_esc(title)}</h4><table class=\"mini\"><thead><tr><th>取值</th><th class=\"num\">条数</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>")

    checks = [check for check in audit_info.get("checks") or [] if isinstance(check, dict)]
    check_rows = "".join(
        f"<tr><td><code>{_esc(check.get('id') or '')}</code></td>"
        f"<td class=\"status-{_esc(check.get('status') or 'unknown')}\">{_esc(check.get('status') or '')}</td>"
        f"<td>{_esc(check.get('detail') or '')}</td></tr>"
        for check in checks
    )
    flagged = qualification.get("needs_requalification") or []
    flag_line = (f"<p>资格待重审：{_esc(', '.join(str(item) for item in flagged))}（原值保留，需人工重审）</p>"
                 if flagged else "<p>没有检测到资格冲突标记。</p>")
    warning_html = ""
    if warnings:
        warning_html = "<h4>生成提示</h4><ul>" + "".join(f"<li>{_esc(item)}</li>" for item in warnings) + "</ul>"
    return f"""<section id="method">
  <h2>方法档案</h2>
  <details>
    <summary>展开：证据分级、资格标记、审计检查与复现命令</summary>
    <p class="note">这一节保留引擎口径。正文的四类标签是它的业务读法，不改变任何原始分级。</p>
    {table("证据等级分布（E0–E5）", level_counts)}
    {table("行为类型 distribution", behavior)}
    {table("观测真实性", integrity)}
    {table("结论资格", eligibility)}
    {f'<h4>结构审计检查</h4><table class="mini"><thead><tr><th>检查</th><th>结果</th><th>说明</th></tr></thead><tbody>{check_rows}</tbody></table>' if check_rows else '<p>审计未运行，结构门槛状态未知。</p>'}
    {flag_line}
    <h4>复现</h4>
    <pre><code>{_esc(layers['reproduce_command'])}</code></pre>
    <pre><code>{_esc(layers['reproduce_plan_command'])}</code></pre>
    {warning_html}
  </details>
</section>"""


def _boundary_section(study: dict[str, Any]) -> str:
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    prohibited = scope.get("prohibited_inferences") if isinstance(scope.get("prohibited_inferences"), list) else []
    items = "".join(f"<li>{_esc(item)}</li>" for item in prohibited)
    return f"""<section id="boundary">
  <h2>边界</h2>
  <p>本页是同一条七节点推理链的阅读投影，不证明总体比例、市场规模、真实付费、因果、发布就绪或商业成功；“暂无采集数据”的环节待数据补齐后更新；四类标签是阅读辅助，不改变证据分级。最终产品与商业决定由负责人做出并留痕。</p>
  {f'<p class="meta">本研究明确禁止的推断：</p><ul>{items}</ul>' if items else ''}
</section>"""


CSS = """
:root{--ink:#16181d;--muted:#5b6472;--line:#e2e6ee;--bg:#f7f8fb;--card:#fff;
--fact:#0f7a53;--fact-bg:#e6f6ee;--self:#9a5b00;--self-bg:#fdf1dd;
--derived:#1d4ed8;--derived-bg:#e8efff;--judgment:#6b21a8;--judgment-bg:#f4e9fd;
--warn:#b42318;--warn-bg:#fdeceb}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
a{color:var(--derived)}
.hero,main,footer{max-width:1080px;margin:0 auto;padding:0 24px}
.hero{padding-top:48px;padding-bottom:8px}
.kicker{color:var(--muted);font-size:13px;letter-spacing:.08em;margin:0 0 8px}
.hero h1{font-size:32px;line-height:1.3;margin:0 0 12px}
.question{color:var(--muted);margin:0 0 14px}
.headline{font-size:19px;font-weight:600;margin:0 0 16px;padding-left:14px;border-left:4px solid var(--judgment)}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.pill{border-radius:999px;padding:3px 12px;font-size:13px;background:#eef1f7;color:var(--muted)}
.pill-ok{background:var(--fact-bg);color:var(--fact)}
.pill-warn{background:var(--warn-bg);color:var(--warn)}
nav.toc{max-width:1080px;margin:8px auto 0;padding:12px 24px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:#fff}
nav.toc ol{display:flex;flex-wrap:wrap;gap:4px 18px;margin:0;padding:0;list-style:none;font-size:14px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:26px 28px;margin:22px 0}
section h2{font-size:22px;margin:0 0 14px}
section h3{font-size:17px;margin:22px 0 8px}
section h4{font-size:14px;color:var(--muted);margin:18px 0 6px;letter-spacing:.04em}
.note{color:var(--muted);font-size:14px;margin:0 0 14px}
.meta{color:var(--muted);font-size:13px;margin:6px 0}
.empty{color:var(--muted)}
.tag{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:600;vertical-align:1px;margin-right:4px}
.tag-fact{background:var(--fact-bg);color:var(--fact)}
.tag-self{background:var(--self-bg);color:var(--self)}
.tag-derived{background:var(--derived-bg);color:var(--derived)}
.tag-judgment{background:var(--judgment-bg);color:var(--judgment)}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-bottom:14px}
.legend-item{border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px;background:#fbfcfe}
.legend-item span{display:block;margin-top:6px;color:var(--muted)}
.time-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.time-card{border:1px solid var(--line);border-radius:12px;padding:16px 18px;background:#fbfcfe}
.time-now{border-top:3px solid var(--derived)}
.time-then{border-top:3px solid var(--judgment)}
.time-card h3{margin:0 0 10px;font-size:16px}
dl.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;margin:10px 0}
dl.kv dt{color:var(--muted);font-size:14px}
dl.kv dd{margin:0}
.time-card dl{grid-template-columns:110px 1fr;font-size:14px}
.alert{border-radius:10px;padding:14px 16px;margin-top:16px;font-size:14px}
.alert-warn{background:var(--warn-bg);border:1px solid #f3c2bd;color:#7a1a12}
.alert p{margin:6px 0}
pre{background:#f1f3f8;border-radius:8px;padding:10px 12px;overflow:auto;font-size:13px;margin:8px 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
.chain-card{border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.chain-id{color:var(--muted);font-weight:600;font-size:14px}
.node-card{border:1px solid var(--line);border-radius:12px;padding:18px;margin:14px 0;background:#fdfefe}
.node-card h3{margin:0 0 10px;display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
.node-name{font-size:18px}
.node-q{color:var(--muted);font-size:13px;font-weight:400}
.node-statement{font-size:16px;margin:0 0 8px}
.strength{font-size:14px;margin:10px 0 2px}
.basis{font-size:13px;color:var(--muted);margin:2px 0 0}
.quotes{margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
blockquote{margin:0;border-left:3px solid var(--self);background:#fffaf2;padding:10px 14px;border-radius:0 8px 8px 0;font-size:14px}
blockquote p{margin:0 0 6px}
blockquote footer{color:var(--muted);font-size:12px}
.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.evidence-card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fbfcfe;display:flex;flex-direction:column}
.evidence-card header{margin-bottom:8px}
.record-id{font-family:ui-monospace,Menlo,monospace;color:var(--muted);margin-right:6px}
.excerpt{margin:0 0 8px;font-size:14px}
.tech{margin-top:auto;padding-top:8px;border-top:1px dashed var(--line);color:var(--muted);font-size:11px;font-family:ui-monospace,Menlo,monospace}
.thumb{margin:8px 0 0}
.thumb img{max-width:100%;border-radius:8px;border:1px solid var(--line);display:block}
.thumb figcaption{color:var(--muted);font-size:11px;margin-top:4px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.chart{margin:0;border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fff}
.chart figcaption{font-size:13px;color:var(--muted);margin-bottom:6px}
.chart svg{width:100%;height:auto;display:block}
.chart-label{font-size:11px;fill:#3b4350}
.chart-value{font-size:11px;fill:#5b6472}
.chart-bar{fill:#5b8def}
.coverage{display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0;margin:8px 0 0}
.coverage li{border-radius:8px;padding:4px 10px;font-size:13px}
.coverage .on{background:var(--derived-bg);color:var(--derived)}
.coverage .off{background:#f1f3f8;color:#98a1af}
.playbook-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.playbook-card{border:1px solid var(--line);border-radius:12px;padding:16px 18px;background:#fbfcfe}
.playbook-card.wide{grid-column:1/-1}
.playbook-card h3{margin-top:0}
.lane-list{margin:0;padding-left:18px;font-size:14px}
.lane-list li{margin-bottom:8px}
.risk-card{border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:12px}
.risk-card h3{margin:0 0 8px;font-size:16px}
table.mini{border-collapse:collapse;width:100%;max-width:640px;font-size:13px}
table.mini th,table.mini td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left}
table.mini .num{text-align:right;font-variant-numeric:tabular-nums}
.status-pass{color:var(--fact)}
.status-fail{color:var(--warn)}
details summary{cursor:pointer;font-weight:600;margin-bottom:10px}
footer.page{color:var(--muted);font-size:13px;padding:28px 24px 48px;border-top:1px solid var(--line);margin-top:30px}
@media (max-width:640px){
.hero h1{font-size:24px}
section{padding:20px 16px}
dl.kv{grid-template-columns:1fr}
.time-card dl{grid-template-columns:90px 1fr}
}
@media print{
body{background:#fff}
nav.toc{display:none}
section{break-inside:avoid;border:none;padding:0 0 12px;margin:16px 0;box-shadow:none}
}
"""

TOC = (
    ("read", "怎么读"), ("time", "现在与判断形成时间"), ("conclusion", "结论与推进建议"),
    ("chain", "七节点推理"), ("evidence", "证据墙"), ("charts", "数据分布"),
    ("playbook", "可复用打法"), ("risks", "风险与下一步"), ("method", "方法档案"),
    ("boundary", "边界"),
)


def render(
    study_dir: Path,
    *,
    study: dict[str, Any] | None = None,
    reasoning: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    audit_info: dict[str, Any] | None = None,
    delta_status: dict[str, Any] | None = None,
    funnel: dict[str, Any] | None = None,
    helpers: dict[str, Callable] | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Write ``06-report/web/index.html`` (+ local assets) and return a manifest.

    ``helpers`` carries the engine's canonical projection functions
    (``strength``/``basis``/``source_label``/``time_span``) so this page and
    ``plan.md`` cannot diverge; without them a compact fallback is used.
    """
    study_dir = Path(study_dir).resolve()
    study = study if isinstance(study, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    audit_info = audit_info if isinstance(audit_info, dict) else {"status": "not_run", "checks": []}
    helpers = helpers or {}
    delta_status = delta_status if isinstance(delta_status, dict) else {}
    records = [record for record in evidence.get("records") or [] if isinstance(record, dict)]
    qualification = evidence.get("qualification") if isinstance(evidence.get("qualification"), dict) else {}
    chains = [chain for chain in (reasoning or {}).get("chains") or [] if isinstance(chain, dict)] \
        if isinstance(reasoning, dict) else []
    decision_records = [item for item in (reasoning or {}).get("decision_records") or []
                        if isinstance(item, dict)] if isinstance(reasoning, dict) else []
    if chains:
        selected, selection = _select_chain(chains, decision_records)
    else:
        selected, selection = None, "empty"
    by_id = {str(record.get("record_id")): record for record in records}
    audit_status = str(audit_info.get("status") or "not_run")
    route = study.get("route") if isinstance(study.get("route"), dict) else {}

    target_dir = Path(out_dir) if out_dir is not None else study_dir / OUTPUT_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    assets_list: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    for record in records:
        asset = _copy_asset(study_dir, target_dir, record, warnings)
        if asset is not None:
            assets_list.append(asset)
            assets[str(asset["record_id"])] = asset

    reasoning_path = study_dir / REASONING_RELATIVE
    data_paths = _data_files(study_dir)
    data_stamp, data_source = _newest(data_paths)
    reasoning_stamp = _mtime(reasoning_path)
    latest_input = max(
        [stamp for stamp in (data_stamp, reasoning_stamp, _mtime(study_dir / "study.json")) if stamp is not None],
        default=None,
    )
    number_stale = bool(data_stamp is not None and reasoning_stamp is not None
                        and data_stamp > reasoning_stamp + 1.0)
    delta = delta_status or {}
    delta_versions = int(delta.get("versions") or 0)
    time_span_fn = helpers.get("time_span") or _fallback_time_span
    layers: dict[str, Any] = {
        "data_at": _iso(data_stamp)[:19].replace("T", " ") if data_stamp else "",
        "data_source": data_source,
        "reasoning_at": _iso(reasoning_stamp)[:19].replace("T", " ") if reasoning_stamp else "",
        "audit_status": audit_status,
        "audit_at": str(audit_info.get("generated_at") or "")[:19].replace("T", " "),
        "review": _review_status(chains),
        "record_count": len(records),
        "family_count": len({str(record.get("source_family") or "未记录") for record in records}),
        "evidence_span": time_span_fn(records),
        "delta_versions": delta_versions,
        "delta_at": str(delta.get("latest_at") or "")[:19].replace("T", " "),
        "delta_needs_review": bool(delta.get("needs_re_review")),
        "delta_stale": bool(delta.get("stale")),
        "delta_action": str(delta.get("next_required_action") or ""),
        "number_stale": number_stale,
        "reproduce_command": f'askovo deliver "{study_dir}" --kind web',
        "reproduce_plan_command": f'askovo deliver "{study_dir}" --kind plan',
    }

    strength_fn = helpers.get("strength") or _fallback_strength
    strengths: dict[str, tuple[str, str, str]] = {}
    for chain in chains:
        chain_records = []
        seen: set[str] = set()
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for name in NODE_ORDER:
            node = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
            for record_id in node.get("evidence_ids") or []:
                record = by_id.get(str(record_id))
                if record is not None and str(record_id) not in seen:
                    chain_records.append(record)
                    seen.add(str(record_id))
        strengths[str(chain.get("id"))] = strength_fn(chain_records)

    label_map = {str(record.get("record_id")): label_for(record, qualification.get("records") or {})
                 for record in records}
    toc_html = "".join(
        f'<li><a href="#{anchor}">{index}. {_esc(title)}</a></li>'
        for index, (anchor, title) in enumerate(TOC, start=1)
    )
    body = "".join([
        _header(study, audit_status, chains, records, layers, selected, selection),
        f'<nav class="toc" aria-label="页面目录"><ol>{toc_html}</ol></nav>',
        "<main>",
        _how_to_read(),
        _time_section(layers),
        _conclusion_section(chains, strengths, study, selected, selection),
        _chain_section(chains, records, by_id, strengths, helpers, selected, selection),
        _evidence_section(records, _cite_index(chains), label_map, assets, qualification),
        _chart_section(records, qualification, chains),
        _playbook_section(study, chains, records, funnel or {}, route),
        _risk_section(chains, by_id),
        _method_section(records, qualification, audit_info, layers, warnings),
        _boundary_section(study),
        "</main>",
    ])
    title = str(study.get("title") or "研究交付")
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Askovo web reading surface">
<meta name="robots" content="noindex">
<title>{_esc(title)} · Askovo 研究阅读面</title>
<style>{CSS}</style>
</head>
<body>
{body}
<footer class="page">
  <p>Askovo · 同一条七节点推理链的阅读投影 · 内容截至 {_esc(layers['data_at'] or '未采集')} · 判断形成于 {_esc(layers['reasoning_at'] or '未建立')}</p>
  <p>不证明总体比例、市场规模、真实付费、因果或商业成功。四类标签为阅读辅助，原始证据分级见方法档案。</p>
</footer>
</body>
</html>
"""
    index_path = target_dir / "index.html"
    index_path.write_text(document, encoding="utf-8")
    return {
        "path": str(index_path),
        "html": document,
        "assets": assets_list,
        "warnings": warnings,
        "layers": layers,
        "sections": [anchor for anchor, _ in TOC],
        "record_count": len(records),
        "chain_count": len(chains),
        "latest_input_mtime": _iso(latest_input) if latest_input else None,
    }

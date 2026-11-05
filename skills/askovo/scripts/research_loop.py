"""Research Loop: gap-driven, bounded, re-audited research rounds.

The loop turns SURE's own audit signals into collection actions, executes them
round by round inside an authorized envelope, re-audits after every round and
stops with a review-ready record of what is verified, unverified and blocked.

It is deterministic orchestration, not judgment:

- it never assigns an evidence level, edits a judgment, or marks a claim
  ``validated``;
- collected records become *candidates* in ``04-findings/loop-candidates.json``
  and wait for human semantic review;
- it may only act inside the envelope recorded at authorization time: allowed
  platforms, per-action record limit, round and record budget;
- platform policy, study scope, the Design gate and drained connectors still
  block actions exactly as they do for ``askovo research``.

State lives at ``04-findings/research-loop.json`` and is written atomically.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sure_engine

STATE_RELATIVE = Path("04-findings/research-loop.json")
CANDIDATES_RELATIVE = Path("04-findings/loop-candidates.json")
SUMMARY_RELATIVE = Path("05-audit/research-loop-summary.md")
SCHEMA_VERSION = "1.0"
KIND = "askovo.research-loop"

DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_ACTIONS_PER_ROUND = 3
DEFAULT_MAX_RECORDS = 300
ACTION_LIMIT_CAP = 100
CANDIDATE_SAMPLE_IDS = 20  # display sample in reports
MAX_RECORD_IDS = 200  # stored ids per candidate, so a mapping can cite any record

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
NODE_INTENT = {
    "scene": "problem",
    "user": "problem",
    "pain": "problem",
    "need": "problem",
    "feature": "solution",
    "product": "solution",
    "business": "commercial",
}
CHAIN_INTENT = {"problem": "problem", "solution": "solution", "commercial": "commercial"}
COLLECTED = {"collected"}
FATAL_RESULTS = {"review_expired", "lease_lost"}
GAP_STATES = ("open", "collected", "analyzed", "resolved", "unresolvable")
ASSESS_VERDICTS = ("resolved", "unresolvable")
ANALYSIS_RELATIVE = Path("04-findings/loop-analysis")
EXECUTIONS_RELATIVE = Path("04-findings/loop-executions.json")
EVALUATIONS_RELATIVE = Path("04-findings/loop-evaluations.json")
MAPPINGS_RELATIVE = Path("04-findings/loop-mappings.json")
LOCAL_ANALYSIS_GAP_KINDS = {"unwritten_node", "claim_needs_decision"}
MAPPING_STANCES = ("supports", "contradicts", "contextual")
ANALYSIS_VERSION = "1"
PLACEHOLDERS = {"", "tbd", "todo", "待填写", "待确认", "待补充", "n/a", "na", "none", "null"}

_CLI: Any = None


class LoopError(ValueError):
    """A rule of the loop was violated (state, authorization or envelope)."""


class DesignGateError(LoopError):
    """The study Design gate does not pass, so no collection may start."""


class InterruptedRunError(LoopError):
    """A round stopped mid-action; the journal needs human inspection."""


# --------------------------------------------------------------------------- #
# binding to the CLI module (single source of truth for audit/verdict logic)
# --------------------------------------------------------------------------- #

def bind_cli(module: Any) -> None:
    """Bind the running ``askovo`` module so the loop reuses its audit logic."""
    global _CLI
    _CLI = module


def _load_cli_module() -> Any:
    path = Path(__file__).with_name("askovo.py")
    spec = importlib.util.spec_from_file_location("askovo_cli", path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise LoopError(f"cannot load {path} beside research_loop.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("askovo_cli", module)
    spec.loader.exec_module(module)
    return module


def cli_module() -> Any:
    global _CLI
    if _CLI is None:
        running = sys.modules.get("__main__")
        if running is not None and Path(getattr(running, "__file__", "") or "").name == "askovo.py":
            _CLI = running
        else:
            _CLI = _load_cli_module()
    return _CLI


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _placeholder(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return True
    if text in PLACEHOLDERS:
        return True
    return text.startswith(("tbd", "todo", "待填写", "待确认", "待补充"))


def _seed(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].strip()


def state_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / STATE_RELATIVE


def candidates_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / CANDIDATES_RELATIVE


def evaluations_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / EVALUATIONS_RELATIVE


def mappings_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / MAPPINGS_RELATIVE


def executions_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / EXECUTIONS_RELATIVE


def gap_state(state: Dict[str, Any], key: str) -> str:
    """Return the lifecycle state of one gap.

    States are ``open → collected → analyzed → resolved / unresolvable``.
    A collected candidate is never treated as a resolved gap: only an explicit
    assessment (or a later rule-based check) may close it. Loop state written
    by older versions has no ``gap_states`` map, so candidates fall back to
    ``collected`` instead of ``resolved``.
    """
    entry = (state.get("gap_states") or {}).get(str(key))
    if isinstance(entry, dict) and entry.get("state") in GAP_STATES:
        return str(entry["state"])
    for candidate in state.get("candidates") or []:
        if isinstance(candidate, dict) and str(candidate.get("gap_key")) == str(key):
            return "collected"
    return "open"


def _set_gap_state(state: Dict[str, Any], key: str, new_state: str, **extra: Any) -> None:
    if new_state not in GAP_STATES:
        raise LoopError(f"unknown gap state {new_state!r}")
    states = state.setdefault("gap_states", {})
    entry = states.setdefault(str(key), {})
    entry["state"] = new_state
    entry["updated_at"] = _now()
    for name, value in extra.items():
        if value not in (None, "", [], {}):
            entry[name] = value


def _resolved_keys(state: Dict[str, Any]) -> set:
    """Gaps closed by an assessment; candidates alone never close a gap."""
    return {
        str(key) for key in (state.get("gap_states") or {})
        if isinstance((state.get("gap_states") or {}).get(key), dict)
        and (state.get("gap_states") or {}).get(key, {}).get("state") == "resolved"
    }


def _candidate_entries(state: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    return [
        item for item in state.get("candidates") or []
        if isinstance(item, dict) and str(item.get("gap_key")) == str(key)
    ]


def _gap_state_counts(state: Dict[str, Any], gaps: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {name: 0 for name in GAP_STATES}
    for gap in gaps:
        counts[gap_state(state, str(gap.get("key")))] += 1
    return counts


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:80] or "gap"


def _study(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / "study.json"
    if not path.is_file():
        raise LoopError(f"missing study.json under {study_dir}; run `askovo do` first")
    data = _load_json(path)
    if not isinstance(data, dict):
        raise LoopError("study.json must be an object")
    return data


def _reasoning(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / "04-findings" / "product-reasoning.json"
    if not path.is_file():
        raise LoopError("missing product-reasoning chain; run `askovo chain` first")
    data = _load_json(path)
    if not isinstance(data, dict):
        raise LoopError("product-reasoning.json must be an object")
    return data


def _save(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".research-loop-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _lock(study_dir: Path):
    """POSIX cross-process lock; Windows keeps the state machine without fcntl."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows fallback
        fcntl = None
    if fcntl is None:
        yield
        return
    path = state_path(study_dir).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LoopError("research loop is already executing")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #

def _configured_fixtures(study: Dict[str, Any]) -> Dict[str, str]:
    config = study.get("research_loop")
    if not isinstance(config, dict):
        return {}
    fixtures = config.get("fixtures")
    if not isinstance(fixtures, dict):
        return {}
    return {
        str(name).strip().lower(): str(value)
        for name, value in fixtures.items()
        if isinstance(value, str) and value.strip()
    }


def eligible_sources(study_dir: Path) -> List[Dict[str, Any]]:
    """Return platforms the study may collect from right now.

    A platform qualifies only when it is named in ``study.scope.allowed_sources``,
    exists in the platform catalog, is not blocked, and has either an enabled
    bundled adapter or an explicit offline fixture. Free-text allowed sources
    ("Synthetic interviews") are design language, not platforms.
    """
    study = _study(study_dir)
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    allowed = scope.get("allowed_sources") if isinstance(scope.get("allowed_sources"), list) else []
    index = sure_engine.platform_index()
    fixtures = _configured_fixtures(study)
    adapters = study.get("source_adapters") if isinstance(study.get("source_adapters"), dict) else {}
    sources: List[Dict[str, Any]] = []
    for raw in allowed:
        name = str(raw or "").strip().lower()
        entry = index.get(name)
        if entry is None or entry.get("decision") == "blocked":
            continue
        fixture_rel = fixtures.get(name)
        if fixture_rel:
            candidate = (Path(study_dir).resolve() / fixture_rel).resolve()
            try:
                candidate.relative_to(Path(study_dir).resolve())
            except ValueError:
                continue
            if candidate.is_file():
                sources.append({"platform": name, "mode": "fixture", "fixture": str(candidate),
                                "reason": "offline authorized export"})
            continue
        adapter = adapters.get(name) if isinstance(adapters, dict) else None
        if isinstance(adapter, dict) and adapter.get("enabled") and entry.get("adapter") in ("github", "reddit"):
            sources.append({"platform": name, "mode": "live", "fixture": None,
                            "reason": f"enabled {entry.get('adapter')} adapter"})
    return sources


def _source_blockers(study_dir: Path) -> List[Dict[str, Any]]:
    """Explain why an allowed platform cannot be used, without inventing a route."""
    study = _study(study_dir)
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    allowed = scope.get("allowed_sources") if isinstance(scope.get("allowed_sources"), list) else []
    index = sure_engine.platform_index()
    fixtures = _configured_fixtures(study)
    adapters = study.get("source_adapters") if isinstance(study.get("source_adapters"), dict) else {}
    blockers: List[Dict[str, Any]] = []
    for raw in allowed:
        name = str(raw or "").strip().lower()
        entry = index.get(name)
        if entry is None:
            continue
        if entry.get("decision") == "blocked":
            blockers.append({
                "platform": name,
                "reason": "platform is blocked by the catalog: " + str(entry.get("notes") or "policy"),
            })
            continue
        if fixtures.get(name):
            continue
        adapter = adapters.get(name) if isinstance(adapters, dict) else None
        if not isinstance(adapter, dict) or not adapter.get("enabled"):
            blockers.append({
                "platform": name,
                "reason": "no enabled adapter for live collection; import an authorized export instead",
            })
        elif entry.get("adapter") not in ("github", "reddit"):
            blockers.append({
                "platform": name,
                "reason": f"{entry.get('name') or name} has no bundled collector; import an authorized export",
            })
    return blockers


# --------------------------------------------------------------------------- #
# gap detection
# --------------------------------------------------------------------------- #

def _query_for(seed: Any, intent: str) -> str:
    """Compose a deterministic query: the study's own wording plus an intent hint."""
    base = _seed(seed)
    if not base:
        return ""
    hints = {
        "problem": ("problem", "问题"),
        "solution": ("alternative workaround", "替代方案"),
        "commercial": ("pricing subscription", "定价 付费"),
        "counter": ("complaint refund cancel", "投诉 退款 取消"),
    }
    english, chinese = hints.get(intent, ("", ""))
    hint = chinese if re.search(r"[\u4e00-\u9fff]", base) else english
    return _seed(f"{base} {hint}", 120) if hint else base


def _claim_gaps(payload: Dict[str, Any], require_counter: bool) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "")
        verdict = str(claim.get("verdict") or "")
        chains = claim.get("chains") if isinstance(claim.get("chains"), dict) else {}
        missing = [
            name for name in ("problem", "solution", "commercial")
            if not (chains.get(name) or {}).get("ok")
        ]
        seed_source = _seed(claim.get("title")) or _seed(claim.get("next_test"))
        reasons = "；".join(str(item) for item in claim.get("reasons") or []) or "证据链未闭合"
        if verdict in ("open", "exceeds_evidence"):
            if missing:
                for name in missing:
                    intent = CHAIN_INTENT[name]
                    gaps.append({
                        "key": f"claim:{claim_id}:{intent}",
                        "kind": "exceeds_evidence" if verdict == "exceeds_evidence" else "open_claim",
                        "severity": "high" if verdict == "exceeds_evidence" else "medium",
                        "intent": intent,
                        "judgment_id": claim_id,
                        "detail": (
                            f"{claim_id} {'声称已验证但超出证据' if verdict == 'exceeds_evidence' else '仍未定'}"
                            f"，缺 {name} 链证据：{reasons}"
                        ),
                        "query_seed": _query_for(seed_source, intent),
                    })
            elif require_counter and not claim.get("counter_evidence"):
                gaps.append({
                    "key": f"claim:{claim_id}:counter",
                    "kind": "missing_counter",
                    "severity": "high" if verdict == "exceeds_evidence" else "medium",
                    "intent": "counter",
                    "judgment_id": claim_id,
                    "detail": f"{claim_id} 三条链已齐，但无反证",
                    "query_seed": _query_for(seed_source, "counter"),
                })
            else:
                gaps.append({
                    "key": f"claim:{claim_id}:decision",
                    "kind": "claim_needs_decision",
                    "severity": "low",
                    "intent": "counter",
                    "judgment_id": claim_id,
                    "detail": f"{claim_id} 证据链与反证已齐，缺的是判断写作而不是采集",
                    "query_seed": "",
                    "actionable": False,
                })
        elif verdict == "supported" and require_counter and not claim.get("counter_evidence"):
            gaps.append({
                "key": f"claim:{claim_id}:counter",
                "kind": "missing_counter",
                "severity": "high",
                "intent": "counter",
                "judgment_id": claim_id,
                "detail": f"{claim_id} 已通过审计，但没有反证记录",
                "query_seed": _query_for(seed_source, "counter"),
            })
    return gaps


def _node_gaps(study_dir: Path) -> List[Dict[str, Any]]:
    data = _reasoning(study_dir)
    chains = data.get("chains") if isinstance(data.get("chains"), list) else []
    gaps: List[Dict[str, Any]] = []
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        chain_id = str(chain.get("id") or "chain")
        nodes = chain.get("nodes") if isinstance(chain.get("nodes"), dict) else {}
        for node_name in sure_engine.REASONING_NODES:
            body = nodes.get(node_name)
            if not isinstance(body, dict):
                continue
            status = str(body.get("status") or "")
            if status in ("validated", "rejected", "deprioritized"):
                continue
            evidence_ids = [value for value in (body.get("evidence_ids") or []) if str(value)]
            statement = body.get("statement")
            intent = NODE_INTENT.get(node_name, "problem")
            if _placeholder(statement):
                gaps.append({
                    "key": f"node:{chain_id}.{node_name}:write",
                    "kind": "unwritten_node",
                    "severity": "medium",
                    "intent": intent,
                    "chain_id": chain_id,
                    "node": node_name,
                    "detail": f"{chain_id}.{node_label(node_name)} 仍是占位文本，需要先写出判断",
                    "query_seed": "",
                    "actionable": False,
                })
                continue
            if evidence_ids:
                continue
            gaps.append({
                "key": f"node:{chain_id}.{node_name}:{intent}",
                "kind": "node_without_evidence",
                "severity": "medium" if node_name in ("pain", "need", "business") else "low",
                "intent": intent,
                "chain_id": chain_id,
                "node": node_name,
                "detail": f"{chain_id}.{node_label(node_name)} 是 {status or '未知'}，没有任何证据",
                "query_seed": _query_for(statement, intent),
            })
    return gaps


def node_label(node: str) -> str:
    return str(sure_engine.REASONING_NODE_LABELS.get(node, node))


def _coverage_gaps(study: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    gates = study.get("quality_gates") if isinstance(study.get("quality_gates"), dict) else {}
    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    gate_report = signals.get("gate_report") if isinstance(signals.get("gate_report"), dict) else {}

    family = gate_report.get("max_source_family_share")
    if isinstance(family, dict) and family.get("status") == "fail":
        share = float(family.get("observed") or 0.0)
        gaps.append({
            "key": "coverage:source_family_share",
            "kind": "source_concentration",
            "severity": "medium",
            "intent": "problem",
            "detail": (
                f"单一来源占比 {share:.0%} 超过上限 {float(family.get('limit') or 0):.0%}；"
                "再多同源材料不解决抽样偏差"
            ),
            "query_seed": _seed(
                (study.get("decision") or {}).get("question")
                if isinstance(study.get("decision"), dict) else ""
            ),
        })

    roles = gate_report.get("required_corpus_roles")
    if isinstance(roles, dict):
        missing = sorted(name for name, item in roles.items()
                         if isinstance(item, dict) and item.get("status") == "fail")
        if missing:
            gaps.append({
                "key": "coverage:corpus_roles",
                "kind": "missing_corpus_role",
                "severity": "low",
                "intent": "problem",
                "detail": "缺语料角色：" + ", ".join(missing) + "；角色缺口需要新设计材料，不是重复采集",
                "query_seed": "",
                "actionable": False,
            })
    return gaps


def _local_analysis_inputs(study_dir: Path) -> List[str]:
    """Existing local inputs for the established descriptive analysis function.

    No network or collector is consulted. A file qualifies only when it contains
    at least one JSON object; invalid rows remain visible to ``analyze_study``.
    """
    root = Path(study_dir).resolve()
    refs: List[str] = []
    for relative in ("02-data/normalized.jsonl", "02-data/evidence.jsonl"):
        path = root / relative
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    refs.append(relative)
                    break
        except OSError:
            continue
    return refs


def detect_gaps(study_dir: Path) -> List[Dict[str, Any]]:
    """Return every open gap, deterministically ordered and explained."""
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    payload = cli_module().audit_payload(study_dir)
    gates = study.get("quality_gates") if isinstance(study.get("quality_gates"), dict) else {}
    require_counter = bool(gates.get("require_counter_evidence_for_validated", True))

    gaps: List[Dict[str, Any]] = []
    gaps.extend(_claim_gaps(payload, require_counter))
    gaps.extend(_node_gaps(study_dir))
    gaps.extend(_coverage_gaps(study, payload))
    for blocker in _source_blockers(study_dir):
        gaps.append({
            "key": f"source:{blocker['platform']}:blocked",
            "kind": "blocked_source",
            "severity": "low",
            "intent": "problem",
            "detail": f"{blocker['platform']} 不可用：{blocker['reason']}",
            "query_seed": "",
            "actionable": False,
        })

    sources = eligible_sources(study_dir)
    for gap in gaps:
        gap.setdefault("actionable", True)
        if gap["actionable"] and (not sources or not gap.get("query_seed")):
            gap["actionable"] = False
            if not sources:
                gap["blocked_reason"] = "no eligible source: declare allowed_sources and enable an adapter or fixture"
            else:
                gap["blocked_reason"] = "no query seed: the claim or node still needs its own wording"

    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for gap in gaps:
        if gap["key"] in seen:
            continue
        seen.add(gap["key"])
        unique.append(gap)
    unique.sort(key=lambda item: (
        SEVERITY_ORDER.get(str(item.get("severity")), 9),
        str(item.get("kind")),
        str(item.get("key")),
    ))
    local_inputs = _local_analysis_inputs(study_dir)
    for index, gap in enumerate(unique, start=1):
        gap["id"] = f"G{index:02d}"
        # These gaps call for structuring what is already present, not more
        # collection. The same CLI/MCP loop can execute this local analysis.
        gap["analysis_actionable"] = bool(
            local_inputs and str(gap.get("kind")) in LOCAL_ANALYSIS_GAP_KINDS
        )
        gap["analysis_input_refs"] = local_inputs if gap["analysis_actionable"] else []
        candidates = research_action_candidates(gap, study, sources)
        gap["research_action_candidates"] = candidates
        gap["next_best_action"] = candidates[0]
    return unique


RESEARCH_ACTION_KINDS = ("collect", "analyze", "experiment", "request_external_evidence", "stop")

# Research modes change which action is usually most decisive. They never turn
# an authorization candidate into an automatically executable action; they only
# reweight the transparent planning heuristic.
MODE_ACTION_WEIGHTS = {
    "discover": {"collect": 1.15, "analyze": 0.90, "experiment": 1.05,
                 "request_external_evidence": 1.00},
    "validate": {"collect": 0.90, "analyze": 0.95, "experiment": 1.20,
                 "request_external_evidence": 1.15},
    "optimize": {"collect": 0.85, "analyze": 1.25, "experiment": 0.95,
                 "request_external_evidence": 1.00},
}
MODE_RATIONALE = {
    "discover": "Discover：先扩大机会空间、替代方案与目标人群样本",
    "validate": "Validate：优先能推翻当前假设的行为、实验或外部证据",
    "optimize": "Optimize：先诊断已有数据断点、替代解释与上游假设",
}
_ACTION_ORDER = {name: index for index, name in enumerate(RESEARCH_ACTION_KINDS)}
STOP_DECISION_KIND = "askovo.stop-decision"
STOP_DECISION_SCHEMA = "1.0"


@dataclass(frozen=True)
class StopDecision:
    """Independent, declaration-based stop gate; never a positive utility score.

    All three criteria must be explicit. Unknown or missing criteria mean keep
    researching (or choose another candidate), never "stop for stop's sake".
    The declarations and their basis come from the study/gap contract; this
    class does not invent measured uncertainty, money, probability or risk.
    """

    evidence_sufficient_for_decision: Optional[bool]
    remaining_unknowns_can_change_decision: Optional[bool]
    continued_research_marginal_value_not_worth_cost_or_risk: Optional[bool]
    basis: Dict[str, Dict[str, str]]
    source_ref: str

    @property
    def should_stop(self) -> bool:
        return (
            self.evidence_sufficient_for_decision is True
            and self.remaining_unknowns_can_change_decision is False
            and self.continued_research_marginal_value_not_worth_cost_or_risk is True
        )

    def as_dict(self) -> Dict[str, Any]:
        criteria = {
            "evidence_sufficient_for_decision": self.evidence_sufficient_for_decision,
            "remaining_unknowns_can_change_decision": self.remaining_unknowns_can_change_decision,
            "continued_research_marginal_value_not_worth_cost_or_risk": (
                self.continued_research_marginal_value_not_worth_cost_or_risk
            ),
        }
        expected = {
            "evidence_sufficient_for_decision": True,
            "remaining_unknowns_can_change_decision": False,
            "continued_research_marginal_value_not_worth_cost_or_risk": True,
        }
        blocking = [
            f"{name} must be {str(value).lower()} (recorded: {criteria[name]})"
            for name, value in expected.items() if criteria[name] is not value
        ]
        return {
            "kind": STOP_DECISION_KIND,
            "schema_version": STOP_DECISION_SCHEMA,
            "should_stop": self.should_stop,
            "status": "stop" if self.should_stop else "not_eligible",
            "priority": "highest" if self.should_stop else "not_eligible",
            "selection_rule": (
                "Stop wins only when evidence is sufficient, remaining unknowns cannot change "
                "the decision, and continued research value is declared below its cost/risk."
            ),
            "scoring": "independent_gate_not_a_positive_utility_score",
            "source_ref": self.source_ref,
            "criteria": {
                name: {
                    "value": value,
                    "required": expected[name],
                    "met": value is expected[name],
                    **self.basis.get(name, {}),
                }
                for name, value in criteria.items()
            },
            "blocking_reasons": blocking,
            "boundary": (
                "Declarations are transparent decision inputs, not measured value, causal proof "
                "or automatic evidence validation. Record restart conditions with the stop decision."
            ),
        }


def _stop_decision(gap: Dict[str, Any], study: Dict[str, Any]) -> StopDecision:
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    raw: Any = None
    source_ref = "study.decision.stop_decision"
    if isinstance(decision.get("stop_decision"), dict):
        raw = decision.get("stop_decision")
    if isinstance(study.get("stop_decision"), dict):
        raw = study.get("stop_decision")
        source_ref = "study.stop_decision"
    if isinstance(gap.get("stop_decision"), dict):
        raw = gap.get("stop_decision")
        source_ref = f"gaps[key={gap.get('key')}].stop_decision"
    raw = raw if isinstance(raw, dict) else {}
    nested = raw.get("criteria") if isinstance(raw.get("criteria"), dict) else {}
    basis_raw = raw.get("basis") if isinstance(raw.get("basis"), dict) else {}

    def declared(name: str) -> Optional[bool]:
        value = nested.get(name, raw.get(name))
        return value if isinstance(value, bool) else None

    evidence = declared("evidence_sufficient_for_decision")
    unknowns = declared("remaining_unknowns_can_change_decision")
    if unknowns is None:
        # Readable alias for contracts that phrase the negative criterion directly.
        alias = nested.get("remaining_unknowns_would_not_change_decision",
                           raw.get("remaining_unknowns_would_not_change_decision"))
        if isinstance(alias, bool):
            unknowns = not alias
    marginal = declared("continued_research_marginal_value_not_worth_cost_or_risk")
    if marginal is None:
        alias = nested.get("continued_research_marginal_value", raw.get("continued_research_marginal_value"))
        if isinstance(alias, str) and alias.strip().casefold() in {
            "below_cost_or_risk", "below_cost/risk", "not_worth_cost_or_risk",
        }:
            marginal = True

    names = (
        "evidence_sufficient_for_decision",
        "remaining_unknowns_can_change_decision",
        "continued_research_marginal_value_not_worth_cost_or_risk",
    )
    basis: Dict[str, Dict[str, str]] = {}
    for name in names:
        entry = basis_raw.get(name) if isinstance(basis_raw.get(name), dict) else {}
        rationale = entry.get("rationale") or raw.get(name + "_basis") or "not_declared"
        restart = entry.get("restart_condition") or raw.get("restart_condition") or ""
        basis[name] = {
            "rationale": str(rationale),
            "basis_ref": str(entry.get("basis_ref") or source_ref),
            "restart_condition": str(restart),
        }
    return StopDecision(evidence, unknowns, marginal, basis, source_ref)


def _cost_level(cost: float) -> str:
    if cost <= 0.15:
        return "low"
    if cost <= 0.40:
        return "medium"
    return "high"


def _action_profile(
    action: str,
    gap: Dict[str, Any],
    *,
    public_collection: bool,
) -> tuple[float, float, float, str]:
    """Relative planning heuristics, never empirical effect or value estimates."""
    kind = str(gap.get("kind") or "")
    intent = str(gap.get("intent") or "problem")
    commercial_public = intent == "commercial" and public_collection
    if action == "collect":
        if commercial_public:
            return 0.15, 0.45, 0.20, "继续采集公开评论无法观察真实报价接受、支付或交付，边际决策价值低"
        return 0.85, 0.45, 0.85, "在已授权来源内补齐直接观察；仍须人工定级与语义复核"
    if action == "analyze":
        if kind in {"unwritten_node", "claim_needs_decision"}:
            return 0.90, 0.15, 0.85, "先把已有材料整理成可证伪节点/判断与反例，不自动生成 validated 文本"
        return 0.45, 0.15, 0.55, "先分析已有候选、重复、反例与覆盖，避免在未知边际收益时继续加量"
    if action == "experiment":
        if intent == "commercial":
            return 0.95, 0.55, 0.95, "用真实报价、可拒绝的付费试点或交付实验观察行为，并登记选择偏差"
        if str(gap.get("node") or "") in {"feature", "product"}:
            return 0.75, 0.60, 0.80, "用任务/原型实验检验方案接受与关键推理，不把接受当付费或发布就绪"
        return 0.55, 0.65, 0.55, "仅当明确假设、分母与停止线后，实验才可能改变当前决定"
    if action == "request_external_evidence":
        if intent == "commercial":
            return 0.75, 0.45, 0.75, "请求授权的一方报价、订单、支付、续费或交付记录，不用公开评论替代"
        return 0.80, 0.35, 0.80, "当前来源不可用或样本形成机制不适配时，请求有权使用的外部材料"
    raise ValueError("stop is selected by StopDecision, not by the positive action heuristic")


def research_action_candidates(
    gap: Dict[str, Any],
    study: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compare next-action candidates without collapsing stop into their score.

    Non-stop scores are transparent relative planning heuristics, never measured
    uncertainty, money, probability or business value. Collect keeps its existing
    authorization route. Analyze may run only when the gap exposes an existing
    local/candidate input; experiment and external evidence remain authorization
    candidates. Stop is selected by an independent :class:`StopDecision` gate.
    """
    decision = study.get("decision") if isinstance(study.get("decision"), dict) else {}
    decision_question = str(decision.get("question") or study.get("title") or "当前产品/商业决定")
    intent = str(gap.get("intent") or "problem")
    question = str(gap.get("query_seed") or gap.get("detail") or decision_question)
    public_collection = any(
        str(item.get("platform") or "") in {"reddit", "github", "x", "youtube", "amazon"}
        for item in sources
    )
    selected: List[Dict[str, Any]] = []
    catalog = sure_engine.methods()
    for method_id in study.get("selected_methods") or []:
        method = catalog.get(str(method_id))
        if method:
            selected.append(sure_engine._method_view(method))
    mode = str((study.get("research_mode") or {}).get("mode") or "")
    mode_weight = MODE_ACTION_WEIGHTS.get(mode, {})
    candidates: List[Dict[str, Any]] = []
    for action in RESEARCH_ACTION_KINDS:
        if action == "stop":
            continue
        reduction, cost, decision_change, rationale = _action_profile(action, gap, public_collection=public_collection)
        # Without a collection route, external evidence is more useful than a
        # nominal collect task; commercial experiments still outrank public text.
        if action == "collect" and not gap.get("actionable"):
            reduction = min(reduction, 0.10)
            decision_change = min(decision_change, 0.20)
            rationale = "当前缺口没有可自动执行的合规采集路线；保留为候选，不进入既有 loop run"
        weight = float(mode_weight.get(action, 1.0))
        score = round(((reduction * decision_change) / (cost + 0.10)) * weight, 4)
        if mode and weight != 1.0:
            rationale = f"{MODE_RATIONALE.get(mode, mode)}；{rationale}"
        method_selection = sure_engine.research_method_selection(
            question,
            selected,
            action=action,
            intent=intent,
            sources=sources if action in {"collect", "analyze"} else [],
        )
        executable = (
            action == "collect" and bool(gap.get("actionable") and gap.get("query_seed"))
        ) or (
            action == "analyze" and bool(gap.get("analysis_actionable"))
        )
        candidates.append({
            "action": action,
            "task": f"{action}：{question}",
            "gap_key": str(gap.get("key") or ""),
            "expected_uncertainty_reduction": reduction,
            "cost": cost,
            "cost_level": _cost_level(cost),
            "decision_change_potential": decision_change,
            "decision_it_can_change": decision_question,
            "priority_score": score,
            "scoring_rule": "(expected_uncertainty_reduction × decision_change_potential) / (cost + 0.10) × mode_weight; relative heuristic only",
            "research_mode": mode or None,
            "mode_weight": weight,
            "rationale": rationale,
            "candidate_only": True,
            "executable_by_existing_loop": executable,
            "execution_constraints": {
                "network": "authorized_collect_only" if action == "collect" else "none" if action == "analyze" else "requires_separate_authorization",
                "automatic_execution": executable,
                "candidate_material_remains_unvalidated": True,
            },
            "method_selection": method_selection,
            "validated_status_changed": False,
        })
    stop = _stop_decision(gap, study).as_dict()
    candidates.append({
        "action": "stop",
        "task": f"stop：{decision_question}",
        "gap_key": str(gap.get("key") or ""),
        "expected_uncertainty_reduction": None,
        "cost": None,
        "cost_level": "not_scored",
        "decision_change_potential": None,
        "decision_it_can_change": decision_question,
        "priority_score": None,
        "scoring_rule": "independent StopDecision; no positive utility score",
        "rationale": (
            "三项停止条件均有明确声明且同时满足，stop 可优先于其他动作"
            if stop["should_stop"] else
            "停止条件未同时满足；不能为了停止而停止，保留其他动作候选"
        ),
        "candidate_only": True,
        "executable_by_existing_loop": False,
        "stop_decision": stop,
        "method_selection": sure_engine.research_method_selection(
            question, selected, action="stop", intent=intent, sources=[],
        ),
        "validated_status_changed": False,
    })

    def candidate_order(item: Dict[str, Any]) -> tuple:
        if item["action"] == "stop":
            return (0 if item["stop_decision"]["should_stop"] else 2, 0.0, 0.0, _ACTION_ORDER["stop"])
        return (1, -float(item["priority_score"]), float(item["cost"]), _ACTION_ORDER[item["action"]])

    candidates.sort(key=candidate_order)
    return candidates


def next_best_actions(gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the winning candidate per gap without hiding the comparison set."""
    result: List[Dict[str, Any]] = []
    for gap in gaps:
        best = gap.get("next_best_action")
        if not isinstance(best, dict):
            continue
        result.append({
            "gap_id": gap.get("id"),
            "gap_key": gap.get("key"),
            "gap_kind": gap.get("kind"),
            "node": gap.get("node"),
            "actionable_for_collection": bool(gap.get("actionable")),
            "actionable_for_local_analysis": bool(gap.get("analysis_actionable")),
            "candidate": best,
            "compared_actions": [item.get("action") for item in gap.get("research_action_candidates") or []],
        })
    return result


# --------------------------------------------------------------------------- #
# planning and authorization
# --------------------------------------------------------------------------- #

def build_actions(
    gaps: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    *,
    attempted: Dict[str, Any],
    limit_actions: int,
    remaining_records: int,
    gap_states: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Plan typed actions: offline analysis first, then authorized collection.

    Analysis never consumes the record budget and never closes a gap on its own.
    It describes either existing local study data or ``collected`` loop material
    and records a follow-up human revision/assessment requirement. Collection
    only runs for gaps whose state is still ``open`` inside the same envelope.
    """
    states = gap_states or {}
    actions: List[Dict[str, Any]] = []
    seen_queries: set[str] = set()

    # 1. analyze existing local study data for writing/decision gaps. This is a
    # controlled, offline action and does not require a collection route.
    for gap in gaps:
        if len(actions) >= limit_actions:
            break
        if not gap.get("analysis_actionable"):
            continue
        if states.get(str(gap["key"]), "open") != "open":
            continue
        attempt_key = f"existing-analysis|{gap['key']}"
        if attempt_key in attempted:
            continue
        actions.append({
            "id": "",
            "kind": "analyze",
            "gap_key": gap["key"],
            "gap_kind": gap["kind"],
            "node": gap.get("node"),
            "judgment_id": gap.get("judgment_id"),
            "intent": gap.get("intent"),
            "question": str(gap.get("query_seed") or gap.get("detail") or ""),
            "analysis_input_refs": list(gap.get("analysis_input_refs") or []),
            "analysis_mode": "deterministic",
            "analysis_scope": "existing_study_data",
            "attempt_key": attempt_key,
            "state": "planned",
            "result": None,
        })

    # 2. deterministic analysis for gaps that already have loop candidates
    for gap in gaps:
        if len(actions) >= limit_actions:
            break
        if not gap.get("actionable"):
            continue
        if states.get(str(gap["key"]), "open") != "collected":
            continue
        attempt_key = f"analysis|{gap['key']}"
        if attempt_key in attempted:
            continue
        actions.append({
            "id": "",
            "kind": "analyze",
            "gap_key": gap["key"],
            "gap_kind": gap["kind"],
            "node": gap.get("node"),
            "judgment_id": gap.get("judgment_id"),
            "intent": gap.get("intent"),
            "analysis_mode": "deterministic",
            "analysis_scope": "loop_candidates",
            "attempt_key": attempt_key,
            "state": "planned",
            "result": None,
        })

    # 3. collection for gaps that are still open, under the original envelope
    for gap in gaps:
        if len(actions) >= limit_actions or remaining_records <= 0:
            break
        if not gap.get("actionable") or not gap.get("query_seed"):
            continue
        if states.get(str(gap["key"]), "open") != "open":
            continue
        for source in sources:
            if len(actions) >= limit_actions or remaining_records <= 0:
                break
            query = _seed(gap["query_seed"], 120)
            attempt_key = f"{source['platform']}|{gap['key']}|{query.casefold()}"
            query_key = f"{source['platform']}|{query.casefold()}"
            if attempt_key in attempted or query_key in seen_queries:
                continue
            limit = min(50, remaining_records, ACTION_LIMIT_CAP)
            if limit < 1:
                continue
            actions.append({
                "id": "",
                "kind": "collect",
                "gap_key": gap["key"],
                "gap_kind": gap["kind"],
                "node": gap.get("node"),
                "judgment_id": gap.get("judgment_id"),
                "intent": gap.get("intent"),
                "platform": source["platform"],
                "mode": source["mode"],
                "fixture": source.get("fixture"),
                "query": query,
                "limit": limit,
                "attempt_key": attempt_key,
                "state": "planned",
                "result": None,
            })
            seen_queries.add(query_key)
            remaining_records -= limit
    return actions


def _envelope(
    sources: List[Dict[str, Any]],
    *,
    max_rounds: int,
    max_actions_per_round: int,
    max_records_total: int,
) -> Dict[str, Any]:
    if not 1 <= max_rounds <= 20:
        raise LoopError("max_rounds must be 1..20")
    if not 1 <= max_actions_per_round <= 20:
        raise LoopError("max_actions_per_round must be 1..20")
    if not 1 <= max_records_total <= 5000:
        raise LoopError("max_records_total must be 1..5000")
    return {
        "max_rounds": max_rounds,
        "max_actions_per_round": max_actions_per_round,
        "max_records_total": max_records_total,
        "max_records_per_action": ACTION_LIMIT_CAP,
        "allowed_platforms": sorted({source["platform"] for source in sources}),
        "platform_modes": {source["platform"]: source["mode"] for source in sources},
        "scope": "envelope: gap-derived queries on allowed platforms only",
    }


def plan(
    study_dir: Path,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_actions_per_round: int = DEFAULT_MAX_ACTIONS_PER_ROUND,
    max_records_total: int = DEFAULT_MAX_RECORDS,
    reset: bool = False,
) -> Dict[str, Any]:
    """Detect gaps, pick eligible sources and write an unauthorized plan."""
    with _lock(study_dir):
        study_dir = Path(study_dir).resolve()
        study = _study(study_dir)
        _reasoning(study_dir)
        existing = load_state_or_none(study_dir)
        if existing is not None and not reset:
            if existing.get("status") in ("authorized", "running", "needs_review"):
                raise LoopError(
                    "a research loop already exists or needs review; inspect `askovo loop status` "
                    "or pass --reset to replace it")
            raise LoopError("research loop state already exists; pass --reset to replan")
        sources = eligible_sources(study_dir)
        gaps = detect_gaps(study_dir)
        envelope = _envelope(
            sources,
            max_rounds=max_rounds,
            max_actions_per_round=max_actions_per_round,
            max_records_total=max_records_total,
        )
        state = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "study_id": str(study.get("study_id") or ""),
            "loop_id": "loop-" + datetime.now().strftime("%Y%m%dT%H%M%S"),
            "created_at": _now(),
            "updated_at": _now(),
            "status": "planned",
            "stop_reason": None,
            "authorization": None,
            "envelope": envelope,
            "sources": sources,
            "research_mode": study.get("research_mode") or {},
            "gaps": gaps,
            "next_best_actions": next_best_actions(gaps),
            "gap_states": {},
            "rounds": [],
            "candidates": [],
            "execution_records": [],
            "evaluations": [],
            "mappings": [],
            "attempted": {},
            "totals": {"records": 0, "actions": 0, "blocked": 0},
        }
        _save(state_path(study_dir), state)
        _save(candidates_path(study_dir), _candidates_document(state))
        return state


def load_state_or_none(study_dir: Path) -> Optional[Dict[str, Any]]:
    path = state_path(study_dir)
    if not path.is_file():
        return None
    data = _load_json(path)
    return data if isinstance(data, dict) else None


def load_state(study_dir: Path) -> Dict[str, Any]:
    state = load_state_or_none(study_dir)
    if state is None:
        raise LoopError("no research loop state; create one with `askovo loop plan`")
    return state


def _check_authorization(state: Dict[str, Any]) -> None:
    auth = state.get("authorization")
    if not isinstance(auth, dict) or not auth.get("by"):
        raise LoopError("research loop is not authorized; run `askovo loop authorize STUDY --by NAME`")
    if auth.get("envelope_sha256") != _sha(state.get("envelope")):
        raise LoopError("authorization is stale: the envelope changed; re-authorize it")


def authorize(study_dir: Path, *, by: str) -> Dict[str, Any]:
    """Record a named operator's authorization of the envelope, not of a query list."""
    if not str(by or "").strip():
        raise LoopError("authorization requires a named operator")
    with _lock(study_dir):
        state = load_state(study_dir)
        if state.get("status") in ("running",):
            raise LoopError("cannot authorize while the loop is running")
        state["authorization"] = {
            "by": str(by).strip(),
            "at": _now(),
            "envelope_sha256": _sha(state.get("envelope")),
            "scope": "authorized envelope: allowed platforms, per-action limit and budgets",
        }
        state["status"] = "authorized"
        state["updated_at"] = _now()
        _save(state_path(study_dir), state)
        return state


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #

def _validate_action(study_dir: Path, state: Dict[str, Any], action: Dict[str, Any]) -> None:
    envelope = state.get("envelope") if isinstance(state.get("envelope"), dict) else {}
    gap_keys = {str(gap.get("key")) for gap in state.get("gaps") or [] if isinstance(gap, dict)}
    if str(action.get("gap_key")) not in gap_keys:
        raise LoopError("action does not map to a recorded gap")
    kind = str(action.get("kind") or "collect")
    if kind == "analyze":
        if action.get("analysis_mode") != "deterministic":
            raise LoopError("only deterministic analysis is authorized inside the envelope")
        scope = str(action.get("analysis_scope") or "loop_candidates")
        if scope not in {"existing_study_data", "loop_candidates"}:
            raise LoopError(f"unknown analysis scope {scope!r}")
        if scope == "existing_study_data":
            refs = action.get("analysis_input_refs")
            if not isinstance(refs, list) or not refs or any(
                ref not in {"02-data/normalized.jsonl", "02-data/evidence.jsonl"} for ref in refs
            ):
                raise LoopError("existing study analysis requires declared local JSONL inputs")
        return
    if kind != "collect":
        raise LoopError(f"unknown action kind {kind!r}")
    platform = str(action.get("platform") or "")
    if platform not in (envelope.get("allowed_platforms") or []):
        raise LoopError(f"action platform {platform!r} is outside the authorized envelope")
    if envelope.get("platform_modes", {}).get(platform) != action.get("mode"):
        raise LoopError(f"action mode for {platform!r} differs from the authorized envelope")
    limit = action.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= ACTION_LIMIT_CAP:
        raise LoopError("action limit is outside the authorized per-action cap")
    if not str(action.get("query") or "").strip():
        raise LoopError("action has no query")
    if action.get("fixture"):
        candidate = Path(str(action["fixture"])).resolve()
        try:
            candidate.relative_to(Path(study_dir).resolve())
        except ValueError:
            raise LoopError("fixture must stay inside the study directory")
        if action.get("mode") != "fixture" or not candidate.is_file():
            raise LoopError("fixture action is missing its authorized export")


def _record_ids(raw_file: Optional[str], limit: int = MAX_RECORD_IDS) -> List[str]:
    if not raw_file:
        return []
    path = Path(raw_file)
    if not path.is_file():
        return []
    ids: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = str(item.get("source_record_id") or item.get("record_id") or "")
            if value:
                ids.append(value)
            if len(ids) >= limit:
                break
    except OSError:
        return ids
    return ids


def _candidates_document(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "askovo.research-loop-candidates",
        "study_id": state.get("study_id"),
        "loop_id": state.get("loop_id"),
        "generated_at": _now(),
        "boundary": (
            "Candidate material only. The loop never assigns an evidence level and never links "
            "a record to a judgment; a human reviews and registers the evidence."
        ),
        "candidates": list(state.get("candidates") or []),
    }


def gap_counts(gaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    for gap in gaps:
        by_kind[str(gap.get("kind"))] = by_kind.get(str(gap.get("kind")), 0) + 1
        by_severity[str(gap.get("severity"))] = by_severity.get(str(gap.get("severity")), 0) + 1
    return {
        "total": len(gaps),
        "actionable": sum(1 for gap in gaps if gap.get("actionable")),
        "by_kind": by_kind,
        "by_severity": by_severity,
    }


def _covered_keys(state: Dict[str, Any]) -> set:
    """Backward-compatible name for the set of *resolved* gaps.

    Older callers used this to mean "a candidate was collected"; that is exactly
    the conflation this module now refuses. Only an assessment closes a gap.
    """
    return _resolved_keys(state)


def run(study_dir: Path) -> Dict[str, Any]:
    """Execute rounds inside the authorized envelope until exhausted or covered."""
    with _lock(study_dir):
        return _run(study_dir)


def _run(study_dir: Path) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    state = load_state(study_dir)
    _check_authorization(state)
    if state.get("status") == "running":
        state["status"] = "needs_review"
        state["stop_reason"] = "interrupted_run"
        _save(state_path(study_dir), state)
        raise InterruptedRunError(
            "a previous round was interrupted while an action was running; inspect the collected "
            "files and the journal before planning a new loop")
    if state.get("status") == "needs_review":
        raise InterruptedRunError(
            "the loop stopped mid-action and still needs review; inspect "
            "04-findings/research-loop.json and the collected files, then run "
            "`askovo loop plan --reset`")
    # Offline analysis is useful precisely while a chain still needs writing.
    # The Design gate is enforced immediately before each collection action below.
    state["status"] = "running"
    state["updated_at"] = _now()
    _save(state_path(study_dir), state)

    try:
        return _execute_rounds(study_dir, state)
    finally:
        if state.get("status") == "running":
            state["status"] = "blocked"
            state["stop_reason"] = state.get("stop_reason") or "aborted"
            state["updated_at"] = _now()
            _save(state_path(study_dir), state)


def _executions_document(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND + ".executions",
        "study_id": state.get("study_id"),
        "loop_id": state.get("loop_id"),
        "boundary": (
            "Deterministic execution journal only. Analyze uses existing local data, performs no "
            "network access, and never promotes a candidate, edits a judgment or proves causality."
        ),
        "executions": state.get("execution_records") or [],
    }


def _analysis_input_fingerprint(study_dir: Path, refs: List[str], question: str) -> str:
    files: Dict[str, str] = {}
    root = Path(study_dir).resolve()
    for relative in refs:
        path = root / relative
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _sha({"files": files, "question": question, "analysis_version": ANALYSIS_VERSION})


def _analyze_existing_study_data(
    study_dir: Path,
    state: Dict[str, Any],
    action: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the established local analysis and journal a human follow-up revision."""
    key = str(action["gap_key"])
    refs = [str(item) for item in action.get("analysis_input_refs") or []]
    question = str(action.get("question") or "")
    fingerprint = _analysis_input_fingerprint(study_dir, refs, question)
    target = Path(study_dir).resolve() / ANALYSIS_RELATIVE / (_slug(key) + ".json")
    relative = str(target.relative_to(Path(study_dir).resolve()))
    if target.is_file():
        try:
            previous = _load_json(target)
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, dict) and previous.get("input_fingerprint") == fingerprint:
            _set_gap_state(state, key, "analyzed", analysis_ref=relative,
                           records=int(previous.get("records") or 0), analysis_scope="existing_study_data")
            return {
                "status": "analyzed",
                "reused": True,
                "records": int(previous.get("records") or 0),
                "verdict": previous.get("verdict"),
                "path": str(target),
                "analysis_path": (previous.get("result") or {}).get("analysis_ref"),
                "execution_id": (previous.get("execution_record") or {}).get("execution_id"),
                "follow_up_revision": previous.get("follow_up_revision"),
                "network_access": "none",
            }

    # Reuse the same function as `askovo analyze`; no collector, experiment or
    # external request is invoked on this path.
    analysis_result = sure_engine.analyze_study(Path(study_dir).resolve(), question or None)
    analysis_document = _load_json(Path(analysis_result["analysis"]))
    root = Path(study_dir).resolve()
    analysis_ref = str(Path(analysis_result["analysis"]).resolve().relative_to(root))
    markdown_ref = str(Path(analysis_result["markdown"]).resolve().relative_to(root))
    records = int(analysis_result.get("records") or 0)
    execution_id = f"EX{len(state.get('execution_records') or []) + 1:04d}"
    follow_up = {
        "revision_type": "loop_gap_state",
        "before": "open",
        "after": "analyzed",
        "next": "human_semantic_revision_and_assessment_required",
        "canonical_product_reasoning_changed": False,
        "demand_judgment_changed": False,
        "candidate_validated": False,
        "gap_resolved": False,
    }
    result_summary = {
        "status": "analyzed",
        "records": records,
        "analysis_ref": analysis_ref,
        "markdown_ref": markdown_ref,
        "by_platform": analysis_document.get("by_platform") or {},
        "by_evidence_level": analysis_document.get("by_evidence_level") or {},
        "question_matches": len(analysis_document.get("question_matches") or []),
    }
    execution = {
        "execution_id": execution_id,
        "action_id": action.get("id"),
        "kind": "analyze",
        "analysis_scope": "existing_study_data",
        "gap_key": key,
        "recorded_at": _now(),
        "input": {"local_refs": refs, "fingerprint": fingerprint, "question": question or None},
        "network_access": "none",
        "result": result_summary,
        "follow_up_revision": follow_up,
        "validated_status_changed": False,
    }
    analysis = {
        "analysis_version": ANALYSIS_VERSION,
        "kind": "askovo.research-loop-analysis-execution",
        "gap_key": key,
        "gap_kind": action.get("gap_kind"),
        "intent": action.get("intent"),
        "node": action.get("node"),
        "judgment_id": action.get("judgment_id"),
        "analysis_scope": "existing_study_data",
        "candidate_groups": 0,
        "records": records,
        "record_ids": [],
        "platforms": sorted((analysis_document.get("by_platform") or {}).keys()),
        "duplicate_record_ids": None,
        "input_fingerprint": fingerprint,
        "verdict": "review_ready" if records else "insufficient_material",
        "execution_record": execution,
        "result": result_summary,
        "follow_up_revision": follow_up,
        "boundary": (
            "Existing local data described by askovo analyze. No network access, evidence-level "
            "assignment, candidate promotion, canonical chain edit, gap closure or causal claim."
        ),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    _save(target, analysis)
    _set_gap_state(state, key, "analyzed", analysis_ref=relative, records=records,
                   analysis_scope="existing_study_data")
    state.setdefault("totals", {})
    state["totals"]["analyses"] = int(state["totals"].get("analyses") or 0) + 1
    state.setdefault("execution_records", []).append(execution)
    _save(executions_path(study_dir), _executions_document(state))
    return {
        "status": "analyzed",
        "reused": False,
        "records": records,
        "verdict": analysis["verdict"],
        "path": str(target),
        "analysis_path": analysis_ref,
        "execution_id": execution_id,
        "follow_up_revision": follow_up,
        "network_access": "none",
    }


def _analyze_gap(study_dir: Path, state: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """Describe existing local data or collected candidates; never grade or close."""
    if str(action.get("analysis_scope") or "loop_candidates") == "existing_study_data":
        return _analyze_existing_study_data(study_dir, state, action)
    key = str(action["gap_key"])
    entries = _candidate_entries(state, key)
    record_ids: List[str] = []
    platforms: set[str] = set()
    for item in entries:
        record_ids.extend(str(value) for value in item.get("record_ids") or [])
        platforms.add(str(item.get("platform") or ""))
    unique = list(dict.fromkeys(record_ids))
    fingerprint = _sha({
        "gap_key": key,
        "records": sum(int(item.get("records") or 0) for item in entries),
        "record_ids": unique,
        "platforms": sorted(item for item in platforms if item),
    })
    target = Path(study_dir).resolve() / ANALYSIS_RELATIVE / (_slug(key) + ".json")
    relative = str(target.relative_to(Path(study_dir).resolve()))
    if target.is_file():
        try:
            previous = _load_json(target)
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, dict) and previous.get("input_fingerprint") == fingerprint:
            _set_gap_state(state, key, "analyzed", analysis_ref=relative,
                           records=int(previous.get("records") or 0))
            return {
                "status": "analyzed",
                "reused": True,
                "records": int(previous.get("records") or 0),
                "verdict": previous.get("verdict"),
                "path": str(target),
            }
    analysis: Dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "gap_key": key,
        "gap_kind": action.get("gap_kind"),
        "intent": action.get("intent"),
        "node": action.get("node"),
        "judgment_id": action.get("judgment_id"),
        "candidate_groups": len(entries),
        "records": sum(int(item.get("records") or 0) for item in entries),
        "record_ids": unique[:MAX_RECORD_IDS],
        "platforms": sorted(item for item in platforms if item),
        "duplicate_record_ids": len(record_ids) - len(unique),
        "input_fingerprint": fingerprint,
        "verdict": "review_ready" if entries else "insufficient_material",
        "boundary": (
            "Deterministic description only: it does not assign an evidence level, judge support "
            "or counter-evidence, or close the gap."
        ),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    _save(target, analysis)
    _set_gap_state(
        state, key, "analyzed",
        analysis_ref=relative,
        records=analysis["records"],
    )
    state.setdefault("totals", {})
    state["totals"]["analyses"] = int(state["totals"].get("analyses") or 0) + 1
    return {
        "status": "analyzed",
        "reused": False,
        "records": analysis["records"],
        "verdict": analysis["verdict"],
        "path": str(target),
    }


def _execute_rounds(study_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    envelope = state["envelope"]
    sources = state.get("sources") or []
    executed = 0
    while True:
        if len(state["rounds"]) >= int(envelope["max_rounds"]):
            state["status"] = "completed"
            state["stop_reason"] = "round_budget"
            break
        gaps = detect_gaps(study_dir)
        state["gaps"] = gaps
        state["next_best_actions"] = next_best_actions(gaps)
        actionable = [gap for gap in gaps if gap.get("actionable")]
        analysis_only = [gap for gap in gaps if gap.get("analysis_actionable") and not gap.get("actionable")]
        plannable = actionable + analysis_only
        states = {str(gap["key"]): gap_state(state, str(gap["key"])) for gap in plannable}
        pending_collect = [gap for gap in actionable if states[str(gap["key"])] == "open"]
        pending_analyze = [
            gap for gap in plannable
            if states[str(gap["key"])] == "collected"
            or (
                gap in analysis_only and states[str(gap["key"])] == "open"
                and f"existing-analysis|{gap['key']}" not in (state.get("attempted") or {})
            )
        ]
        remaining = int(envelope["max_records_total"]) - int(state["totals"]["records"])
        if not pending_collect and not pending_analyze:
            analyzed = [gap for gap in plannable if states[str(gap["key"])] == "analyzed"]
            if analyzed:
                state["status"] = "completed"
                state["stop_reason"] = "awaiting_semantic_review"
                decision = "stop_with_reason"
            elif not actionable:
                if gaps:
                    state["status"] = "blocked"
                    state["stop_reason"] = "no_actionable_source"
                    decision = "request_external_evidence"
                else:
                    state["status"] = "completed"
                    state["stop_reason"] = "converged"
                    decision = "stop_with_reason"
            else:
                state["status"] = "completed"
                state["stop_reason"] = "converged"
                decision = "stop_with_reason"
            state["last_decision"] = decision
            break
        decision = "analyze_existing" if pending_analyze else (
            "continue_collecting" if remaining > 0 else "stop_with_reason")
        state["last_decision"] = decision
        actions = build_actions(
            plannable, sources,
            attempted=state.get("attempted") or {},
            limit_actions=int(envelope["max_actions_per_round"]),
            remaining_records=max(0, remaining),
            gap_states=states,
        )
        if not actions:
            if pending_analyze:
                state["status"] = "completed"
                state["stop_reason"] = "awaiting_analysis"
            elif remaining <= 0:
                state["status"] = "completed"
                state["stop_reason"] = "record_budget"
            elif state.get("candidates"):
                state["status"] = "completed"
                state["stop_reason"] = "partial_coverage"
            else:
                state["status"] = "blocked"
                state["stop_reason"] = "sources_exhausted"
            state["last_decision"] = "stop_with_reason"
            break
        round_index = len(state["rounds"]) + 1
        for index, action in enumerate(actions, start=1):
            if executed >= int(envelope["max_actions_per_round"]) * int(envelope["max_rounds"]):
                break
            action["id"] = f"L{round_index}-{index}"
            _validate_action(study_dir, state, action)
        record: Dict[str, Any] = {
            "round": round_index,
            "decision": decision,
            "started_at": _now(),
            "status": "running",
            "before": gap_counts(gaps),
            "actions": actions,
            "records_added": 0,
            "audit": None,
        }
        state["rounds"].append(record)
        _save(state_path(study_dir), state)

        fatal = False
        for action in actions:
            action["state"] = "running"
            state["attempted"][action["attempt_key"]] = {"round": round_index, "state": "running"}
            _save(state_path(study_dir), state)
            if str(action.get("kind")) == "analyze":
                result = _analyze_gap(study_dir, state, action)
                action["result"] = result
                action["state"] = "completed"
                executed += 1
                state["totals"]["actions"] += 1
                state["attempted"][action["attempt_key"]]["state"] = "analyzed"
                state["updated_at"] = _now()
                _save(state_path(study_dir), state)
                continue
            gate = cli_module().audit_study(study_dir, "design")
            if gate.status != "pass":
                action["state"] = "blocked"
                action["result"] = {"status": "design_gate_failed"}
                state["attempted"][action["attempt_key"]]["state"] = "design_gate_failed"
                _save(state_path(study_dir), state)
                raise DesignGateError(
                    "Design gate does not pass; fix the study contract before any collection: "
                    + "; ".join(f"{item.check_id}: {item.detail}" for item in gate.findings
                                 if item.status == "fail")[:600])
            try:
                kwargs: Dict[str, Any] = {
                    "study_dir": study_dir,
                    "platform": action["platform"],
                    "query": action["query"],
                    "limit": int(action["limit"]),
                    "fixture": Path(action["fixture"]) if action.get("fixture") else None,
                    "run_id": f"{state['loop_id']}-r{round_index}-{action['id']}",
                }
                result = sure_engine.collect_platform(**kwargs)
            except Exception as exc:  # surface the exact failure in the journal
                action["state"] = "interrupted"
                action["result"] = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
                state["attempted"][action["attempt_key"]]["state"] = "interrupted"
                state["status"] = "needs_review"
                state["stop_reason"] = "interrupted_run"
                record["status"] = "interrupted"
                state["updated_at"] = _now()
                _save(state_path(study_dir), state)
                raise InterruptedRunError(
                    f"collection action {action['id']} was interrupted; inspect the files before replanning: {exc}")
            action["result"] = result
            status_name = str(result.get("status") or "")
            executed += 1
            state["totals"]["actions"] += 1
            if status_name in COLLECTED:
                action["state"] = "completed"
                added = int(result.get("normalized_added") or 0)
                record["records_added"] += added
                state["totals"]["records"] += added
                state["attempted"][action["attempt_key"]]["state"] = "collected"
                if added:
                    state["candidates"].append({
                        "gap_key": action["gap_key"],
                        "gap_kind": action["gap_kind"],
                        "intent": action["intent"],
                        "node": action.get("node"),
                        "judgment_id": action.get("judgment_id"),
                        "platform": action["platform"],
                        "mode": action["mode"],
                        "query": action["query"],
                        "run_id": result.get("run_id"),
                        "records": added,
                        "record_ids": _record_ids(result.get("raw_file")),
                        "status": "proposed",
                        "proposed_evidence_level": None,
                        "note": "Human review assigns the evidence level and links the record to a judgment.",
                    })
                    _set_gap_state(state, str(action["gap_key"]), "collected",
                                   candidate_run=result.get("run_id"), records=added)
                    _save(candidates_path(study_dir), _candidates_document(state))
            else:
                action["state"] = "blocked"
                state["totals"]["blocked"] += 1
                state["attempted"][action["attempt_key"]]["state"] = status_name or "blocked"
                if status_name in FATAL_RESULTS:
                    fatal = True
            state["updated_at"] = _now()
            _save(state_path(study_dir), state)
            if fatal:
                break

        try:
            analysis = sure_engine.analyze_study(study_dir, None)
        except (OSError, ValueError, json.JSONDecodeError) as exc:  # analysis never blocks the loop
            analysis = {"status": "error", "reason": str(exc)}
        payload = cli_module().audit_payload(study_dir)
        after_gaps = detect_gaps(study_dir)
        record["analysis"] = {
            "records": int(analysis.get("records", 0) or 0) if isinstance(analysis, dict) else 0,
        }
        record["audit"] = {
            "status": payload.get("status"),
            "summary": payload.get("summary"),
        }
        record["after"] = gap_counts(after_gaps)
        record["finished_at"] = _now()
        record["status"] = "blocked" if fatal else "completed"
        state["gaps"] = after_gaps
        state["next_best_actions"] = next_best_actions(after_gaps)
        _save(candidates_path(study_dir), _candidates_document(state))
        if fatal:
            state["status"] = "blocked"
            state["stop_reason"] = "connector_blocked"
            break
        collected_in_round = any(str(item.get("kind") or "collect") == "collect" for item in actions)
        if record["records_added"] == 0 and collected_in_round:
            state["status"] = "completed" if state.get("candidates") else "blocked"
            state["stop_reason"] = "no_new_material"
            break

    state["updated_at"] = _now()
    _save(state_path(study_dir), state)
    _save(candidates_path(study_dir), _candidates_document(state))
    return status(study_dir)


def _evaluations_document(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND + ".evaluations",
        "study_id": state.get("study_id"),
        "boundary": (
            "Named human assessments only. The loop never assigns an evidence level, never edits a "
            "judgment and never marks a claim validated."
        ),
        "evaluations": state.get("evaluations") or [],
    }


def assess(
    study_dir: Path,
    *,
    gap_key: str,
    verdict: str,
    by: str,
    reason: str = "",
    evidence_ids: Any = (),
    hypothesis_id: str = "",
) -> Dict[str, Any]:
    """Record a named operator's judgment that a gap is closed or unverifiable.

    This is the only path from ``analyzed`` to ``resolved``. The CLI can check
    that evidence references exist, but the semantic judgment stays human: it is
    recorded, not inferred.
    """
    verdict = str(verdict or "").strip()
    if verdict not in ASSESS_VERDICTS:
        raise LoopError("verdict must be one of: " + ", ".join(ASSESS_VERDICTS))
    operator = str(by or "").strip()
    if not operator:
        raise LoopError("an assessment requires a named operator")
    refs = [str(item).strip() for item in (evidence_ids or []) if str(item).strip()]
    if verdict == "resolved" and not refs:
        raise LoopError("a resolved gap requires at least one evidence reference")
    if verdict == "unresolvable" and not str(reason or "").strip():
        raise LoopError("an unresolvable gap requires a recorded reason")
    with _lock(study_dir):
        study_dir = Path(study_dir).resolve()
        state = load_state(study_dir)
        study = _study(study_dir)
        if verdict == "resolved":
            evidence_file = study_dir / "02-data" / "evidence.jsonl"
            known: set[str] = set()
            if evidence_file.is_file():
                for line in evidence_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict) and record.get("record_id"):
                        known.add(str(record["record_id"]))
                unknown = [ref for ref in refs if ref not in known]
                if unknown:
                    raise LoopError(
                        "resolved evidence is not registered in 02-data/evidence.jsonl: "
                        + ", ".join(unknown)
                    )
        if str(hypothesis_id or "").strip():
            declared = {
                str(item.get("id")) for item in (study.get("hypotheses") or [])
                if isinstance(item, dict)
            }
            if str(hypothesis_id) not in declared:
                raise LoopError(
                    f"unknown hypothesis {hypothesis_id!r}; study.json declares: "
                    + (", ".join(sorted(declared)) or "none")
                )
        gaps = detect_gaps(study_dir)
        state["gaps"] = gaps
        keys = {str(gap.get("key")) for gap in gaps}
        if gap_key not in keys:
            raise LoopError(f"unknown gap {gap_key!r}; run `askovo loop status` for current gaps")
        current = gap_state(state, gap_key)
        if current in ("resolved", "unresolvable"):
            raise LoopError(f"gap {gap_key} is already {current}")
        _set_gap_state(
            state, gap_key, verdict,
            by=operator, at=_now(), reason=str(reason or ""),
            evidence_ids=refs, hypothesis_id=str(hypothesis_id or ""),
        )
        evaluations = state.setdefault("evaluations", [])
        evaluation = {
            "id": f"EV{len(evaluations) + 1:02d}",
            "gap_key": gap_key,
            "verdict": verdict,
            "level": "human_assessment",
            "hypothesis_id": str(hypothesis_id or ""),
            "evidence_ids": refs,
            "reason": str(reason or ""),
            "by": operator,
            "at": _now(),
            "previous_state": current,
        }
        evaluations.append(evaluation)
        state["updated_at"] = _now()
        _save(state_path(study_dir), state)
        _save(evaluations_path(study_dir), _evaluations_document(state))
        result = status(study_dir)
        result["evaluation"] = evaluation
        return result


def _mappings_document(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND + ".mappings",
        "study_id": state.get("study_id"),
        "boundary": (
            "Mappings are supplied by a host agent or a reviewer and only carry provenance: "
            "record id, hypothesis id, verbatim quote and stance. They are not an evidence "
            "level, a judgment status or a validated claim."
        ),
        "mappings": state.get("mappings") or [],
    }


def map_candidates(study_dir: Path, *, mappings: Any, by: str) -> Dict[str, Any]:
    """Validate host-supplied evidence mappings against collected candidates.

    The semantic link (which quote supports or contradicts which hypothesis) is
    supplied by a host agent or reviewer. This function only checks that the
    quote exists in a collected record, that the hypothesis is declared in
    ``study.json``, and that the stance is one of the allowed values.
    """
    operator = str(by or "").strip()
    if not operator:
        raise LoopError("evidence mapping requires a named operator")
    if not isinstance(mappings, list) or not mappings:
        raise LoopError("mappings must be a non-empty array")
    with _lock(study_dir):
        study_dir = Path(study_dir).resolve()
        state = load_state(study_dir)
        study = _study(study_dir)
        declared = {
            str(item.get("id")) for item in (study.get("hypotheses") or [])
            if isinstance(item, dict)
        }
        record_gap: Dict[str, str] = {}
        for candidate in state.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            for record_id in candidate.get("record_ids") or []:
                record_gap[str(record_id)] = str(candidate.get("gap_key"))
        prepared: List[Dict[str, Any]] = []
        existing = len(state.get("mappings") or [])
        for index, raw in enumerate(mappings, start=1):
            if not isinstance(raw, dict):
                raise LoopError(f"mapping {index} must be an object")
            hypothesis_id = str(raw.get("hypothesis_id") or "").strip()
            if hypothesis_id not in declared:
                raise LoopError(
                    f"mapping {index}: unknown hypothesis {hypothesis_id!r}; declare it in study.json"
                )
            record_id = str(raw.get("record_id") or "").strip()
            if record_id not in record_gap:
                raise LoopError(
                    f"mapping {index}: record {record_id!r} is not among collected candidates"
                )
            quote = str(raw.get("quote") or "").strip()
            if len(quote) < 5:
                raise LoopError(f"mapping {index}: quote must be at least 5 characters")
            stance = str(raw.get("stance") or "").strip()
            if stance not in MAPPING_STANCES:
                raise LoopError(
                    f"mapping {index}: stance must be one of: " + ", ".join(MAPPING_STANCES)
                )
            prepared.append({
                "id": f"M{existing + index:02d}",
                "gap_key": record_gap[record_id],
                "record_id": record_id,
                "hypothesis_id": hypothesis_id,
                "stance": stance,
                "quote": quote[:500],
                "locator": str(raw.get("locator") or record_id),
                "by": operator,
                "at": _now(),
                "level": "host_supplied_mapping",
            })
        state.setdefault("mappings", []).extend(prepared)
        state["updated_at"] = _now()
        _save(state_path(study_dir), state)
        _save(mappings_path(study_dir), _mappings_document(state))
        return {
            "status": "mapped",
            "added": len(prepared),
            "total": len(state.get("mappings") or []),
            "path": str(mappings_path(study_dir)),
            "by_gap": {
                gap: sum(1 for item in prepared if item["gap_key"] == gap)
                for gap in sorted({item["gap_key"] for item in prepared})
            },
        }


def advise(study_dir: Path) -> Dict[str, Any]:
    """Suggest, never decide: a deterministic reading of recorded mappings.

    The advice only reflects what a reviewer already mapped. It cannot close a
    gap, cannot promote a candidate to evidence and cannot mark a claim
    validated; ``loop assess`` remains the only path.
    """
    state = load_state(study_dir)
    gaps = state.get("gaps") or []
    mappings = [item for item in state.get("mappings") or [] if isinstance(item, dict)]
    items: List[Dict[str, Any]] = []
    for gap in gaps:
        key = str(gap.get("key"))
        if not gap.get("actionable"):
            continue
        current = gap_state(state, key)
        if current != "analyzed":
            continue
        related = [item for item in mappings if str(item.get("gap_key")) == key]
        supports = [item for item in related if item.get("stance") == "supports"]
        contradicts = [item for item in related if item.get("stance") == "contradicts"]
        contextual = [item for item in related if item.get("stance") == "contextual"]
        if not related:
            recommendation = "insufficient"
            reason = "no evidence mapping recorded for this gap"
        elif supports and not contradicts:
            recommendation = "resolved_candidate"
            reason = "mapped passages support the hypothesis and none contradict it"
        elif contradicts and not supports:
            recommendation = "unresolvable_candidate"
            reason = "mapped passages contradict the hypothesis and none support it"
        else:
            recommendation = "conflicted"
            reason = "mapped passages disagree; a reviewer must weigh them"
        items.append({
            "gap_key": key,
            "gap_kind": gap.get("kind"),
            "state": current,
            "recommendation": recommendation,
            "reason": reason,
            "supports": len(supports),
            "contradicts": len(contradicts),
            "contextual": len(contextual),
            "hypothesis_ids": sorted({str(item.get("hypothesis_id")) for item in related
                                      if item.get("hypothesis_id")}),
            "record_ids": sorted({str(item.get("record_id")) for item in related
                                  if item.get("record_id")})[:20],
        })
    return {
        "loop_id": state.get("loop_id"),
        "advice": items,
        "boundary": (
            "Advice is a deterministic summary of reviewer-supplied mappings. It is not an "
            "evidence level, not a judgment and not an assessment; only `loop assess` closes a gap."
        ),
    }


def status(study_dir: Path) -> Dict[str, Any]:
    state = load_state(study_dir)
    gaps = state.get("gaps") or []
    resolved = _resolved_keys(state)
    actionable = [gap for gap in gaps if gap.get("actionable")]
    analysis_only = [gap for gap in gaps if gap.get("analysis_actionable") and not gap.get("actionable")]
    states = _gap_state_counts(state, actionable + analysis_only)
    return {
        "loop_id": state.get("loop_id"),
        "study_id": state.get("study_id"),
        "status": state.get("status"),
        "stop_reason": state.get("stop_reason"),
        "last_decision": state.get("last_decision"),
        "authorized": bool(state.get("authorization")),
        "authorization": state.get("authorization"),
        "envelope": state.get("envelope"),
        "next_best_actions": next_best_actions(gaps),
        "gaps": {
            "total": len(gaps),
            "actionable": len(actionable),
            "analysis_only": len(analysis_only),
            "resolved": len(resolved),
            "covered": len(resolved),
            "open": states["open"],
            "collected": states["collected"],
            "analyzed": states["analyzed"],
            "unresolvable": states["unresolvable"],
            "by_kind": gap_counts(gaps)["by_kind"],
        },
        "rounds": [
            {
                "round": item.get("round"),
                "status": item.get("status"),
                "actions": len(item.get("actions") or []),
                "records_added": item.get("records_added"),
                "audit": (item.get("audit") or {}).get("status"),
                "after": item.get("after"),
            }
            for item in state.get("rounds") or []
        ],
        "totals": state.get("totals"),
        "candidates": len(state.get("candidates") or []),
        "executions": len(state.get("execution_records") or []),
        "evaluations": len(state.get("evaluations") or []),
        "mappings": len(state.get("mappings") or []),
        "state_path": str(state_path(study_dir)),
        "candidates_path": str(candidates_path(study_dir)),
        "executions_path": str(executions_path(study_dir)),
        "evaluations_path": str(evaluations_path(study_dir)),
        "mappings_path": str(mappings_path(study_dir)),
        "summary_path": str(summary_path(study_dir)) if summary_path(study_dir).is_file() else None,
    }


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def summary_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / SUMMARY_RELATIVE


def _claim_lines(payload: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        verdict = claim.get("verdict")
        mark = {"supported": "可支持", "open": "未定", "exceeds_evidence": "超出证据",
                "rejected": "已拒绝", "deprioritized": "已降级"}.get(verdict, str(verdict))
        lines.append(
            f"- {claim.get('id')} {claim.get('title')} — {mark}"
            f"（最高证据 {claim.get('max_evidence_level')}，反证 {claim.get('counter_evidence')} 条）"
        )
        for reason in claim.get("reasons") or []:
            lines.append(f"  - {reason}")
    return lines or ["- 无登记判断；先写 demand-judgments.json。"]


def report(study_dir: Path) -> Dict[str, Any]:
    """Write the review-ready loop summary and return it with its path."""
    study_dir = Path(study_dir).resolve()
    state = load_state(study_dir)
    payload = cli_module().audit_payload(study_dir)
    gaps = detect_gaps(study_dir)
    resolved = _resolved_keys(state)
    totals = state.get("totals") or {}

    verified = [claim for claim in payload.get("claims") or []
                if isinstance(claim, dict) and claim.get("verdict") == "supported"]
    unverified = [claim for claim in payload.get("claims") or []
                  if isinstance(claim, dict) and claim.get("verdict") in ("open", "exceeds_evidence")]
    blocked = [gap for gap in gaps if not gap.get("actionable") and not gap.get("analysis_actionable")]
    pending = [
        gap for gap in gaps
        if (gap.get("actionable") or gap.get("analysis_actionable")) and gap.get("key") not in resolved
    ]
    needs_collection = [
        gap for gap in pending
        if gap.get("actionable") and gap_state(state, str(gap["key"])) == "open"
    ]
    needs_analysis = [
        gap for gap in pending
        if gap_state(state, str(gap["key"])) == "collected"
        or (gap.get("analysis_actionable") and gap_state(state, str(gap["key"])) == "open")
    ]
    needs_assessment = [gap for gap in pending if gap_state(state, str(gap["key"])) == "analyzed"]
    state_counts = _gap_state_counts(
        state, [gap for gap in gaps if gap.get("actionable") or gap.get("analysis_actionable")]
    )

    lines: List[str] = [
        f"# 研究闭环报告：{payload.get('study_title') or state.get('study_id')}",
        "",
        f"- 闭环：`{state.get('loop_id')}`",
        f"- 状态：{state.get('status')} / 停止原因：{state.get('stop_reason') or '-'}",
        f"- 轮次：{len(state.get('rounds') or [])}；采集记录：{totals.get('records', 0)}；"
        f"候选证据组：{len(state.get('candidates') or [])}；人工评估：{len(state.get('evaluations') or [])}",
        f"- 授权：{(state.get('authorization') or {}).get('by') or '未授权'}",
        f"- 缺口状态：open {state_counts['open']} / collected {state_counts['collected']} / "
        f"analyzed {state_counts['analyzed']} / resolved {state_counts['resolved']} / "
        f"unresolvable {state_counts['unresolvable']}",
        "",
        "## 已验证结论（仅指现有材料通过审计门）",
        "",
    ]
    if verified:
        lines.extend(f"- {claim.get('id')} {claim.get('title')} — 证据链与反证齐全，仍需人工语义复核与业务签收。"
                     for claim in verified)
    else:
        lines.append("- 目前没有通过审计的验证结论。")
    lines.extend(["", "## 未验证假设", ""])
    lines.extend(_claim_lines({"claims": unverified}) if unverified else ["- 无未定判断。"])
    lines.extend(["", "## 无法自动验证 / 阻断", ""])
    if blocked:
        for gap in blocked:
            reason = gap.get("blocked_reason") or "需要人工写作或外部数据，不在采集范围内"
            lines.append(f"- [{gap.get('kind')}] {gap.get('detail')}（{reason}）")
    else:
        lines.append("- 无记录在案的阻断项。")
    lines.extend(["", "## 仍需补证", ""])
    open_gaps = needs_collection + needs_analysis
    if open_gaps:
        for gap in open_gaps:
            stage = (
                "待分析" if gap.get("analysis_actionable")
                or gap_state(state, str(gap["key"])) == "collected" else "待采集"
            )
            lines.append(f"- [{gap.get('id')} {gap.get('kind')} / {stage}] {gap.get('detail')}"
                         + (f"；建议查询：`{gap.get('query_seed')}`" if gap.get("query_seed") else ""))
    else:
        lines.append("- 无未覆盖的可采集缺口。")
    lines.extend(["", "## 待人工评估（采集与分析已不能自动闭合）", ""])
    if needs_assessment:
        for gap in needs_assessment:
            entry = (state.get("gap_states") or {}).get(str(gap["key"])) or {}
            lines.append(
                f"- [{gap.get('id')} {gap.get('kind')}] {gap.get('detail')}；"
                f"分析：`{entry.get('analysis_ref') or '-'}`；"
                f"评估：`askovo loop assess STUDY --gap {gap.get('key')} "
                f"--verdict resolved|unresolvable --by NAME`"
            )
        lines.append("")
        lines.append("评估是人工语义判断，系统只记录；未评估的分析结果不会被当成缺口已闭合。")
    else:
        lines.append("- 无待评估缺口。")
    lines.extend(["", "## 候选证据（待人工定级与关联）", ""])
    candidates = state.get("candidates") or []
    if candidates:
        for item in candidates:
            ids = ", ".join(str(value) for value in (item.get("record_ids") or [])[:5])
            lines.append(
                f"- {item.get('gap_key')} ← {item.get('platform')} `{item.get('query')}`"
                f"（{item.get('records')} 条；样例 {ids or '-'}；run {item.get('run_id')}）"
            )
        lines.append("")
        lines.append("候选记录没有证据等级，也不会被审计计入；人工定级并写入判断后才改变结论。")
    else:
        lines.append("- 本轮没有新增候选材料。")
    lines.extend(["", "## 下一最佳研究动作候选（不自动执行）", ""])
    for gap in gaps:
        best = gap.get("next_best_action") if isinstance(gap.get("next_best_action"), dict) else {}
        if not best:
            continue
        compared = ", ".join(str(item.get("action")) for item in gap.get("research_action_candidates") or [])
        if best.get("action") == "stop":
            stop = best.get("stop_decision") if isinstance(best.get("stop_decision"), dict) else {}
            lines.append(
                f"- [{gap.get('id')} {gap.get('key')}] **stop**：{best.get('rationale')}；"
                f"StopDecision={stop.get('status')}（独立门控，不参与正收益评分）。"
            )
            for name, criterion in (stop.get("criteria") or {}).items():
                lines.append(
                    f"  - {name}: {criterion.get('value')}（要求 {criterion.get('required')}）；"
                    f"依据：{criterion.get('rationale')}；来源：{criterion.get('basis_ref')}"
                )
        else:
            lines.append(
                f"- [{gap.get('id')} {gap.get('key')}] **{best.get('action')}**：{best.get('rationale')}；"
                f"不确定性下降 {best.get('expected_uncertainty_reduction')}，相对成本 {best.get('cost')}，"
                f"决策改变潜力 {best.get('decision_change_potential')}，评分 {best.get('priority_score')}。"
            )
        lines.append(f"  - 可改变的决定：{best.get('decision_it_can_change')}；已比较：{compared}。")
        if not gap.get("actionable"):
            lines.append("  - 原缺口不可自动采集；这里仅新增任务候选，不改变 actionable 或 validated。")
    if not any(isinstance(gap.get("next_best_action"), dict) for gap in gaps):
        lines.append("- 当前没有缺口候选。")
    lines.extend(["", "## 下一步", ""])
    next_actions = list(payload.get("next_actions") or [])
    for gap in open_gaps[:5]:
        action = (
            "分析" if gap.get("analysis_actionable")
            or gap_state(state, str(gap["key"])) == "collected" else "补采"
        )
        next_actions.append(f"{action} {gap.get('key')}：" + (gap.get("query_seed") or gap.get("detail") or ""))
    for gap in needs_assessment[:3]:
        next_actions.append(
            f"评估缺口 {gap.get('key')}：`askovo loop assess` 记录 resolved 或 unresolvable")
    for item in candidates[:3]:
        next_actions.append(
            f"复核 {item.get('run_id')} 的 {item.get('records')} 条候选记录，定级后写入判断 {item.get('judgment_id') or ''}".strip())
    if not next_actions:
        next_actions.append("没有待办；补充业务签收或开始写作。")
    lines.extend(f"- {action}" for action in next_actions)
    lines.extend(["", "## 边界", "", cli_module().AUDIT_BOUNDARY, ""])

    path = summary_path(study_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n".join(lines)
    path.write_text(markdown, encoding="utf-8")
    return {"status": state.get("status"), "stop_reason": state.get("stop_reason"),
            "path": str(path), "markdown": markdown,
            "verified": len(verified), "unverified": len(unverified),
            "blocked": len(blocked), "pending": len(pending),
            "awaiting_assessment": len(needs_assessment)}

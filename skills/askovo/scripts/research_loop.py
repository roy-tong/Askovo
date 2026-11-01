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
CANDIDATE_SAMPLE_IDS = 20

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


def _cli() -> Any:
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


def detect_gaps(study_dir: Path) -> List[Dict[str, Any]]:
    """Return every open gap, deterministically ordered and explained."""
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    payload = _cli().audit_payload(study_dir)
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
    for index, gap in enumerate(unique, start=1):
        gap["id"] = f"G{index:02d}"
    return unique


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
) -> List[Dict[str, Any]]:
    """Turn uncovered gaps into collection actions, one query per source."""
    actions: List[Dict[str, Any]] = []
    seen_queries: set[str] = set()
    for gap in gaps:
        if len(actions) >= limit_actions or remaining_records <= 0:
            break
        if not gap.get("actionable") or not gap.get("query_seed"):
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
            "gaps": gaps,
            "rounds": [],
            "candidates": [],
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
    gap_keys = {str(gap.get("key")) for gap in state.get("gaps") or [] if isinstance(gap, dict)}
    if str(action.get("gap_key")) not in gap_keys:
        raise LoopError("action does not map to a recorded gap")
    if action.get("fixture"):
        candidate = Path(str(action["fixture"])).resolve()
        try:
            candidate.relative_to(Path(study_dir).resolve())
        except ValueError:
            raise LoopError("fixture must stay inside the study directory")
        if action.get("mode") != "fixture" or not candidate.is_file():
            raise LoopError("fixture action is missing its authorized export")


def _record_ids(raw_file: Optional[str], limit: int = CANDIDATE_SAMPLE_IDS) -> List[str]:
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
    return {str(item.get("gap_key")) for item in state.get("candidates") or [] if isinstance(item, dict)}


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
    gate = _cli().audit_study(study_dir, "design")
    if gate.status != "pass":
        raise DesignGateError(
            "Design gate does not pass; fix the study contract before any collection: "
            + "; ".join(f"{item.check_id}: {item.detail}" for item in gate.findings
                         if item.status == "fail")[:600])
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
        actionable = [gap for gap in gaps if gap.get("actionable")]
        covered = _covered_keys(state)
        uncovered = [gap for gap in actionable if gap["key"] not in covered]
        if not uncovered:
            if not actionable:
                if gaps:
                    state["status"] = "blocked"
                    state["stop_reason"] = "no_actionable_source"
                else:
                    state["status"] = "completed"
                    state["stop_reason"] = "converged"
            else:
                state["status"] = "completed"
                state["stop_reason"] = "awaiting_semantic_review"
            break
        remaining = int(envelope["max_records_total"]) - int(state["totals"]["records"])
        if remaining <= 0:
            state["status"] = "completed"
            state["stop_reason"] = "record_budget"
            break
        actions = build_actions(
            uncovered, sources,
            attempted=state.get("attempted") or {},
            limit_actions=int(envelope["max_actions_per_round"]),
            remaining_records=remaining,
        )
        if not actions:
            if state.get("candidates"):
                state["status"] = "completed"
                state["stop_reason"] = "partial_coverage"
            else:
                state["status"] = "blocked"
                state["stop_reason"] = "sources_exhausted"
            break
        round_index = len(state["rounds"]) + 1
        for index, action in enumerate(actions, start=1):
            if executed >= int(envelope["max_actions_per_round"]) * int(envelope["max_rounds"]):
                break
            action["id"] = f"L{round_index}-{index}"
            _validate_action(study_dir, state, action)
        record: Dict[str, Any] = {
            "round": round_index,
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
        payload = _cli().audit_payload(study_dir)
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
        _save(candidates_path(study_dir), _candidates_document(state))
        if fatal:
            state["status"] = "blocked"
            state["stop_reason"] = "connector_blocked"
            break
        if record["records_added"] == 0:
            state["status"] = "completed" if state.get("candidates") else "blocked"
            state["stop_reason"] = "no_new_material"
            break

    state["updated_at"] = _now()
    _save(state_path(study_dir), state)
    _save(candidates_path(study_dir), _candidates_document(state))
    return status(study_dir)


def status(study_dir: Path) -> Dict[str, Any]:
    state = load_state(study_dir)
    gaps = state.get("gaps") or []
    covered = _covered_keys(state)
    actionable = [gap for gap in gaps if gap.get("actionable")]
    return {
        "loop_id": state.get("loop_id"),
        "study_id": state.get("study_id"),
        "status": state.get("status"),
        "stop_reason": state.get("stop_reason"),
        "authorized": bool(state.get("authorization")),
        "authorization": state.get("authorization"),
        "envelope": state.get("envelope"),
        "gaps": {
            "total": len(gaps),
            "actionable": len(actionable),
            "covered": sum(1 for gap in actionable if gap.get("key") in covered),
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
        "state_path": str(state_path(study_dir)),
        "candidates_path": str(candidates_path(study_dir)),
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
    payload = _cli().audit_payload(study_dir)
    gaps = detect_gaps(study_dir)
    covered = _covered_keys(state)
    totals = state.get("totals") or {}

    verified = [claim for claim in payload.get("claims") or []
                if isinstance(claim, dict) and claim.get("verdict") == "supported"]
    unverified = [claim for claim in payload.get("claims") or []
                  if isinstance(claim, dict) and claim.get("verdict") in ("open", "exceeds_evidence")]
    blocked = [gap for gap in gaps if not gap.get("actionable")]
    pending = [gap for gap in gaps if gap.get("actionable") and gap.get("key") not in covered]

    lines: List[str] = [
        f"# 研究闭环报告：{payload.get('study_title') or state.get('study_id')}",
        "",
        f"- 闭环：`{state.get('loop_id')}`",
        f"- 状态：{state.get('status')} / 停止原因：{state.get('stop_reason') or '-'}",
        f"- 轮次：{len(state.get('rounds') or [])}；采集记录：{totals.get('records', 0)}；"
        f"候选证据组：{len(state.get('candidates') or [])}",
        f"- 授权：{(state.get('authorization') or {}).get('by') or '未授权'}",
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
    if pending:
        for gap in pending:
            lines.append(f"- [{gap.get('id')} {gap.get('kind')}] {gap.get('detail')}"
                         + (f"；建议查询：`{gap.get('query_seed')}`" if gap.get("query_seed") else ""))
    else:
        lines.append("- 无未覆盖的可采集缺口。")
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
    lines.extend(["", "## 下一步", ""])
    next_actions = list(payload.get("next_actions") or [])
    for gap in pending[:5]:
        next_actions.append(f"补采 {gap.get('key')}：" + (gap.get("query_seed") or gap.get("detail") or ""))
    for item in candidates[:3]:
        next_actions.append(
            f"复核 {item.get('run_id')} 的 {item.get('records')} 条候选记录，定级后写入判断 {item.get('judgment_id') or ''}".strip())
    if not next_actions:
        next_actions.append("没有待办；补充业务签收或开始写作。")
    lines.extend(f"- {action}" for action in next_actions)
    lines.extend(["", "## 边界", "", _cli().AUDIT_BOUNDARY, ""])

    path = summary_path(study_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n".join(lines)
    path.write_text(markdown, encoding="utf-8")
    return {"status": state.get("status"), "stop_reason": state.get("stop_reason"),
            "path": str(path), "markdown": markdown,
            "verified": len(verified), "unverified": len(unverified),
            "blocked": len(blocked), "pending": len(pending)}

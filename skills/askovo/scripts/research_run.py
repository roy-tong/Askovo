"""Research Run: execute an authorized, bounded research action plan.

The Skill/agent decides *what* to investigate and supplies a machine-readable
action list. The CLI only executes actions that the operator explicitly
authorized; it never invents a source, bypasses a platform policy or sends data
to a model.

State lives at ``04-findings/research-run.json``. An action is bound to the
action-list hash at authorization time, so editing the plan after authorization
requires a new explicit authorization.

Action file (JSON)::

    {
      "schema_version": "1.0",
      "run_id": "run-001",
      "actions": [
        {"id": "A1", "node": "pain", "platform": "github",
         "query": "billing retry", "limit": 50,
         "purpose": "find substitute behavior"},
        {"id": "A2", "node": "need", "platform": "reddit",
         "query": "invoice confusion", "limit": 50,
         "fixture": "01-sources/authorized/export.jsonl"}
      ]
    }
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import sure_engine

STATE_RELATIVE = Path("04-findings/research-run.json")
REASONING_RELATIVE = Path("04-findings/product-reasoning.json")
SUCCESS = {"collected"}


class ResearchRunError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _study(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / "study.json"
    if not path.is_file():
        raise ResearchRunError("missing study.json; run `askovo do` first")
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ResearchRunError("study.json must be an object")
    return data


def _nodes(study_dir: Path) -> Dict[str, str]:
    path = Path(study_dir).resolve() / REASONING_RELATIVE
    if not path.is_file():
        raise ResearchRunError("missing product-reasoning chain; run `askovo chain` first")
    data = _load_json(path)
    chains = data.get("chains") if isinstance(data, dict) else None
    if not isinstance(chains, list) or not chains:
        raise ResearchRunError("product reasoning has no chains")
    nodes: Dict[str, str] = {}
    for chain in chains:
        if not isinstance(chain, dict):
            continue
        values = chain.get("nodes")
        if isinstance(values, dict):
            for name, node in values.items():
                status = node.get("status") if isinstance(node, dict) else "unknown"
                nodes[str(name)] = str(status or "unknown")
    return nodes


def load_actions(path: Path) -> Dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ResearchRunError("actions file must be an object")
    if data.get("schema_version") not in (None, "1.0"):
        raise ResearchRunError("unsupported actions schema_version")
    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ResearchRunError("actions must be a non-empty array")
    return data


def validate_actions(study_dir: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    node_status = _nodes(study_dir)
    scope = study.get("scope") if isinstance(study.get("scope"), dict) else {}
    allowed = scope.get("allowed_sources") if isinstance(scope.get("allowed_sources"), list) else []
    allowed_set = {str(item) for item in allowed}
    platforms = sure_engine.platform_index()
    seen = set()
    total = 0
    actions: List[Dict[str, Any]] = []
    for index, raw in enumerate(data.get("actions") or []):
        if not isinstance(raw, dict):
            raise ResearchRunError("actions[%d] must be an object" % index)
        aid = str(raw.get("id") or "").strip()
        if not aid or aid in seen:
            raise ResearchRunError("each action needs a unique non-empty id")
        seen.add(aid)
        node = str(raw.get("node") or "").strip()
        if node not in node_status:
            raise ResearchRunError("action %s has unknown reasoning node %r" % (aid, node))
        platform = str(raw.get("platform") or "").strip().lower()
        if platform not in platforms:
            raise ResearchRunError("action %s has unknown platform %r" % (aid, platform))
        if platform not in allowed_set:
            raise ResearchRunError(
                "action %s platform %r is not in study.scope.allowed_sources" % (aid, platform))
        query = str(raw.get("query") or "").strip()
        if not query:
            raise ResearchRunError("action %s needs a query" % aid)
        limit = raw.get("limit", 100)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ResearchRunError("action %s limit must be 1..500" % aid)
        fixture = raw.get("fixture")
        fixture_path = None
        if fixture:
            candidate = (study_dir / str(fixture)).resolve()
            try:
                candidate.relative_to(study_dir)
            except ValueError:
                raise ResearchRunError(
                    "action %s fixture must stay inside the study directory" % aid)
            if not candidate.is_file():
                raise ResearchRunError("action %s fixture does not exist: %s" % (aid, candidate))
            fixture_path = str(candidate)
        action = {
            "id": aid, "node": node, "platform": platform, "query": query,
            "limit": limit, "fixture": fixture_path,
            "cdp_url": str(raw.get("cdp_url") or "") or None,
            "url": str(raw.get("url") or "") or None,
            "ack_terms": bool(raw.get("ack_terms")),
            "purpose": str(raw.get("purpose") or "")[:300],
            "state": "pending", "result": None,
        }
        action["action_sha256"] = _sha({k: action[k] for k in
                                       ("id", "node", "platform", "query", "limit",
                                        "fixture", "cdp_url", "url", "ack_terms")})
        total += limit
        actions.append(action)
    return {
        "schema_version": "1.0", "kind": "askovo.research-run",
        "study_id": study.get("study_id", ""),
        "run_id": str(data.get("run_id") or "run-" + _now().replace(":", "").replace("-", "")),
        "created_at": _now(), "status": "planned",
        "authorization": None, "actions": actions,
        "budget": {"max_records": total, "used_records": 0, "max_steps": len(actions)},
        "actions_sha256": _sha([a["action_sha256"] for a in actions]),
    }


def state_path(study_dir: Path) -> Path:
    return Path(study_dir).resolve() / STATE_RELATIVE


def prepare(study_dir: Path, actions_path: Path, *, reset: bool = False) -> Dict[str, Any]:
    data = load_actions(actions_path)
    state = validate_actions(study_dir, data)
    path = state_path(study_dir)
    if path.exists() and not reset:
        old = _load_json(path)
        if isinstance(old, dict) and old.get("actions_sha256") != state["actions_sha256"]:
            raise ResearchRunError(
                "existing research-run state differs from the new actions; "
                "use --reset to replace it and re-authorize")
        return old
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(path, state)
    return state


def _save(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".research-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_state(study_dir: Path) -> Dict[str, Any]:
    path = state_path(study_dir)
    if not path.is_file():
        raise ResearchRunError("no research-run state; create one with `research plan`")
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ResearchRunError("research-run state must be an object")
    return data


def authorize(study_dir: Path, *, by: str) -> Dict[str, Any]:
    if not str(by or "").strip():
        raise ResearchRunError("authorization requires a named operator")
    state = load_state(study_dir)
    state["authorization"] = {
        "by": str(by).strip(), "at": _now(),
        "actions_sha256": state.get("actions_sha256"),
        "scope": "all actions in this run",
    }
    state["status"] = "authorized"
    _save(state_path(study_dir), state)
    return state


def _check_authorized(state: Dict[str, Any]) -> None:
    actions = state.get("actions") or []
    if not actions:
        raise ResearchRunError("research plan has no actions")
    hashes = [_sha({k: a[k] for k in
                   ("id", "node", "platform", "query", "limit", "fixture",
                    "cdp_url", "url", "ack_terms")}) for a in actions]
    if hashes != [a.get("action_sha256") for a in actions] or _sha(hashes) != state.get("actions_sha256"):
        raise ResearchRunError("research plan changed; prepare and re-authorize the new plan")
    auth = state.get("authorization")
    if not isinstance(auth, dict) or not auth.get("by"):
        raise ResearchRunError("research actions are not authorized; run `research authorize --by NAME`")
    if auth.get("actions_sha256") != state.get("actions_sha256"):
        raise ResearchRunError(
            "authorization is stale: the action list changed; re-authorize the new plan")


@contextmanager
def _run_lock(study_dir):
    # POSIX cross-process lock; Windows keeps the state machine but has no fcntl.
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows fallback
        fcntl = None
    if fcntl is None:
        yield
        return
    path = state_path(study_dir).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ResearchRunError("research run is already executing")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run(study_dir: Path, *, max_steps: int = 1, analyze: bool = False) -> Dict[str, Any]:
    with _run_lock(study_dir):
        return _run(study_dir, max_steps=max_steps, analyze=analyze)


def _run(study_dir: Path, *, max_steps: int = 1, analyze: bool = False) -> Dict[str, Any]:
    if max_steps < 1 or max_steps > 20:
        raise ResearchRunError("max_steps must be 1..20")
    state = load_state(study_dir)
    _check_authorized(state)
    completed = 0
    for action in state.get("actions") or []:
        if completed >= max_steps:
            break
        if action.get("state") == "completed":
            continue
        if action.get("state") in ("blocked", "running"):
            state["status"] = "blocked"
            break
        action["state"] = "running"
        state["status"] = "running"
        _save(state_path(study_dir), state)
        try:
            kwargs = {
                "study_dir": Path(study_dir),
                "platform": action["platform"],
                "query": action["query"],
                "limit": action["limit"],
                "fixture": Path(action["fixture"]) if action.get("fixture") else None,
                "cdp_url": action.get("cdp_url"),
                "url": action.get("url"),
                "ack_terms": bool(action.get("ack_terms")),
            }
            result = sure_engine.collect_platform(**kwargs)
        except Exception as exc:  # surface the exact failure in the run ledger
            action["state"] = "blocked"
            action["result"] = {"status": "error", "reason": "%s: %s" % (type(exc).__name__, exc)}
            state["status"] = "blocked"
            break
        action["result"] = result
        if result.get("status") in SUCCESS:
            action["state"] = "completed"
            state["budget"]["used_records"] = int(state["budget"].get("used_records", 0)) + int(
                result.get("records", 0) or 0)
            completed += 1
            _save(state_path(study_dir), state)
        elif result.get("status") == "planned":
            action["state"] = "blocked"
            state["status"] = "blocked"
            break
        else:
            action["state"] = "blocked"
            state["status"] = "blocked"
            break
    if all(a.get("state") == "completed" for a in state.get("actions") or []):
        state["status"] = "completed"
    _save(state_path(study_dir), state)
    analysis = None
    if analyze and any(a.get("state") == "completed" for a in state.get("actions") or []):
        analysis = sure_engine.analyze_study(Path(study_dir), None)
        state["analysis"] = analysis
    state["updated_at"] = _now()
    _save(state_path(study_dir), state)
    return {"state": state, "analysis": analysis}


def status(study_dir: Path) -> Dict[str, Any]:
    state = load_state(study_dir)
    counts: Dict[str, int] = {}
    for action in state.get("actions") or []:
        key = str(action.get("state") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {
        "run_id": state.get("run_id"), "study_id": state.get("study_id"),
        "status": state.get("status"), "authorized": bool(state.get("authorization")),
        "counts": counts, "budget": state.get("budget"),
        "actions": [{"id": a.get("id"), "node": a.get("node"),
                     "platform": a.get("platform"), "state": a.get("state"),
                     "records": (a.get("result") or {}).get("records")}
                    for a in state.get("actions") or []],
    }

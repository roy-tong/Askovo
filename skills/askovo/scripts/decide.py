"""A-02 one-question decide orchestrator: a read-only layer over the Research Loop.

`askovo decide` turns one decision question (``askovo.decision-task/1``) into a
tracked research task. It composes existing capabilities instead of building a
second fact chain:

- the study workspace and the canonical seven-node chain come from the study
  template (``_create_workspace``), never a parallel truth;
- collection runs through ``research_loop`` and only after a human
  ``loop authorize``; this module never authorizes and never calls
  ``loop assess`` (candidates wait for human semantic review);
- delivery is a partial, gap-listing projection of the canonical artifacts
  (``decision_review`` + loop state), never an invented conclusion.

Product-layer states (PRD A-02, a projection over loop state, not a second
canonical state machine)::

    created -> scoped -> collecting -> analyzed -> review_required
            -> brief_ready -> delivered
    exceptions: needs_input | blocked | interrupted | cancelled

Every status carries the C-01 delegation fields (``next_actor``,
``next_required_action``, ``blocked_reason_code``, ``last_updated_at``,
``has_pending_external_effect``, ``artifact_refs``) and failures carry stable
``reason_code`` values from the C-01 error registry instead of prose that
looks like success.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import research_loop
import sure_engine

SCHEMA = "askovo.decision-task/1"
KIND = "askovo.decide-task"
TASK_SCHEMA_VERSION = "1.0"
BRIEF_KIND = "askovo.decide-brief"

DECISION_TYPES: Dict[str, Dict[str, Any]] = {
    "prioritize_features": {
        "primary_deliverable": "decision_brief",
        "minimal_roles": ["product_manager", "user_researcher"],
        "focus": "rank user problems and candidate features by evidence-weighted impact",
    },
    "validate_hypothesis": {
        "primary_deliverable": "decision_brief",
        "minimal_roles": ["user_researcher", "business_analyst"],
        "focus": "test declared hypotheses against collected behavior and counter-evidence",
    },
}

PRODUCT_STATES = (
    "created", "scoped", "collecting", "analyzed", "review_required",
    "brief_ready", "delivered", "needs_input", "blocked", "interrupted", "cancelled",
)
# C-01 §3 error registry. decide emits a subset; the full registry is listed so
# mappings stay inside the frozen vocabulary.
REASON_CODES = (
    "INPUT_REQUIRED", "AUTH_REQUIRED", "REVIEW_REQUIRED", "UNSUPPORTED_SCOPE",
    "POLICY_DENIED", "RATE_LIMITED", "STALE_SOURCE",
    "INDETERMINATE_EXTERNAL_ACTION", "ARTIFACT_PARTIAL", "INTERNAL_ERROR",
)
DEFAULT_MAX_RECORDS = 200
LOOP_MAX_RECORDS = 5000  # research_loop envelope bound
DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_ACTIONS = 3

_STATE_REASONS = {
    "needs_input": "INPUT_REQUIRED",
    "review_required": "REVIEW_REQUIRED",
    "blocked": "INTERNAL_ERROR",
}


class DecideError(ValueError):
    """A decide rule was violated; always carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INTERNAL_ERROR",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code if reason_code in REASON_CODES else "INTERNAL_ERROR"
        self.suggestion = suggestion


# --------------------------------------------------------------------------- #
# input contract
# --------------------------------------------------------------------------- #

def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_input(raw: Any) -> Dict[str, Any]:
    """Validate and normalize an askovo.decision-task/1 document.

    Raises :class:`DecideError` with ``INPUT_REQUIRED`` (missing facts) or
    ``UNSUPPORTED_SCOPE`` (decision type / source outside the first batch).
    The task never degrades an unsupported request into a look-alike success.
    """
    if not isinstance(raw, dict):
        raise DecideError("decision task must be a JSON object", "INPUT_REQUIRED")
    schema = str(raw.get("schema") or SCHEMA)
    if schema != SCHEMA:
        raise DecideError(
            f"unsupported schema {schema!r}; expected {SCHEMA}", "UNSUPPORTED_SCOPE",
            "keep askovo.decision-task/1 or omit the schema field")
    question = " ".join(str(raw.get("question") or "").split())
    if not question:
        raise DecideError("question is required", "INPUT_REQUIRED",
                          "state the one decision question, e.g. 下一版先修哪些问题")
    decision_type = str(raw.get("decision_type") or "").strip()
    if not decision_type:
        raise DecideError("decision_type is required", "INPUT_REQUIRED",
                          "first batch: prioritize_features, validate_hypothesis")
    if decision_type not in DECISION_TYPES:
        raise DecideError(
            f"unsupported decision_type {decision_type!r}; first batch supports: "
            + ", ".join(sorted(DECISION_TYPES)), "UNSUPPORTED_SCOPE",
            "choose prioritize_features or validate_hypothesis; other types need a later ticket")
    product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
    repo = str(product.get("repo") or "").strip()
    if not repo or "/" not in repo:
        raise DecideError("product.repo is required as owner/name", "INPUT_REQUIRED")
    kind = str(product.get("kind") or "github_repository")
    if kind != "github_repository":
        raise DecideError(
            f"unsupported product.kind {kind!r}; first batch supports github_repository",
            "UNSUPPORTED_SCOPE")

    authorization = raw.get("authorization") if isinstance(raw.get("authorization"), dict) else {}
    allowed_raw = authorization.get("allowed_sources")
    allowed_raw = allowed_raw if isinstance(allowed_raw, list) else []
    platforms = sure_engine.platform_index()
    allowed: List[str] = []
    for item in allowed_raw:
        name = str(item or "").strip().lower()
        if not name:
            continue
        if name not in platforms:
            raise DecideError(
                f"unsupported source {name!r}; supported platforms: "
                + ", ".join(sorted(platforms)), "UNSUPPORTED_SCOPE",
                "import an authorized export instead of an unsupported live source")
        if name not in allowed:
            allowed.append(name)
    max_records = authorization.get("max_records", DEFAULT_MAX_RECORDS)
    if isinstance(max_records, bool) or not isinstance(max_records, int):
        raise DecideError("authorization.max_records must be an integer", "INPUT_REQUIRED")
    if not 1 <= max_records <= LOOP_MAX_RECORDS:
        raise DecideError(
            f"authorization.max_records must be 1..{LOOP_MAX_RECORDS}", "INPUT_REQUIRED")
    scope = raw.get("source_scope") if isinstance(raw.get("source_scope"), dict) else {}
    fixture = str(scope.get("fixture") or "").strip() or None
    if fixture and allowed and "github" not in allowed and not Path(fixture).is_file():
        raise DecideError("source_scope.fixture does not exist", "INPUT_REQUIRED")
    if fixture and not Path(fixture).is_file():
        raise DecideError(f"source_scope.fixture does not exist: {fixture}", "INPUT_REQUIRED")

    normalized = {
        "schema": SCHEMA,
        "question": question,
        "product": {"kind": kind, "repo": repo},
        "decision_type": decision_type,
        "audience": raw.get("audience") if isinstance(raw.get("audience"), dict) else {},
        "source_scope": {
            "issues": bool(scope.get("issues", True)),
            "discussions": bool(scope.get("discussions", False)),
            "updated_since": str(scope.get("updated_since") or "") or None,
            "fixture": fixture,
        },
        "authorization": {
            "approved_by": str(authorization.get("approved_by") or "").strip() or None,
            "allowed_sources": allowed,
            "max_records": int(max_records),
        },
        "deadline": str(raw.get("deadline") or "").strip() or None,
        "delivery": (raw.get("delivery") if isinstance(raw.get("delivery"), dict)
                     else {"primary": "decision_brief", "secondary": []}),
    }
    return normalized


def input_hash(normalized: Dict[str, Any]) -> str:
    """Deterministic task identity: same question/scope/authorization, same id."""
    digest_source = {key: value for key, value in normalized.items() if key != "schema"}
    return _sha(digest_source)


def task_id_for(normalized: Dict[str, Any]) -> str:
    return "A-TASK-" + input_hash(normalized)[:8].upper()


# --------------------------------------------------------------------------- #
# task storage (atomic task.json + append-only run-log.jsonl)
# --------------------------------------------------------------------------- #

def default_workspace() -> Path:
    return Path(os.environ.get("ASKOVO_DECIDE_HOME") or "./askovo-decide").resolve()


def _task_dir(workspace: Path, task_id: str) -> Path:
    return Path(workspace).resolve() / "tasks" / task_id


def _task_path(workspace: Path, task_id: str) -> Path:
    return _task_dir(workspace, task_id) / "task.json"


def _log_path(workspace: Path, task_id: str) -> Path:
    return _task_dir(workspace, task_id) / "run-log.jsonl"


def _save_task(workspace: Path, task: Dict[str, Any]) -> None:
    path = _task_path(workspace, str(task.get("task_id")))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".decide-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(task, ensure_ascii=False, indent=2) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _append_log(workspace: Path, task_id: str, event: Dict[str, Any]) -> None:
    path = _log_path(workspace, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": _now(), **event}
    with path.open("a", encoding="utf-8") as out:  # append-only run journal
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_task(workspace: Path, task_id: str) -> Dict[str, Any]:
    path = _task_path(workspace, task_id)
    if not path.is_file():
        raise DecideError(f"unknown decide task {task_id!r} under {Path(workspace).resolve()}",
                          "INPUT_REQUIRED", "check `askovo decide status` task ids")
    task = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        raise DecideError(f"task file for {task_id} is corrupt", "INTERNAL_ERROR")
    return task


@contextmanager
def _lock(workspace: Path, task_id: str):
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows keeps the state machine
        fcntl = None
    if fcntl is None:
        yield
        return
    path = _task_dir(workspace, task_id) / ".lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DecideError("decide task is already executing", "INTERNAL_ERROR")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _transition(workspace: Path, task: Dict[str, Any], state: str, *,
                reason_code: Optional[str] = None, detail: str = "") -> None:
    if state not in PRODUCT_STATES:
        raise DecideError(f"unknown product state {state!r}", "INTERNAL_ERROR")
    previous = task.get("state")
    task["state"] = state
    task["updated_at"] = _now()
    entry = {"state": state, "at": _now(),
             "reason_code": reason_code or _STATE_REASONS.get(state),
             "detail": detail[:400]}
    history = task.setdefault("phase_history", [])
    if (history and history[-1].get("state") == entry["state"]
            and history[-1].get("reason_code") == entry["reason_code"]):
        # Re-observing the same gate is not a new phase: refresh it in place so a
        # retried `--run` does not pile up identical history entries.
        history[-1] = entry
    else:
        history.append(entry)
    _save_task(workspace, task)
    _append_log(workspace, str(task["task_id"]), {
        "event": "transition", "from": previous, "to": state,
        "reason_code": entry["reason_code"], "detail": detail[:400]})


# --------------------------------------------------------------------------- #
# study binding and planning
# --------------------------------------------------------------------------- #

def _import_fixture(study_dir: Path, source: Path) -> str:
    """Copy an authorized export into the study and return its study-relative path.

    ``research_loop.eligible_sources`` only accepts fixtures inside the study
    directory: a study must own the snapshot it later cites. Copying keeps the
    offline route reproducible and leaves the caller's export untouched.
    """
    study_dir = Path(study_dir).resolve()
    target_dir = study_dir / "01-sources" / "authorized"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(source).name
    if Path(source).resolve() != target.resolve():
        shutil.copyfile(str(Path(source).resolve()), str(target))
    return str(target.relative_to(study_dir))


def _bind_study(workspace: Path, task_id: str, study: Dict[str, Any]) -> None:
    """Record a bound study under ``<workspace>/studies`` (one binding per task)."""
    studies = Path(workspace).resolve() / "studies"
    studies.mkdir(parents=True, exist_ok=True)
    (studies / f"{task_id}.json").write_text(json.dumps({
        "schema_version": TASK_SCHEMA_VERSION,
        "kind": KIND,
        "task_id": task_id,
        "mode": study.get("mode"),
        "study_dir": study.get("dir"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scaffold_study(workspace: Path, task: Dict[str, Any]) -> Path:
    """Create the study from the bundled template; placeholders stay assumptions."""
    study_dir = Path(workspace).resolve() / "studies" / str(task["task_id"])
    task_input = task["input"]
    cli = research_loop.cli_module()
    cli._create_workspace(study_dir, str(task["study"]["study_id"]),
                          task_input["question"], task_input["question"], [])
    study_path = study_dir / "study.json"
    study = json.loads(study_path.read_text(encoding="utf-8"))
    decision = study.setdefault("decision", {})
    decision["question"] = task_input["question"]
    decision["owner"] = task_input["authorization"].get("approved_by") or "待填写"
    if task_input.get("deadline"):
        decision["deadline"] = task_input["deadline"]
    if not decision.get("options"):
        decision["options"] = ["优先处理候选问题（待证据复核）", "先补证据再排期", "暂不处理"]
    scope = study.setdefault("scope", {})
    scope["allowed_sources"] = list(task_input["authorization"]["allowed_sources"])
    updated_since = (task_input.get("source_scope") or {}).get("updated_since")
    window = scope.setdefault("source_time_window", {})
    if isinstance(window, dict) and updated_since:
        window["start"] = updated_since
    fixture = (task_input.get("source_scope") or {}).get("fixture")
    if fixture:
        fixtures = study.setdefault("research_loop", {}).setdefault("fixtures", {})
        fixtures["github"] = _import_fixture(study_dir, Path(fixture))
    else:
        adapters = study.get("source_adapters") if isinstance(study.get("source_adapters"), dict) else {}
        for platform in scope["allowed_sources"]:
            if isinstance(adapters.get(platform), dict):
                adapters[platform]["enabled"] = True
    study_path.write_text(json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return study_dir


def _study_dir_of(workspace: Path, task: Dict[str, Any]) -> Path:
    entry = task.get("study") or {}
    path = Path(str(entry.get("dir") or ""))
    if not path.is_absolute():
        path = Path(workspace).resolve() / path
    return path


def _declared_fixture(task: Dict[str, Any]) -> bool:
    """True when the task itself names an authorized offline export."""
    scope = (task.get("input") or {}).get("source_scope") or {}
    return bool(scope.get("fixture"))


def _declared_authorization(task: Dict[str, Any]) -> bool:
    """True only when the task declares a named owner *and* an approved source.

    This is a declaration, not a grant: the research loop still requires its own
    human ``loop authorize`` before a single record is read (C-01 §2 red line).
    """
    authorization = (task.get("input") or {}).get("authorization") or {}
    return bool(authorization.get("approved_by")) and bool(authorization.get("allowed_sources"))


def _plan(workspace: Path, task: Dict[str, Any]) -> None:
    """Scope the task: check sources, plan the loop once, record the digest."""
    if task.get("plan", {}).get("planned"):
        return  # idempotent: planning happens exactly once per task
    if not _declared_authorization(task):
        # C-01: a task without a declared owner and at least one approved source
        # is not authorized. Refuse before any study plan or read exists.
        task["state_detail"] = {
            "reason": "no declared authorization for any source",
            "import_tasks": _import_tasks(task, []),
        }
        _transition(workspace, task, "needs_input", reason_code="AUTH_REQUIRED",
                    detail="a named owner must declare allowed_sources before decide plans or reads")
        return
    study_dir = _study_dir_of(workspace, task)
    sources = research_loop.eligible_sources(study_dir)
    if not sources:
        blockers = research_loop._source_blockers(study_dir)
        task["state_detail"] = {
            "reason": "no eligible authorized source",
            "import_tasks": _import_tasks(task, blockers),
        }
        _transition(workspace, task, "needs_input", reason_code="AUTH_REQUIRED",
                    detail="no eligible source: provide authorization and an adapter or export")
        return
    try:
        state = research_loop.plan(
            study_dir,
            max_rounds=DEFAULT_MAX_ROUNDS,
            max_actions_per_round=DEFAULT_MAX_ACTIONS,
            max_records_total=int(task["input"]["authorization"]["max_records"]),
            reset=False,
        )
    except research_loop.LoopError as exc:
        task["state_detail"] = {"reason": str(exc)}
        _transition(workspace, task, "needs_input", reason_code="INPUT_REQUIRED",
                    detail=f"study loop state conflict: {exc}")
        return
    envelope = state.get("envelope") or {}
    task["plan"] = {
        "planned": True,
        "deliverable": (task["input"].get("delivery") or {}).get("primary") or "decision_brief",
        "minimal_roles": DECISION_TYPES[task["input"]["decision_type"]]["minimal_roles"],
        "focus": DECISION_TYPES[task["input"]["decision_type"]]["focus"],
        "digest": {
            "envelope": {key: envelope.get(key) for key in
                         ("max_rounds", "max_actions_per_round", "max_records_total",
                          "max_records_per_action", "allowed_platforms", "platform_modes")},
            "sources": [{"platform": s.get("platform"), "mode": s.get("mode")} for s in sources],
            "gap_counts": research_loop.gap_counts(state.get("gaps") or []),
        },
    }
    task["budget"] = {
        "max_records": int(envelope.get("max_records_total") or 0),
        "max_rounds": int(envelope.get("max_rounds") or 0),
        "used_records": 0,
        "rounds_used": 0,
    }
    _transition(workspace, task, "scoped",
                detail="loop plan written; awaiting human authorization, no reading yet")


def _import_tasks(task: Dict[str, Any], blockers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Concrete human tasks that make the task runnable; never a fake route."""
    tasks: List[Dict[str, Any]] = []
    for blocker in blockers:
        tasks.append({
            "action": "unblock_source",
            "platform": blocker.get("platform"),
            "detail": blocker.get("reason"),
        })
    if not tasks:
        authorization = (task.get("input") or {}).get("authorization") or {}
        sources = authorization.get("allowed_sources") or []
        tasks.append({
            "action": "authorize_sources",
            "detail": "authorization.allowed_sources is empty; declare the platforms the "
                      "owner approved (first batch: public github reads or an authorized export)",
        })
        if not sources:
            tasks.append({
                "action": "import_authorized_export",
                "detail": "place an authorized export under 01-sources/ and reference it via "
                          "source_scope.fixture (offline route, no live reads)",
            })
        else:
            tasks.append({
                "action": "import_authorized_export",
                "detail": "no enabled adapter for "
                          + ", ".join(str(s) for s in sources)
                          + "; import an authorized export via source_scope.fixture",
            })
    return tasks


# --------------------------------------------------------------------------- #
# execution (gated by the loop's own human authorization)
# --------------------------------------------------------------------------- #

_BLOCKED_REASONS = {
    "awaiting_external_validation": "REVIEW_REQUIRED",
    "connector_blocked": "RATE_LIMITED",
}


def _execute(workspace: Path, task: Dict[str, Any]) -> None:
    """Advance a planned task as far as the human gates allow; never past them."""
    study_dir = _study_dir_of(workspace, task)
    if not task.get("plan", {}).get("planned"):
        _plan(workspace, task)  # retried on every --run: the human may have fixed the input
        if not task.get("plan", {}).get("planned"):
            return  # needs_input: nothing to execute
    loop = research_loop.load_state_or_none(study_dir)
    if loop is None:
        raise DecideError("study loop state vanished; re-run decide start", "INTERNAL_ERROR")

    if task.get("state") == "cancelled":
        raise DecideError(
            f"task {task['task_id']} was cancelled by "
            f"{(task.get('cancel') or {}).get('by', 'operator')}; create a new task for a new run",
            "POLICY_DENIED")

    # Scope integrity: the authorized envelope must stay inside the declared sources.
    envelope = loop.get("envelope") or {}
    allowed = {str(s) for s in task["input"]["authorization"]["allowed_sources"]}
    outside = [p for p in (envelope.get("allowed_platforms") or []) if str(p) not in allowed]
    if outside:
        task["state_detail"] = {"reason": "authorized envelope exceeds declared sources",
                                "platforms": outside}
        _transition(workspace, task, "blocked", reason_code="POLICY_DENIED",
                    detail="envelope platforms outside authorization: " + ", ".join(map(str, outside)))
        return

    status_name = str(loop.get("status") or "")
    if status_name == "needs_review":
        task["state_detail"] = {
            "reason": "a collection action was interrupted; the journal needs inspection",
            "loop_state": str(research_loop.state_path(study_dir)),
        }
        _transition(workspace, task, "interrupted",
                    detail="interrupted run: inspect the loop journal and reconcile; "
                           "interrupted actions are never auto-repeated")
        return
    if status_name in ("completed", "blocked"):
        _absorb_terminal(workspace, task, study_dir)  # idempotent re-run protection
        return
    if not loop.get("authorization"):
        task["state_detail"] = {
            "reason": "research loop envelope is not human-authorized",
            "next": f"askovo loop authorize {study_dir} --by NAME",
        }
        if _declared_fixture(task):
            # The task names an authorized export, so the plan is runnable and the
            # only remaining gate is the human `loop authorize`. Stay `scoped` (the
            # C-01 awaiting_authorization projection) instead of inventing a failure.
            _save_task(workspace, task)
            _append_log(workspace, str(task["task_id"]), {
                "event": "run_gated", "reason_code": "AUTH_REQUIRED",
                "detail": "human loop authorize required; no record read"})
            return
        _transition(workspace, task, "needs_input", reason_code="AUTH_REQUIRED",
                    detail="decide cannot self-authorize; a named operator must run loop authorize")
        return

    if task.get("state") not in ("collecting",):
        _transition(workspace, task, "collecting",
                    detail="executing the authorized research loop envelope")
    try:
        research_loop.run(study_dir)
    except research_loop.InterruptedRunError as exc:
        task["state_detail"] = {"reason": str(exc),
                                "loop_state": str(research_loop.state_path(study_dir))}
        _transition(workspace, task, "interrupted",
                    detail=f"interrupted: {exc}; reconcile before any replay")
        return
    except research_loop.DesignGateError as exc:
        task["state_detail"] = {"reason": str(exc)}
        _transition(workspace, task, "needs_input", reason_code="INPUT_REQUIRED",
                    detail=f"design gate failed: {exc}")
        return
    except research_loop.LoopError as exc:
        task["state_detail"] = {"reason": str(exc)}
        _transition(workspace, task, "blocked", reason_code="INTERNAL_ERROR", detail=str(exc))
        return
    _absorb_terminal(workspace, task, study_dir)


def _absorb_terminal(workspace: Path, task: Dict[str, Any], study_dir: Path) -> None:
    """Map a terminal loop status onto product states without re-running."""
    summary = research_loop.status(study_dir)
    loop_status = str(summary.get("status") or "")
    stop_reason = str(summary.get("stop_reason") or "")
    totals = summary.get("totals") or {}
    budget = task.setdefault("budget", {})
    budget["used_records"] = int(totals.get("records") or 0)
    budget["rounds_used"] = len(summary.get("rounds") or [])
    candidates = int(summary.get("candidates") or 0)

    if loop_status == "completed":
        if candidates:
            _transition(workspace, task, "analyzed",
                        detail="loop finished collecting and describing candidates")
            _transition(workspace, task, "review_required", reason_code="REVIEW_REQUIRED",
                        detail="candidates wait for human semantic review (loop assess); "
                               "decide never auto-assesses")
        elif stop_reason in ("no_new_material", "sources_exhausted", "no_actionable_source"):
            task["state_detail"] = {"reason": f"loop stopped: {stop_reason or 'no material'}",
                                    "import_tasks": _import_tasks(task, [])}
            _transition(workspace, task, "needs_input", reason_code="INPUT_REQUIRED",
                        detail=f"no new material ({stop_reason}); see import tasks")
        else:
            _transition(workspace, task, "analyzed", detail=f"loop stopped: {stop_reason}")
        return
    if loop_status == "blocked":
        reason_code = _BLOCKED_REASONS.get(stop_reason, "INPUT_REQUIRED")
        task["state_detail"] = {"reason": f"loop blocked: {stop_reason}"}
        _transition(workspace, task, "blocked" if stop_reason == "awaiting_external_validation"
                    else "needs_input", reason_code=reason_code,
                    detail=f"loop blocked: {stop_reason}")
        return
    if loop_status == "needs_review":
        task["state_detail"] = {"reason": "loop needs review after interruption",
                                "loop_state": str(research_loop.state_path(study_dir))}
        _transition(workspace, task, "interrupted", detail="loop needs_review; reconcile first")
        return
    # planned / authorized / running: nothing new to absorb
    if loop_status in ("planned", "authorized") and task.get("state") == "created":
        _transition(workspace, task, "scoped", detail="loop not yet run")


# --------------------------------------------------------------------------- #
# public orchestration API (shared by CLI and MCP)
# --------------------------------------------------------------------------- #

def _ensure_plan(workspace: Path, task: Dict[str, Any]) -> None:
    """Fill in a missing plan; never rewind a phase.

    A dry ``decide start`` is read-only (PRD §2.4: the default shows the plan
    without reading). The A-02 product state machine only moves forward
    (``created -> scoped -> collecting -> analyzed -> review_required ->
    brief_ready -> delivered``), so re-submitting an identical task must not pull
    a task that already collected back to ``scoped`` and must not send its
    ``status`` next action back to "loop authorize". Only a task without a plan
    gets one derived; everything else is reported as it is.
    """
    if task.get("plan", {}).get("planned"):
        return
    _plan(workspace, task)


def start(workspace: Path, raw_input: Optional[Dict[str, Any]] = None, *,
          task_id: Optional[str] = None, run: bool = False,
          study_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Create (idempotently) or resume a decide task; reading stays gated."""
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)  # start owns its workspace root
    if task_id:
        with _lock(workspace, task_id):
            task = load_task(workspace, task_id)
            if task.get("state") == "cancelled":
                raise DecideError(
                    f"task {task_id} was cancelled by "
                    f"{(task.get('cancel') or {}).get('by', 'operator')}; create a new task",
                    "POLICY_DENIED")
            if raw_input is not None:
                normalized = normalize_input(raw_input)
                if input_hash(normalized) != task.get("input_hash"):
                    raise DecideError(
                        "input differs from the frozen task input; resume without --input "
                        "or create a new task", "INPUT_REQUIRED")
            if run:
                _execute(workspace, task)
            else:
                _ensure_plan(workspace, task)
            return status(workspace, task_id)

    if raw_input is None:
        raise DecideError("decide start needs a decision task (--input FILE or MCP task object)",
                          "INPUT_REQUIRED")
    normalized = normalize_input(raw_input)
    new_id = task_id_for(normalized)
    with _lock(workspace, new_id):
        existing = None
        if _task_path(workspace, new_id).is_file():
            existing = load_task(workspace, new_id)  # A9: identical input resumes, never duplicates
        if existing is None:
            task = {
                "schema_version": TASK_SCHEMA_VERSION,
                "kind": KIND,
                "task_id": new_id,
                "input": normalized,
                "input_hash": input_hash(normalized),
                "created_at": _now(),
                "updated_at": _now(),
                "state": "created",
                "state_detail": {},
                "phase_history": [],
                "study": {},
                "plan": {"planned": False},
                "budget": {"max_records": int(normalized["authorization"]["max_records"]),
                           "max_rounds": DEFAULT_MAX_ROUNDS,
                           "used_records": 0, "rounds_used": 0},
                "artifacts": {},
            }
            _save_task(workspace, task)
            _append_log(workspace, new_id, {"event": "created", "to": "created",
                                            "detail": normalized["question"]})
            _transition(workspace, task, "created", detail="task registered")
            if study_dir is not None:
                task["study"] = {"mode": "bound", "dir": str(Path(study_dir).resolve())}
                _bind_study(workspace, new_id, task["study"])
            else:
                task["study"] = {"mode": "scaffolded", "study_id": "decide-" + new_id[-8:].lower(),
                                 "dir": None}
                task["study"]["dir"] = str(_scaffold_study(workspace, task))
            task["artifacts"]["study"] = task["study"]["dir"]
            _save_task(workspace, task)
            _append_log(workspace, new_id, {
                "event": "study_bound", "mode": task["study"]["mode"],
                "study_dir": task["study"]["dir"]})
            _plan(workspace, task)
        else:
            task = existing
            if not run:
                _ensure_plan(workspace, task)
        if run:
            _execute(workspace, task)
        return status(workspace, new_id)


def cancel(workspace: Path, task_id: str, *, by: str) -> Dict[str, Any]:
    """Cancel a task; further reading is refused and external effects stop."""
    operator = str(by or "").strip()
    if not operator:
        raise DecideError("cancel requires a named operator (--by)", "INPUT_REQUIRED")
    workspace = Path(workspace).resolve()
    with _lock(workspace, task_id):
        task = load_task(workspace, task_id)
        if task.get("state") == "delivered":
            raise DecideError("delivered tasks are immutable; cancel applies before delivery",
                              "POLICY_DENIED")
        task["cancel"] = {"by": operator, "at": _now()}
        _transition(workspace, task, "cancelled",
                    detail=f"cancelled by {operator}; no further reading or replay")
        return status(workspace, task_id)


def apply_mode(task: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Map the PRD §2.4 ``--mode`` research-mode alias onto ``decision_type``.

    ``discover``/``validate`` are the only first-batch modes; ``optimize`` is
    refused instead of silently downgraded to a different question type.
    """
    name = str(mode or "").strip().lower()
    if not name:
        return task
    mapping = {"discover": "prioritize_features", "validate": "validate_hypothesis"}
    if name not in mapping:
        raise DecideError(
            f"unsupported mode {name!r}; first batch supports discover, validate",
            "UNSUPPORTED_SCOPE",
            "choose discover or validate; optimize needs a later ticket")
    declared = str(task.get("decision_type") or "").strip()
    if declared and declared != mapping[name]:
        raise DecideError(
            f"--mode {name} maps to decision_type {mapping[name]!r} but "
            f"{declared!r} was requested; pass one of them", "INPUT_REQUIRED")
    task["decision_type"] = mapping[name]
    return task


def _expert_refusal(action: str, task_id: str, *, by: str = "",
                    since: str = "") -> DecideError:
    """Build the refusal for a PRD §2.4 expert entry this ticket does not implement.

    A named refusal is the correct answer: the alternative is a command that
    prints a plausible-looking success without a review or a delta engine.
    """
    hint = {
        "review": f"Until then use `askovo review {task_id}` (deterministic review) or "
                  f"`askovo decide brief {task_id}` (partial brief).",
        "delta": f"Until then use `askovo decide brief {task_id}`; the accepted-baseline "
                 f"delta ships with the Decision Snapshot work (A-04).",
    }[action]
    operator = f" by {by}" if str(by or "").strip() else ""
    window = f" since {since}" if str(since or "").strip() else ""
    return DecideError(
        f"`askovo decide {action} {task_id}`{operator}{window} is not implemented in A-02; "
        f"the {action} entry ships in 后续工单 (A-04 Decision Brief + Decision Snapshot). "
        f"{hint}",
        "UNSUPPORTED_SCOPE",
        "report the gap instead of treating a stub as a completed review",
    )


def review(workspace: Path, task_id: str, *, by: str = "") -> Dict[str, Any]:
    """Expert entry (PRD §2.4): explicitly unsupported in A-02."""
    raise _expert_refusal("review", task_id, by=by)


def delta(workspace: Path, task_id: str, *, since: str = "") -> Dict[str, Any]:
    """Expert entry (PRD §2.4): explicitly unsupported in A-02."""
    raise _expert_refusal("delta", task_id, since=since)


def task_from_flags(*, question: str = "", repo: str = "", decision_type: str = "",
                    max_records: int = DEFAULT_MAX_RECORDS, fixture: str = "",
                    deadline: str = "", approved_by: str = "",
                    allowed_sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build an ``askovo.decision-task/1`` document from PRD §2.4 command flags.

    ``--question``/``--repo`` is the direct CLI form; the JSON document stays the
    canonical input. Declaring ``repo`` never authorizes a read on its own: the
    loop's human ``authorize`` step is still required.
    """
    return {
        "schema": SCHEMA,
        "question": question,
        "product": {"kind": "github_repository", "repo": repo},
        "decision_type": decision_type or "prioritize_features",
        "audience": {"description": "", "confidence": "declared"},
        "source_scope": {
            "issues": True,
            "discussions": False,
            "updated_since": None,
            "fixture": fixture or None,
        },
        "authorization": {
            "approved_by": approved_by or None,
            "allowed_sources": list(allowed_sources or ["github"]),
            "max_records": int(max_records),
        },
        "deadline": deadline or None,
        "delivery": {"primary": "decision_brief", "secondary": []},
    }


def _gap_view(study_dir: Path, loop_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    view: Dict[str, Any] = {"total": 0, "unresolved": [], "by_state": {}}
    if loop_summary is None:
        return view
    gaps = loop_summary.get("gaps") or {}
    view["total"] = int(gaps.get("total") or 0)
    for key in ("open", "collected", "analyzed", "resolved", "unresolvable"):
        view["by_state"][key] = int(gaps.get(key) or 0)
    view["unresolved"] = int(gaps.get("open") or 0) + int(gaps.get("collected") or 0) \
        + int(gaps.get("analyzed") or 0)
    return view


def _next_step(workspace: Path, task: Dict[str, Any],
               loop_summary: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """C-01: every state has a concrete next actor and next required action."""
    state = str(task.get("state") or "created")
    study_dir = _study_dir_of(workspace, task)
    authorized = bool(loop_summary and loop_summary.get("authorized"))
    if state == "created":
        return {"next_actor": "delegating_agent",
                "next_required_action": "re-run `askovo decide start` to scope the task"}
    if state == "scoped":
        gate = f"`askovo loop authorize {study_dir} --by NAME` (human)"
        if authorized:
            return {"next_actor": "human_operator",
                    "next_required_action": f"{gate} already recorded; re-run "
                                            f"`askovo decide start --task {task['task_id']} "
                                            f"--run` to absorb the loop"}
        return {"next_actor": "human_operator",
                "next_required_action": f"{gate}, then `askovo decide start "
                                        f"--task {task['task_id']} --run`",
                "blocked_reason_code": "AUTH_REQUIRED"}
    if state == "needs_input":
        detail = task.get("state_detail") or {}
        reason = str(detail.get("reason") or "input missing")
        code = "AUTH_REQUIRED" if "authoriz" in reason.lower() or "source" in reason.lower() \
            else "INPUT_REQUIRED"
        parts = [reason]
        if detail.get("next"):
            parts.append(str(detail["next"]))
        import_tasks = detail.get("import_tasks") or []
        if import_tasks:
            parts.append("import tasks: " + json.dumps(import_tasks, ensure_ascii=False)[:400])
        return {"next_actor": "human_operator",
                "next_required_action": "; ".join(parts),
                "blocked_reason_code": code}
    if state == "collecting":
        return {"next_actor": "askovo",
                "next_required_action": "wait for the authorized loop run to finish; "
                                        "re-run `askovo decide start --task <id> --run` if it crashed"}
    if state in ("analyzed", "review_required"):
        return {"next_actor": "human_reviewer",
                "next_required_action": f"review candidates, then `askovo loop assess {study_dir} "
                                        f"--gap <key> --verdict resolved|unresolvable --by NAME` "
                                        f"(decide never auto-passes review)",
                "blocked_reason_code": "REVIEW_REQUIRED"}
    if state == "brief_ready":
        return {"next_actor": "business_owner",
                "next_required_action": f"read the partial brief "
                                        f"{_task_dir(workspace, str(task['task_id'])) / 'brief.md'}; "
                                        f"decision review/acceptance ships in a later ticket (A-04)",
                "blocked_reason_code": "REVIEW_REQUIRED"}
    if state == "delivered":
        return {"next_actor": "business_owner",
                "next_required_action": "validate the outcome; delivered never means decision_approved"}
    if state == "blocked":
        return {"next_actor": "human_operator",
                "next_required_action": str((task.get("state_detail") or {}).get("reason")
                                            or "resolve the blocked source or study contract"),
                "blocked_reason_code": "INTERNAL_ERROR"}
    if state == "interrupted":
        return {"next_actor": "human_operator",
                "next_required_action": "inspect 04-findings/research-loop.json and the collected "
                                        "files, reconcile the interrupted action, then re-plan "
                                        "explicitly (`askovo loop plan --reset`); "
                                        "decide never auto-replays interrupted actions"}
    if state == "cancelled":
        return {"next_actor": "delegating_agent",
                "next_required_action": "task cancelled; create a new decide task for a new run "
                                        "(inputs are idempotency-keyed)"}
    return {"next_actor": "human_operator", "next_required_action": "inspect the task log"}


def _artifact_refs(workspace: Path, task: Dict[str, Any]) -> List[str]:
    study_dir = _study_dir_of(workspace, task)
    refs: List[str] = []
    for relative in ("study.json", "04-findings/product-reasoning.json",
                     "04-findings/demand-judgments.json", "04-findings/research-loop.json",
                     "04-findings/loop-candidates.json", "06-decision-review.json",
                     "06-decision-review.md"):
        candidate = study_dir / relative
        if candidate.is_file():
            refs.append(str(candidate))
    task_dir = _task_dir(workspace, str(task["task_id"]))
    for name in ("brief.md", "brief.json"):
        candidate = task_dir / name
        if candidate.is_file():
            refs.append(str(candidate))
    refs.append(str(_log_path(workspace, str(task["task_id"]))))
    return refs


def status(workspace: Path, task_id: str) -> Dict[str, Any]:
    """C-01 status projection: state, next actor/action, reason code, budget, gaps."""
    workspace = Path(workspace).resolve()
    task = load_task(workspace, task_id)
    study_dir = _study_dir_of(workspace, task)
    loop_summary = None
    if study_dir.is_dir() and (study_dir / "04-findings" / "research-loop.json").is_file():
        loop_summary = research_loop.status(study_dir)
        budget = task.setdefault("budget", {})
        budget["used_records"] = int((loop_summary.get("totals") or {}).get("records") or 0)
        budget["rounds_used"] = len(loop_summary.get("rounds") or [])
    step = _next_step(workspace, task, loop_summary)
    detail = task.get("state_detail") or {}
    pending_effects = str(task.get("state")) in ("collecting", "interrupted")
    return {
        "schema": SCHEMA,
        "task_id": task.get("task_id"),
        "state": task.get("state"),
        "question": (task.get("input") or {}).get("question"),
        "decision_type": (task.get("input") or {}).get("decision_type"),
        "repo": ((task.get("input") or {}).get("product") or {}).get("repo"),
        "next_actor": step["next_actor"],
        "next_required_action": step["next_required_action"],
        "blocked_reason_code": step.get("blocked_reason_code"),
        "last_updated_at": task.get("updated_at"),
        "has_pending_external_effect": pending_effects,
        "artifact_refs": _artifact_refs(workspace, task),
        "plan": task.get("plan") or {},
        "budget": task.get("budget") or {},
        "gaps": _gap_view(study_dir, loop_summary),
        "candidates": int((loop_summary or {}).get("candidates") or 0),
        "loop_status": (loop_summary or {}).get("status"),
        "loop_stop_reason": (loop_summary or {}).get("stop_reason"),
        "study_dir": str(study_dir) if task.get("study") else None,
        "state_detail": detail if detail else None,
        "log_path": str(_log_path(workspace, str(task.get("task_id")))),
    }


# --------------------------------------------------------------------------- #
# partial brief + result projection (read-only; never a second truth)
# --------------------------------------------------------------------------- #

def brief(workspace: Path, task_id: str, *, fmt: str = "json") -> Dict[str, Any]:
    """Write a partial decision brief: findings so far plus every gap, no invention."""
    workspace = Path(workspace).resolve()
    with _lock(workspace, task_id):
        task = load_task(workspace, task_id)
        if not task.get("study"):
            raise DecideError("task has no study yet; run decide start first", "INPUT_REQUIRED")
        study_dir = _study_dir_of(workspace, task)
        if not (study_dir / "study.json").is_file():
            raise DecideError("bound study is missing study.json", "INPUT_REQUIRED")
        loop_summary = None
        if (study_dir / "04-findings" / "research-loop.json").is_file():
            loop_summary = research_loop.status(study_dir)
        try:
            import decision_review
            review_payload = decision_review.review(study_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            review_payload = {"status": "unavailable", "reason": str(exc), "items": []}
        gaps = _gap_view(study_dir, loop_summary)
        unresolved = gaps.get("unresolved") or 0
        candidates = int((loop_summary or {}).get("candidates") or 0)
        supported = sum(1 for claim in _claims(study_dir) if claim.get("verdict") == "supported")
        artifact_status = "partial" if unresolved or not supported else "ready"
        document = {
            "schema_version": "1.0",
            "kind": BRIEF_KIND,
            "task_id": task_id,
            "question": (task.get("input") or {}).get("question"),
            "decision_type": (task.get("input") or {}).get("decision_type"),
            "generated_at": _now(),
            "artifact_status": artifact_status,
            "reason_code": "ARTIFACT_PARTIAL" if artifact_status == "partial" else None,
            "conclusion": {
                "kind": "recommendation_required",
                "current": "hold" if not supported else "candidate_ready_for_review",
                "note": "机器只给候选与缺口；结论是 recommendation，不是自动批准",
            },
            "options": _options(study_dir),
            "evidence": {
                "supported_claims": supported,
                "candidate_groups": candidates,
                "candidates_are_evidence": False,
                "note": "loop 候选没有证据等级；人工定级并写入判断后才改变结论",
            },
            "gaps": _gap_details(study_dir, loop_summary, review_payload),
            "restricted": [
                "样本为授权来源便利样本，不能外推总体比例",
                "无真实付费/留存行为证据时不得宣称商业验证",
                "delivered/brief_ready 不等于 decision_approved",
            ],
            "next_validation": _validation_backlog(study_dir, loop_summary, review_payload),
            "decision_state": "not_approved",
            "delivery_state": "partial" if artifact_status == "partial" else "brief_ready",
            "outcome_state": "not_measured",
            "causality_state": "not_claimed",
            "canonical_refs": [str(study_dir / relative) for relative in
                               ("study.json", "04-findings/product-reasoning.json",
                                "04-findings/demand-judgments.json",
                                "04-findings/loop-candidates.json")
                               if (study_dir / relative).is_file()],
            "boundary": (
                "Brief 是 canonical 链与研究循环的只读投影：列出缺口与假设，不编造访谈、"
                "转化率或验证结论；商业成立需要研究设计与可重复验证。"),
        }
        task_dir = _task_dir(workspace, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "brief.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (task_dir / "brief.md").write_text(_brief_markdown(document), encoding="utf-8")
        task["artifacts"]["brief_md"] = str(task_dir / "brief.md")
        task["artifacts"]["brief_json"] = str(task_dir / "brief.json")
        if str(task.get("state")) in ("analyzed", "review_required", "brief_ready"):
            _transition(workspace, task, "brief_ready", reason_code="ARTIFACT_PARTIAL",
                        detail="partial brief written; gaps stay visible")
        else:
            _save_task(workspace, task)
            _append_log(workspace, task_id, {
                "event": "brief_written", "artifact_status": artifact_status,
                "state_unchanged": task.get("state")})
        document["markdown_path"] = str(task_dir / "brief.md")
        document["json_path"] = str(task_dir / "brief.json")
        if fmt == "md":
            document["markdown"] = _brief_markdown(document)
        return document


def result(workspace: Path, task_id: str) -> Dict[str, Any]:
    """MCP high-level result: brief + evidence index + validation backlog + refs."""
    workspace = Path(workspace).resolve()
    document = brief(workspace, task_id)
    task = load_task(workspace, task_id)
    study_dir = _study_dir_of(workspace, task)
    candidates_doc: Dict[str, Any] = {"count": 0, "record_ids": [], "path": None}
    candidates_path = study_dir / "04-findings" / "loop-candidates.json"
    if candidates_path.is_file():
        try:
            candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            entries = candidates.get("candidates") or []
            record_ids: List[str] = []
            for entry in entries:
                for record_id in entry.get("record_ids") or []:
                    record_ids.append(str(record_id))
            candidates_doc = {"count": len(entries),
                              "record_ids": sorted(set(record_ids))[:50],
                              "path": str(candidates_path)}
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "task_id": task_id,
        "state": task.get("state"),
        "artifact_status": document["artifact_status"],
        "reason_code": document["reason_code"],
        "brief": document,
        "evidence_index": candidates_doc,
        "validation_backlog": document["next_validation"],
        "canonical_refs": document["canonical_refs"],
        "review_status": _review_status(study_dir),
        "decision_state": document["decision_state"],
        "delivery_state": document["delivery_state"],
        "outcome_state": document["outcome_state"],
        "causality_state": document["causality_state"],
        "boundary": document["boundary"],
    }


# --------------------------------------------------------------------------- #
# brief helpers (deterministic projections only)
# --------------------------------------------------------------------------- #

def _claims(study_dir: Path) -> List[Dict[str, Any]]:
    try:
        payload = research_loop.cli_module().audit_payload(Path(study_dir))
        return [claim for claim in payload.get("claims") or [] if isinstance(claim, dict)]
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError):
        return []


def _options(study_dir: Path) -> List[str]:
    try:
        study = json.loads((Path(study_dir) / "study.json").read_text(encoding="utf-8"))
        options = study.get("decision") or {}
        return [str(item) for item in options.get("options") or []]
    except (OSError, json.JSONDecodeError):
        return []


def _gap_details(study_dir: Path, loop_summary: Optional[Dict[str, Any]],
                 review_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    if loop_summary is not None:
        state = research_loop.load_state_or_none(Path(study_dir)) or {}
        resolved = research_loop._resolved_keys(state)
        for gap in (state.get("gaps") or [])[:12]:
            if not isinstance(gap, dict) or str(gap.get("key")) in resolved:
                continue
            details.append({
                "id": gap.get("id"), "kind": gap.get("kind"), "severity": gap.get("severity"),
                "gap_state": research_loop.gap_state(state, str(gap.get("key"))),
                "detail": gap.get("detail"),
            })
    for item in (review_payload.get("items") or [])[:10]:
        if isinstance(item, dict) and item.get("status") in ("fail", "warn"):
            details.append({"kind": "review_item", "severity": item.get("status"),
                            "detail": item.get("detail")})
    return details


def _validation_backlog(study_dir: Path, loop_summary: Optional[Dict[str, Any]],
                        review_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    backlog: List[Dict[str, Any]] = []
    if loop_summary is not None:
        state = research_loop.load_state_or_none(Path(study_dir)) or {}
        for task_item in state.get("external_validation_tasks") or []:
            if isinstance(task_item, dict):
                backlog.append({"kind": "external_validation", "gap_key": task_item.get("gap_key"),
                                "recommended_action": task_item.get("recommended_action"),
                                "requires": task_item.get("requires")})
        for action in (loop_summary.get("next_best_actions") or [])[:5]:
            candidate = (action or {}).get("candidate") or {}
            if candidate.get("action") in ("experiment", "request_external_evidence"):
                backlog.append({"kind": "candidate_action", "gap_key": action.get("gap_key"),
                                "action": candidate.get("action"),
                                "requires_separate_authorization": True})
    for item in (review_payload.get("items") or [])[:5]:
        if isinstance(item, dict) and item.get("status") == "fail" and item.get("next_action"):
            backlog.append({"kind": "review_next_action", "detail": item.get("next_action")})
    return backlog[:10]


def _review_status(study_dir: Path) -> str:
    path = Path(study_dir) / "06-decision-review.json"
    if not path.is_file():
        return "not_run"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("status") or "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


def _brief_markdown(document: Dict[str, Any]) -> str:
    lines = [
        f"# Decision Brief（partial）：{document.get('question')}",
        "",
        f"- task：`{document.get('task_id')}`；artifact：**{document.get('artifact_status')}**"
        f"（reason_code：{document.get('reason_code') or '-'}）",
        f"- decision_state：`{document.get('decision_state')}`；delivery_state："
        f"`{document.get('delivery_state')}`；outcome_state：`{document.get('outcome_state')}`；"
        f"causality_state：`{document.get('causality_state')}`",
        "",
        "## 结论（recommendation，不是自动批准）",
        "",
        f"- 当前：**{document['conclusion']['current']}**。{document['conclusion']['note']}",
        "",
        "## 选项",
        "",
    ]
    lines.extend(f"- {option}" for option in document.get("options") or []) or lines.append("- 无登记选项")
    lines.extend(["", "## 证据（候选，不是定级证据）", ""])
    evidence = document.get("evidence") or {}
    lines.append(f"- 通过审计的判断：{evidence.get('supported_claims', 0)}；"
                 f"候选证据组：{evidence.get('candidate_groups', 0)}。{evidence.get('note')}")
    lines.extend(["", "## 缺口（一屏可见）", ""])
    gaps = document.get("gaps") or []
    if gaps:
        for gap in gaps:
            lines.append(f"- [{gap.get('severity')}] {gap.get('kind')}（{gap.get('gap_state', '')}）："
                         f"{gap.get('detail')}")
    else:
        lines.append("- 无未解决缺口。")
    lines.extend(["", "## 受限结论", ""])
    lines.extend(f"- {item}" for item in document.get("restricted") or [])
    lines.extend(["", "## 下一个最低成本验证动作", ""])
    backlog = document.get("next_validation") or []
    if backlog:
        for item in backlog:
            lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
    else:
        lines.append("- 无（先人工语义复核候选）。")
    lines.extend(["", "## Canonical 引用", ""])
    lines.extend(f"- {ref}" for ref in document.get("canonical_refs") or [])
    lines.extend(["", "## 边界", "", str(document.get("boundary")), ""])
    return "\n".join(lines)

"""A-06 external research bridge: a bounded, auditable subprocess boundary.

`askovo external-research` runs a host adapter as a **real** child process and
stores its output as unverified candidates. Running someone else's code is the
highest-privilege thing this repository does, so the boundary is explicit:

- **environment allowlist (A29)** — the child environment is *built* from
  :data:`DEFAULT_ENV_ALLOWLIST` plus the entry's explicit ``extra_env`` plus four
  ``ASKOVO_*`` context variables. The parent environment is never inherited and
  then trimmed, so an unauthorized secret cannot leak by accident.
- **signed command registry (A30)** — only a command listed in
  ``01-sources/external-research.json`` with an ``access_basis``, a reviewer and a
  matching adapter SHA-256 may run. ``--trusted-local`` is the single explicit
  escape hatch for a pre-A-06 local workflow; it still requires ``--authorize``
  and its use is recorded in the run.
- **bounded streams (A31)** — stdout/stderr go to temporary files with a hard
  byte cap; an oversized run fails with ``RATE_LIMITED`` instead of being
  truncated into a success. The cap can only be lowered by a caller, never raised.
- **per-run identity (A32)** — every run gets its own ``ext-<utc>-<random>`` id
  and writes ``04-findings/external-research/<run_id>.json`` with exclusive
  create, so two runs in the same second both survive.
- **no path escape (A30)** — the output path is resolved (symlinks included) and
  must stay inside the study directory.
- **candidates stay candidates (A33)** — a URL is an unverified pointer, never a
  fetched fact. The bridge performs **no network access at all**; nothing here
  resolves a link, promotes an evidence level or marks a claim validated.

Zero network. The only external effect is the child process itself, gated by an
explicit human ``--authorize``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "askovo.external-research/1"
SCHEMA_VERSION = "1.0"
REGISTRY_RELATIVE = Path("01-sources/external-research.json")
RUNS_RELATIVE = Path("04-findings/external-research")

#: The child only sees these. Everything else is dropped, not inherited.
DEFAULT_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PYTHONIOENCODING", "SYSTEMROOT", "TZ",
)
#: Injected context; the adapter reads the question through these, never through a
#: free-form environment.
CONTEXT_ENV_KEYS = ("ASKOVO_QUESTION", "ASKOVO_STUDY", "ASKOVO_MODE", "ASKOVO_RUN_ID")

DEFAULT_MAX_STDOUT_BYTES = 256 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 900

BOUNDARY = (
    "外部框架返回的是候选材料：URL 只是指向，未尝试访问、无法证明链接或源内容真实；"
    "记录未定级、未与需求判断相连；只有人工把来源映射到研究问题后才可能成为证据。"
)


class BridgeError(ValueError):
    """A boundary rule was violated; always carries a C-01 reason code."""

    def __init__(self, message: str, reason_code: str = "INPUT_REQUIRED",
                 suggestion: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.suggestion = suggestion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _study(study_dir: Path) -> Dict[str, Any]:
    path = Path(study_dir).resolve() / "study.json"
    if not path.is_file():
        raise BridgeError(f"study.json not found under {Path(study_dir).resolve()}",
                          "INPUT_REQUIRED", "run `askovo do` first")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read study.json: {exc}", "INTERNAL_ERROR")
    if not isinstance(payload, dict):
        raise BridgeError("study.json must be an object", "INTERNAL_ERROR")
    return payload


def load_registry(study_dir: Path) -> Dict[str, Any]:
    """Read the auditable command registry; a missing file means "no commands"."""
    path = Path(study_dir).resolve() / REGISTRY_RELATIVE
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "commands": [], "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read {REGISTRY_RELATIVE.as_posix()}: {exc}",
                          "INTERNAL_ERROR",
                          "fix the registry; an unreadable allowlist allows nothing")
    if not isinstance(payload, dict):
        raise BridgeError(f"{REGISTRY_RELATIVE.as_posix()} must be an object", "INTERNAL_ERROR")
    commands = payload.get("commands")
    payload["commands"] = [item for item in commands if isinstance(item, dict)] \
        if isinstance(commands, list) else []
    payload["path"] = str(path)
    return payload


def _entry_by_id(registry: Dict[str, Any], command_id: str) -> Dict[str, Any]:
    for entry in registry.get("commands") or []:
        if str(entry.get("id") or "") == command_id:
            return entry
    raise BridgeError(
        f"command {command_id!r} is not in the signed registry "
        f"({registry.get('path')}); an arbitrary --command is refused",
        "POLICY_DENIED",
        "add a reviewed entry to 01-sources/external-research.json (id, adapter, argv, "
        "sha256, access_basis, reviewed_at, reviewed_by), or use --trusted-local "
        "with --authorize for a one-off local workflow")


def _validate_entry(entry: Dict[str, Any]) -> None:
    missing = [field for field in ("id", "adapter", "argv", "sha256", "access_basis",
                                   "reviewed_at", "reviewed_by")
               if not str(entry.get(field) or "").strip()]
    if missing:
        raise BridgeError(
            f"registry entry {entry.get('id') or '<unnamed>'} is missing "
            + ", ".join(missing), "POLICY_DENIED",
            "a command needs an auditable access basis, reviewer, timestamp and adapter hash")
    if not isinstance(entry.get("argv"), list) or not entry["argv"]:
        raise BridgeError(f"registry entry {entry['id']} needs a non-empty argv array",
                          "POLICY_DENIED")
    adapter = Path(str(entry["adapter"])).resolve()
    if not adapter.is_file():
        raise BridgeError(f"adapter not found for {entry['id']}: {adapter}",
                          "POLICY_DENIED", "the registry must point at a real reviewed file")
    actual = _sha256_file(adapter)
    if actual != str(entry["sha256"]).strip():
        raise BridgeError(
            f"adapter sha256 mismatch for {entry['id']}: registry "
            f"{str(entry['sha256']).strip()} != file {actual}", "POLICY_DENIED",
            "the reviewed adapter changed; re-review it and update the registry hash")
    extra = entry.get("extra_env") or []
    if not isinstance(extra, list) or any(not isinstance(item, str) or not item.strip()
                                          for item in extra):
        raise BridgeError(f"registry entry {entry['id']}.extra_env must be an array of names",
                          "POLICY_DENIED")


def _trusted_local_entry(command: str, argv: List[str]) -> Dict[str, Any]:
    return {
        "id": "trusted-local",
        "label": "explicit trusted-local command",
        "adapter": None,
        "argv": list(argv),
        "sha256": _sha256_text(command),
        "access_basis": "explicit --trusted-local with --authorize (operator-declared)",
        "reviewed_at": _now(),
        "reviewed_by": "operator",
        "extra_env": [],
    }


def _build_env(entry: Dict[str, Any], *, question: str, study_dir: Path,
               mode: str, run_id: str) -> Dict[str, str]:
    """Build the child environment from the allowlist; never inherit-then-delete."""
    keys = list(DEFAULT_ENV_ALLOWLIST) + [str(item) for item in entry.get("extra_env") or []]
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env.update({
        "ASKOVO_QUESTION": str(question or ""),
        "ASKOVO_STUDY": str(Path(study_dir).resolve()),
        "ASKOVO_MODE": str(mode or ""),
        "ASKOVO_RUN_ID": str(run_id),
    })
    return env


def _resolve_output(study_dir: Path, output: str, run_id: str) -> Path:
    root = Path(study_dir).resolve()
    if not str(output or "").strip():
        return root / RUNS_RELATIVE / f"{run_id}.json"
    candidate = Path(str(output))
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved == root or root not in resolved.parents:
        raise BridgeError(
            f"output path escapes the authorized study directory: {resolved}",
            "POLICY_DENIED",
            "pass a path inside the study, e.g. 04-findings/external-research/run.json")
    if resolved.is_dir():
        raise BridgeError(f"output path is a directory: {resolved}", "INPUT_REQUIRED",
                          "pass a file path")
    return resolved


def _effective_cap(requested: Optional[int], default: int) -> int:
    """An operator can lower the cap, never raise it."""
    if requested is None:
        return default
    try:
        value = int(requested)
    except (TypeError, ValueError):
        raise BridgeError(f"byte cap must be an integer, got {requested!r}", "INPUT_REQUIRED")
    return max(1, min(value, default))


def _validate_payload(payload: Any) -> List[Dict[str, Any]]:
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise BridgeError("external research output must contain a non-empty sources list",
                          "INPUT_REQUIRED",
                          "the adapter must print one JSON object with a sources array")
    cleaned: List[Dict[str, Any]] = []
    for index, item in enumerate(sources, start=1):
        if not isinstance(item, dict):
            raise BridgeError(f"sources[{index}] must be an object", "INPUT_REQUIRED")
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise BridgeError(
                f"sources[{index}].url must be an http(s) link, got {url!r}",
                "INPUT_REQUIRED",
                "a non-http link is not a research source; the bridge never resolves it")
        cleaned.append({
            "id": f"X{index:02d}",
            "url": url,
            "title": str(item.get("title") or "").strip(),
            "excerpt": str(item.get("excerpt") or "").strip(),
            "claim": str(item.get("claim") or "").strip(),
            "retrieved_at": str(item.get("retrieved_at") or _now()),
            "evidence_level": None,
            "status": "candidate",
            # A33: the pointer is unverified by construction. Nothing fetches it.
            "url_verification": "not_attempted",
        })
    return cleaned


def run(study_dir: Path, command: str, *, authorize: bool = False,
        trusted_local: bool = False, question: str = "", output: str = "",
        timeout: Optional[int] = None, max_stdout_bytes: Optional[int] = None,
        max_stderr_bytes: Optional[int] = None) -> Dict[str, Any]:
    """Run one authorized adapter and store its output as candidates.

    Raises :class:`BridgeError` for every refusal; nothing is written when the
    run is refused or its streams exceed the cap.
    """
    study_dir = Path(study_dir).resolve()
    study = _study(study_dir)
    if not authorize:
        raise BridgeError(
            "the external research command runs with the current user's privileges; "
            "confirm the source and command, then add --authorize",
            "AUTH_REQUIRED",
            "review the adapter and re-run with --authorize (and --trusted-local only "
            "for a one-off local command)")
    raw_command = str(command or "").strip()
    if not raw_command:
        raise BridgeError("--command cannot be empty", "INPUT_REQUIRED",
                          "pass a registry command id, or --trusted-local with a command")

    registry = load_registry(study_dir)
    known_ids = {str(entry.get("id") or "") for entry in registry.get("commands") or []}
    argv = shlex.split(raw_command)
    if not argv:
        raise BridgeError("--command is empty after parsing", "INPUT_REQUIRED")
    if trusted_local and raw_command not in known_ids:
        entry = _trusted_local_entry(raw_command, argv)
    else:
        entry = _entry_by_id(registry, raw_command)
        _validate_entry(entry)
        argv = [str(item) for item in entry["argv"]]

    timeout_value = int(timeout) if timeout is not None else int(
        entry.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    if timeout_value <= 0:
        raise BridgeError("timeout must be positive", "INPUT_REQUIRED")
    stdout_cap = _effective_cap(max_stdout_bytes, DEFAULT_MAX_STDOUT_BYTES)
    stderr_cap = _effective_cap(max_stderr_bytes, DEFAULT_MAX_STDERR_BYTES)

    run_id = "ext-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
    mode = str((study.get("research_mode") or {}).get("mode") or "")
    env = _build_env(entry, question=question or str(study.get("title") or ""),
                     study_dir=study_dir, mode=mode, run_id=run_id)
    target = _resolve_output(study_dir, output, run_id)

    started_at = _now()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            completed = subprocess.run(
                argv, stdin=subprocess.DEVNULL, stdout=stdout_file, stderr=stderr_file,
                timeout=timeout_value, env=env, cwd=str(study_dir), close_fds=True,
            )
        except subprocess.TimeoutExpired:
            raise BridgeError(
                f"external research command timed out after {timeout_value}s; its external "
                f"effect is unknown and must not be replayed automatically",
                "INDETERMINATE_EXTERNAL_ACTION",
                "inspect the adapter's side effects, then re-run deliberately")
        except OSError as exc:
            raise BridgeError(f"external research command could not start: {exc}",
                              "INTERNAL_ERROR")
        stdout_size = stdout_file.tell()
        stderr_size = stderr_file.tell()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_text = stdout_file.read(min(stdout_size, stdout_cap + 1)).decode("utf-8", "replace")
        stderr_text = stderr_file.read(min(stderr_size, stderr_cap + 1)).decode("utf-8", "replace")
    finished_at = _now()

    if stdout_size > stdout_cap:
        raise BridgeError(
            f"external research stdout exceeded the cap ({stdout_size} > {stdout_cap} bytes); "
            f"the run is refused rather than truncated", "RATE_LIMITED",
            "narrow the adapter's output or lower the question scope; a truncated result is "
            "not a result")
    if stderr_size > stderr_cap:
        raise BridgeError(
            f"external research stderr exceeded the cap ({stderr_size} > {stderr_cap} bytes); "
            f"the run is refused rather than truncated", "RATE_LIMITED",
            "the adapter is too noisy to audit; fix it before re-running")
    if completed.returncode != 0:
        raise BridgeError(
            f"external research command exited {completed.returncode}: {stderr_text[:500]}",
            "INTERNAL_ERROR", "fix the adapter; the bridge stores nothing from a failed run")
    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"external research output is not JSON: {exc}", "INPUT_REQUIRED",
                          "the adapter must print one JSON object with a sources array")
    sources = _validate_payload(payload)
    notes = [str(item) for item in (payload.get("notes") or [])] if isinstance(payload, dict) else []
    if trusted_local:
        notes.insert(0, "trusted-local: this command bypassed the signed registry and is "
                        "recorded for audit; prefer a reviewed registry entry")

    record = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "study_id": study.get("study_id"),
        "question": env["ASKOVO_QUESTION"],
        "mode": mode,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "command_id": entry["id"],
        "command_argv": argv,
        "command_sha256": str(entry["sha256"]),
        "trusted_local": bool(trusted_local and raw_command not in known_ids),
        "registry": registry.get("path"),
        "env_allowlist": sorted(set(list(DEFAULT_ENV_ALLOWLIST)
                                    + [str(item) for item in entry.get("extra_env") or []])),
        "env_keys": sorted(env),
        "limits": {
            "max_stdout_bytes": stdout_cap,
            "max_stderr_bytes": stderr_cap,
            "timeout_seconds": timeout_value,
        },
        "exit_code": completed.returncode,
        "sources": sources,
        "notes": notes,
        "review_required": True,
        "evidence_grade_assigned": False,
        "network_attempted": False,
        "output_path": str(target),
        "boundary": BOUNDARY,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:  # pragma: no cover - run ids are unique by construction
        raise BridgeError(f"external research run {run_id} already exists", "INTERNAL_ERROR",
                          "run ids are unique; re-run to get a new one")
    return record


def summary_lines(record: Dict[str, Any]) -> List[str]:
    """Human-readable summary; the JSON record stays the machine contract."""
    return [
        f"已保存外部研究候选：{record.get('output_path')}",
        f"- run id：{record.get('run_id')}；来源：{len(record.get('sources') or [])} 条；"
        f"状态：candidate；需要人工定级与映射",
        f"- 环境：仅白名单 {len(record.get('env_allowlist') or [])} 个变量；"
        f"stdout 上限 {record.get('limits', {}).get('max_stdout_bytes')} 字节",
        f"- {record.get('boundary')}",
    ]

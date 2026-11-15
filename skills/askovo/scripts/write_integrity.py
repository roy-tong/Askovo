"""A-07 canonical write integrity: strict reads, one journaled transaction, one lock.

The canonical decision join is ``02-data/evidence.jsonl`` ->
``04-findings/demand-judgments.json`` -> ``04-findings/product-reasoning.json``
plus the candidate status and the append-only acceptance trail. Accepting one
issue candidate writes all five. Before A-07 that sequence could silently erase
history (a corrupt judgment file became ``[]``), stop half-way (evidence on disk,
judgment missing) and lose concurrent updates (read-modify-write with no lock).

This module provides the smallest primitive that makes those failures
impossible or visible, using the standard library only:

- :func:`read_json` / :func:`read_jsonl` refuse an unreadable canonical file
  with :class:`IntegrityError` carrying the path and the cause. There is no
  ``except -> []/{}`` fallback anywhere in this module.
- :class:`Transaction` stages every write as a same-directory ``*.tmp`` file,
  records the intent (old/new SHA-256 plus the exact payload) in
  ``04-findings/.write-journal.json`` with an fsync, applies the files with
  ``os.replace``, verifies the new hashes, and only then deletes the journal. An
  interruption leaves the journal behind, so the next entry point can replay it
  or refuse with a precise completed/pending list.
- one cross-process lock per study serializes writers. POSIX uses
  ``fcntl.flock``; a platform without ``fcntl`` falls back to an ``O_EXCL`` lock
  file and refuses loudly on contention instead of pretending to lock.

The journal is an implementation artifact, not a second truth: it is deleted on
success and never read by projections.
"""
from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # POSIX only; the fallback below is explicit, never silent.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX import path
    fcntl = None  # type: ignore[assignment]

JOURNAL_RELATIVE = Path("04-findings/.write-journal.json")
LOCK_RELATIVE = Path("04-findings/.write.lock")
JOURNAL_KIND = "askovo.write-journal"
JOURNAL_SCHEMA = "1.0"
HASH_PREFIX = "sha256:"
DEFAULT_LOCK_TIMEOUT = 60.0
_LOCK_POLL_SECONDS = 0.05


class IntegrityError(RuntimeError):
    """A canonical artifact could not be read or written without losing history."""

    def __init__(self, message: str, *, path: Any = None,
                 code: str = "INTERNAL_ERROR", suggestion: str = "") -> None:
        super().__init__(message)
        self.path = str(path) if path is not None else ""
        self.code = code
        self.suggestion = suggestion


# --------------------------------------------------------------------------- #
# strict canonical reads (never a silent fallback)
# --------------------------------------------------------------------------- #

def sha256_bytes(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise IntegrityError(
            f"cannot read {label} {path}: {type(exc).__name__}: {exc}",
            path=path, code="INTERNAL_ERROR") from exc


def read_json(path: Any, *, missing_ok: bool = False, expected: Any = None,
              label: str = "canonical artifact") -> Any:
    """Read one canonical JSON document or raise :class:`IntegrityError`.

    ``missing_ok`` only covers a genuinely absent file (a first write). A file
    that exists but cannot be decoded, or decodes to the wrong type, is always an
    error: treating it as ``{}``/``[]`` is the A-07 data-loss bug.
    """
    path = Path(path)
    if not path.is_file():
        if missing_ok:
            return None
        raise IntegrityError(f"{label} is missing: {path}", path=path,
                             code="INPUT_REQUIRED")
    raw = _read_bytes(path, label=label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError(
            f"cannot decode {label} {path}: not UTF-8 ({exc.reason} at byte {exc.start})",
            path=path, code="INTERNAL_ERROR") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IntegrityError(
            f"cannot parse {label} {path}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}", path=path, code="INTERNAL_ERROR") from exc
    if expected is not None and not isinstance(value, expected):
        wanted = expected.__name__ if isinstance(expected, type) else "/".join(
            item.__name__ for item in expected)
        raise IntegrityError(
            f"{label} {path} must be a JSON {wanted}, got {type(value).__name__}",
            path=path, code="INTERNAL_ERROR")
    return value


def read_jsonl(path: Any, *, missing_ok: bool = True, require_object: bool = True,
               label: str = "canonical JSONL artifact") -> List[Dict[str, Any]]:
    """Read a canonical JSONL file line by line, refusing the first bad line.

    The old ``except JSONDecodeError: continue`` treatment silently dropped a
    record. Here line ``N`` is named, so the operator can repair the store instead
    of rewriting it from a truncated view.
    """
    path = Path(path)
    if not path.is_file():
        if missing_ok:
            return []
        raise IntegrityError(f"{label} is missing: {path}", path=path,
                             code="INPUT_REQUIRED")
    raw = _read_bytes(path, label=label)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError(
            f"cannot decode {label} {path}: not UTF-8 ({exc.reason} at byte {exc.start})",
            path=path, code="INTERNAL_ERROR") from exc
    items: List[Dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntegrityError(
                f"cannot parse {label} {path} line {number}: {exc.msg} "
                f"(column {exc.colno})", path=path, code="INTERNAL_ERROR") from exc
        if require_object and not isinstance(item, dict):
            raise IntegrityError(
                f"{label} {path} line {number} must be a JSON object, got "
                f"{type(item).__name__}", path=path, code="INTERNAL_ERROR")
        items.append(item)
    return items


# --------------------------------------------------------------------------- #
# atomic replace + fsync
# --------------------------------------------------------------------------- #

def _fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync; unsupported platforms must not fail the write."""
    try:
        handle = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _write_bytes_and_fsync(path: Path, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_replace(source: Any, target: Any) -> None:
    """Same-directory ``os.replace`` + directory fsync.

    Kept as a module-level function so tests can interrupt the exact step without
    patching ``os`` globally.
    """
    source, target = Path(source), Path(target)
    os.replace(str(source), str(target))
    _fsync_dir(target.parent)


def _tmp_path(target: Path) -> Path:
    return target.with_name(target.name + ".tmp")


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


# --------------------------------------------------------------------------- #
# cross-process lock
# --------------------------------------------------------------------------- #

class _StudyLock:
    """One writer per study.

    POSIX: ``fcntl.flock`` on ``04-findings/.write.lock`` (released on process
    death by the kernel). No ``fcntl``: an ``O_EXCL`` lock file, with an explicit
    refusal that says the fallback is in use and names the owner — a stale lock is
    never silently stolen.
    """

    def __init__(self, path: Path, *, timeout: float = DEFAULT_LOCK_TIMEOUT,
                 purpose: str = "") -> None:
        self.path = Path(path)
        self.timeout = max(0.0, float(timeout))
        self.purpose = str(purpose or "")
        self._fd: Optional[int] = None
        self._exclusive_path: Optional[Path] = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is not None:
            self._acquire_flock()
        else:
            self._acquire_exclusive()

    def _acquire_flock(self) -> None:
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[union-attr]
                self._fd = fd
                return
            except OSError as exc:
                retryable = exc.errno in (
                    errno.EACCES, errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN))
                if not retryable:
                    os.close(fd)
                    raise IntegrityError(
                        f"cannot lock canonical writes on {self.path}: {exc}",
                        path=self.path) from exc
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise IntegrityError(
                        f"another canonical write is still running ({self.path}, waited "
                        f"{self.timeout:.1f}s); retry after it finishes. Do not delete the "
                        f"POSIX lock file by hand — flock releases it when that process exits.",
                        path=self.path, code="INTERNAL_ERROR",
                        suggestion="retry the command; if the process is gone, retry once more")
                time.sleep(_LOCK_POLL_SECONDS)

    def _acquire_exclusive(self) -> None:
        exclusive = self.path.with_name(self.path.name + ".excl")
        try:
            fd = os.open(str(exclusive), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            owner = _read_text_quiet(exclusive, limit=300)
            raise IntegrityError(
                f"another canonical write holds the O_EXCL lock file {exclusive} "
                f"(owner record: {owner or 'unreadable'}); this platform has no "
                f"fcntl.flock, so the fallback lock is in use. A stale lock after a crash "
                f"must be checked and removed by hand — refusing to continue.",
                path=exclusive, code="INTERNAL_ERROR",
                suggestion="verify no writer is running, then delete the .excl lock file") from exc
        payload = (f"pid={os.getpid()} acquired_at={_now()} purpose={self.purpose}\n"
                   ).encode("utf-8")
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._exclusive_path = exclusive

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)  # type: ignore[union-attr]
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._exclusive_path is not None:
            _unlink_quiet(self._exclusive_path)
            self._exclusive_path = None


def _read_text_quiet(path: Path, *, limit: int = 4096) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", "replace").strip()
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# journal planning / replay
# --------------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_path(root: Path, target: Path) -> str:
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise IntegrityError(
            f"canonical write target escapes the study: {target}", path=target) from exc


def _resolve_target(root: Path, relative: Any) -> Path:
    path = Path(str(relative))
    if path.is_absolute() or ".." in path.parts:
        raise IntegrityError(
            f"write journal path is not a study-relative path: {relative!r}",
            path=root / JOURNAL_RELATIVE)
    target = (root / path).resolve()
    _relative_path(root, target)
    return target


def _journal_bytes(document: Dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _decode_payload(entry: Dict[str, Any], journal_path: Path) -> bytes:
    value = entry.get("payload_b64")
    if not isinstance(value, str):
        raise IntegrityError(
            f"write journal {journal_path} entry has no base64 payload",
            path=journal_path)
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise IntegrityError(
            f"write journal {journal_path} entry payload is not valid base64: {exc}",
            path=journal_path) from exc


def _validate_journal(journal: Any, journal_path: Path) -> Dict[str, Any]:
    if not isinstance(journal, dict):
        raise IntegrityError(
            f"write journal {journal_path} must be a JSON object",
            path=journal_path)
    if journal.get("kind") != JOURNAL_KIND:
        raise IntegrityError(
            f"write journal {journal_path} has kind {journal.get('kind')!r}, "
            f"expected {JOURNAL_KIND!r}", path=journal_path)
    if str(journal.get("schema_version")) != JOURNAL_SCHEMA:
        raise IntegrityError(
            f"write journal {journal_path} has unsupported schema "
            f"{journal.get('schema_version')!r}", path=journal_path)
    files = journal.get("files")
    if not isinstance(files, list) or not files:
        raise IntegrityError(
            f"write journal {journal_path} has no files to replay", path=journal_path)
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise IntegrityError(
                f"write journal {journal_path} has a non-object file entry",
                path=journal_path)
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            raise IntegrityError(
                f"write journal {journal_path} entry has no path", path=journal_path)
        if relative in seen:
            raise IntegrityError(
                f"write journal {journal_path} repeats {relative!r}", path=journal_path)
        seen.add(relative)
        if entry.get("operation") not in ("append", "replace"):
            raise IntegrityError(
                f"write journal {journal_path} entry {relative!r} has unknown operation "
                f"{entry.get('operation')!r}", path=journal_path)
        if not isinstance(entry.get("old_exists"), bool):
            raise IntegrityError(
                f"write journal {journal_path} entry {relative!r} has no old_exists flag",
                path=journal_path)
        old_sha = entry.get("old_sha256")
        if old_sha is not None and not (isinstance(old_sha, str)
                                        and old_sha.startswith(HASH_PREFIX)):
            raise IntegrityError(
                f"write journal {journal_path} entry {relative!r} has an invalid old hash",
                path=journal_path)
        new_sha = entry.get("new_sha256")
        if not (isinstance(new_sha, str) and new_sha.startswith(HASH_PREFIX)):
            raise IntegrityError(
                f"write journal {journal_path} entry {relative!r} has no new hash",
                path=journal_path)
        _decode_payload(entry, journal_path)
    return journal


def _load_journal(root: Path) -> Optional[Dict[str, Any]]:
    path = root / JOURNAL_RELATIVE
    if not path.is_file():
        return None
    try:
        document = read_json(path, label="write journal")
    except IntegrityError as exc:
        raise IntegrityError(
            f"write journal is unreadable: {exc}", path=path) from exc
    return _validate_journal(document, path)


def _plan_entry(root: Path, raw: Dict[str, Any], journal_path: Path) -> Dict[str, Any]:
    target = _resolve_target(root, raw["path"])
    try:
        current = target.read_bytes() if target.is_file() else None
    except OSError as exc:
        raise IntegrityError(
            f"cannot read {target} while inspecting the write journal: {exc}",
            path=target) from exc
    current_sha = sha256_bytes(current) if current is not None else None
    plan = {
        "path": raw["path"],
        "operation": raw["operation"],
        "old_sha256": raw.get("old_sha256"),
        "old_exists": raw["old_exists"],
        "new_sha256": raw["new_sha256"],
        "payload": _decode_payload(raw, journal_path),
        "target": target,
        "current_sha256": current_sha,
        "state": "pending",
        "detail": "",
    }
    if current_sha == raw["new_sha256"]:
        plan["state"] = "applied"
        return plan
    if raw["old_exists"]:
        if current is not None and current_sha == raw.get("old_sha256"):
            return plan
        plan["state"] = "conflict"
        plan["detail"] = (
            f"current content is {current_sha or 'missing'}, expected the recorded old "
            f"hash {raw.get('old_sha256')} or new hash {raw['new_sha256']}")
        return plan
    if current is None or current == b"":
        return plan
    plan["state"] = "conflict"
    plan["detail"] = (
        f"the journal recorded an absent file on {_now()} but {target} now exists with "
        f"content {current_sha}")
    return plan


def _plan(root: Path, journal: Dict[str, Any]) -> List[Dict[str, Any]]:
    journal_path = root / JOURNAL_RELATIVE
    return [_plan_entry(root, entry, journal_path) for entry in journal["files"]]


def _entry_bytes(plan: Dict[str, Any]) -> bytes:
    if plan["operation"] == "append":
        try:
            current = plan["target"].read_bytes() if plan["target"].is_file() else b""
        except OSError as exc:
            raise IntegrityError(
                f"cannot read {plan['target']} before appending: {exc}",
                path=plan["target"]) from exc
        return current + plan["payload"]
    return plan["payload"]


def _apply_plan_entry(plan: Dict[str, Any]) -> None:
    data = _entry_bytes(plan)
    target = plan["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(target)
    _write_bytes_and_fsync(tmp, data)
    atomic_replace(tmp, target)


def _report_meta(journal: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not journal:
        return {"candidate_id": None, "operator": None, "created_at": None,
                "purpose": None, "transaction_id": None}
    meta = journal.get("meta") if isinstance(journal.get("meta"), dict) else {}
    return {
        "candidate_id": meta.get("candidate_id"),
        "operator": meta.get("operator"),
        "created_at": journal.get("created_at"),
        "purpose": journal.get("purpose"),
        "transaction_id": journal.get("transaction_id"),
    }


def _meta_suffix(meta: Dict[str, Any]) -> str:
    parts = []
    if meta.get("candidate_id"):
        parts.append(f"候选 {meta['candidate_id']}")
    if meta.get("operator"):
        parts.append(f"操作人 {meta['operator']}")
    if meta.get("created_at"):
        parts.append(f"开始于 {meta['created_at']}")
    return ("（" + "，".join(parts) + "）") if parts else ""


def _reason_incomplete(meta: Dict[str, Any], completed: List[str],
                       pending: List[str]) -> str:
    return (f"上次接受未完成{_meta_suffix(meta)}：已完成 {len(completed)} 项 "
            f"{completed}，未完成 {len(pending)} 项 {pending}。"
            f"运行 `askovo issues recover <study> --apply` 完成写入；"
            f"任何写入入口在恢复前都会拒绝继续。")


def _reason_conflict(meta: Dict[str, Any], completed: List[str], pending: List[str],
                     conflicts: List[Dict[str, str]]) -> str:
    return (f"上次接受未完成且无法自动重放{_meta_suffix(meta)}："
            f"已完成 {len(completed)} 项 {completed}，未完成 {len(pending)} 项 {pending}；"
            f"冲突文件 {[item['path'] for item in conflicts]} 的当前内容既不是写入前也不是"
            f"写入后（可能被人工或其他进程修改），replay 会覆盖这些改动。"
            f"请人工核对这些文件；未完成的事项不会被静默跳过。")


def _report(status: str, *, journal_path: Path, meta: Dict[str, Any],
            completed: List[str], pending: List[str],
            conflicts: Optional[List[Dict[str, str]]] = None,
            detail: str = "", errors: Optional[List[str]] = None) -> Dict[str, Any]:
    conflicts = conflicts or []
    if status == "none":
        reason = ""
    elif status == "completed":
        reason = f"上次接受未完成{_meta_suffix(meta)}，已按 journal 重放并校验完成。"
    elif status == "incomplete":
        reason = _reason_incomplete(meta, completed, pending)
    elif status == "clean":
        reason = (f"上次接受未完成{_meta_suffix(meta)}，但 journal 记录的每个文件都已是"
                  f"写入后的内容；运行 --apply 清理 journal 即可。")
    elif status == "conflict":
        reason = _reason_conflict(meta, completed, pending, conflicts)
    else:  # corrupt
        reason = (f"上次接受未完成：write journal {journal_path} 无法读取或结构不合法"
                  f"（{detail}）。无法判断哪些写入已生效；请人工核对 evidence / judgments / "
                  f"product-reasoning / candidate / trail 后删除 journal。")
    return {
        "status": status,
        "journal": str(journal_path),
        "candidate_id": meta.get("candidate_id"),
        "operator": meta.get("operator"),
        "created_at": meta.get("created_at"),
        "transaction_id": meta.get("transaction_id"),
        "purpose": meta.get("purpose"),
        "reason": reason,
        "completed": completed,
        "pending": pending,
        "conflicts": conflicts,
        "errors": errors or [],
        "next_required_action": _next_action(status, journal_path),
        "boundary": ("journal 只是写入意图与重放材料，不是第二份判断；恢复只按记录的新 hash "
                     "落盘，不重新决策。"),
    }


def _next_action(status: str, journal_path: Path) -> str:
    if status == "none":
        return "无需恢复"
    if status == "completed":
        return "继续原定工作；重复 accept 会返回 already_accepted"
    if status == "clean":
        return "运行 `askovo issues recover <study> --apply` 清理 journal"
    if status == "incomplete":
        return "运行 `askovo issues recover <study> --apply` 完成上次接受"
    if status == "conflict":
        return "人工核对冲突文件后再决定重放或手工修复；不要直接删除 journal"
    return ("先核对 journal 记录的五个文件，再手工删除 "
            f"{journal_path.name}；在此之前所有写入入口都会拒绝")


def recover_locked(study_dir: Any, *, apply: bool = False) -> Dict[str, Any]:
    """Inspect (and optionally replay) the journal. Caller must hold the lock."""
    root = Path(study_dir).resolve()
    journal_path = root / JOURNAL_RELATIVE
    if not journal_path.is_file():
        empty = _report("none", journal_path=journal_path, meta={}, completed=[],
                        pending=[])
        empty["exit_code"] = 0
        return empty
    try:
        journal = _load_journal(root)
        assert journal is not None
        plan = _plan(root, journal)
    except IntegrityError as exc:
        report = _report("corrupt", journal_path=journal_path,
                         meta=_report_meta(None), completed=[], pending=[],
                         detail=str(exc))
        report["exit_code"] = 2
        return report
    meta = _report_meta(journal)
    completed = [item["path"] for item in plan if item["state"] == "applied"]
    conflicts = [{"path": item["path"], "detail": item["detail"]}
                 for item in plan if item["state"] == "conflict"]
    pending = [item["path"] for item in plan if item["state"] == "pending"]
    if conflicts:
        report = _report("conflict", journal_path=journal_path, meta=meta,
                         completed=completed, pending=pending, conflicts=conflicts)
        report["exit_code"] = 2
        return report
    if not apply:
        status = "clean" if not pending else "incomplete"
        report = _report(status, journal_path=journal_path, meta=meta,
                         completed=completed, pending=pending)
        report["exit_code"] = 0 if status == "clean" else 1
        return report
    errors: List[str] = []
    for item in plan:
        if item["state"] != "pending":
            continue
        try:
            _apply_plan_entry(item)
        except OSError as exc:
            errors.append(f"{item['path']}: {type(exc).__name__}: {exc}")
    # Re-plan after the replay: verify the new hashes and detect a concurrent edit.
    try:
        plan = _plan(root, journal)
    except IntegrityError as exc:
        report = _report("corrupt", journal_path=journal_path, meta=meta,
                         completed=[], pending=[], detail=str(exc), errors=errors)
        report["exit_code"] = 2
        return report
    completed = [item["path"] for item in plan if item["state"] == "applied"]
    pending = [item["path"] for item in plan if item["state"] == "pending"]
    conflicts = [{"path": item["path"], "detail": item["detail"]}
                 for item in plan if item["state"] == "conflict"]
    if conflicts:
        report = _report("conflict", journal_path=journal_path, meta=meta,
                         completed=completed, pending=pending, conflicts=conflicts,
                         errors=errors)
        report["exit_code"] = 2
        return report
    if pending:
        report = _report("incomplete", journal_path=journal_path, meta=meta,
                         completed=completed, pending=pending, errors=errors)
        report["exit_code"] = 2
        return report
    try:
        journal_path.unlink()
    except OSError as exc:
        report = _report("incomplete", journal_path=journal_path, meta=meta,
                         completed=completed, pending=[], errors=errors + [
                             f"journal cleanup failed: {type(exc).__name__}: {exc}"])
        report["exit_code"] = 2
        return report
    _fsync_dir(journal_path.parent)
    report = _report("completed", journal_path=journal_path, meta=meta,
                     completed=completed, pending=[], errors=errors)
    report["exit_code"] = 0 if not errors else 2
    return report


def recover(study_dir: Any, *, apply: bool = False) -> Dict[str, Any]:
    """Explicit recovery entry: dry-run by default, ``apply=True`` replays."""
    root = Path(study_dir).resolve()
    if not root.is_dir():
        raise IntegrityError(f"study directory does not exist: {root}", path=root,
                             code="INPUT_REQUIRED")
    lock = _StudyLock(root / LOCK_RELATIVE, purpose="issues recover")
    lock.acquire()
    try:
        return recover_locked(root, apply=apply)
    finally:
        lock.release()


# --------------------------------------------------------------------------- #
# transaction
# --------------------------------------------------------------------------- #

class Transaction:
    """Stage N canonical writes, journal the intent, apply them as one unit.

    ``with Transaction(study) as txn:`` acquires the lock and finishes any journal
    left by an earlier interruption (raising a precise :class:`IntegrityError` when
    that journal conflicts). ``txn.add(...)`` only stages; ``txn.commit()`` writes
    every ``*.tmp``, installs the journal, applies the files, verifies the new
    hashes and deletes the journal. An ``OSError`` during the apply rolls already
    replaced files back to their old bytes, so the caller never observes a
    half-written study.
    """

    def __init__(self, study_dir: Any, *, purpose: str = "", meta: Optional[Dict[str, Any]] = None,
                 timeout: float = DEFAULT_LOCK_TIMEOUT, auto_recover: bool = True) -> None:
        self.study_dir = Path(study_dir).resolve()
        self.purpose = str(purpose or "")
        self.meta = dict(meta or {})
        self.journal_path = self.study_dir / JOURNAL_RELATIVE
        self._lock = _StudyLock(self.study_dir / LOCK_RELATIVE, timeout=timeout,
                                purpose=self.purpose)
        self._auto_recover = bool(auto_recover)
        self._entries: List[Dict[str, Any]] = []
        self.recovery: Optional[Dict[str, Any]] = None
        self._entered = False

    def __enter__(self) -> "Transaction":
        self._lock.acquire()
        self._entered = True
        if self._auto_recover:
            self.recover()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._lock.release()
        self._entered = False
        return False

    # -- recovery ---------------------------------------------------------- #

    def recover(self) -> Optional[Dict[str, Any]]:
        """Finish a journal left by an interrupted accept, or refuse precisely."""
        report = recover_locked(self.study_dir, apply=True)
        status = str(report.get("status"))
        if status in ("conflict", "corrupt", "incomplete"):
            raise IntegrityError(str(report.get("reason") or "previous acceptance incomplete"),
                                 path=self.journal_path,
                                 suggestion=str(report.get("next_required_action") or ""))
        if status in ("completed", "clean"):
            self.recovery = report
            return report
        return None

    # -- staging ----------------------------------------------------------- #

    def add(self, path: Any, data: Any, *, mode: str = "replace") -> None:
        if mode not in ("append", "replace"):
            raise IntegrityError(f"unknown write mode {mode!r}", path=path)
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        raw_target = Path(path)
        target = (raw_target if raw_target.is_absolute()
                  else self.study_dir / raw_target).resolve()
        relative = _relative_path(self.study_dir, target)
        if any(item["path"] == relative for item in self._entries):
            raise IntegrityError(
                f"transaction already writes {relative}; one write per file per transaction",
                path=target)
        if mode == "append" and not payload:
            return
        try:
            old = target.read_bytes() if target.is_file() else None
        except OSError as exc:
            raise IntegrityError(
                f"cannot read {target} before writing: {type(exc).__name__}: {exc}",
                path=target) from exc
        new = (old or b"") + payload if mode == "append" else payload
        self._entries.append({
            "path": relative,
            "operation": mode,
            "old_exists": old is not None,
            "old_sha256": sha256_bytes(old) if old is not None else None,
            "new_sha256": sha256_bytes(new),
            "payload": payload,
            "target": target,
            "old": old,
            "new": new,
        })

    # -- commit ------------------------------------------------------------ #

    def commit(self) -> None:
        if not self._entries:
            return
        staged: List[Dict[str, Any]] = []
        try:
            for item in self._entries:
                target = item["target"]
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = _tmp_path(target)
                _write_bytes_and_fsync(tmp, item["new"])
                staged.append({"item": item, "tmp": tmp})
        except OSError as exc:
            self._cleanup_staged(staged)
            raise IntegrityError(
                f"could not stage canonical writes ({type(exc).__name__}: {exc}); "
                f"no artifact was changed", path=exc.filename or self.study_dir) from exc
        journal = {
            "schema_version": JOURNAL_SCHEMA,
            "kind": JOURNAL_KIND,
            "transaction_id": uuid.uuid4().hex,
            "created_at": _now(),
            "purpose": self.purpose,
            "meta": self.meta,
            "files": [{key: item[key] for key in
                       ("path", "operation", "old_exists", "old_sha256",
                        "new_sha256")} | {"payload_b64": base64.b64encode(
                            item["payload"]).decode("ascii")}
                      for item in self._entries],
        }
        journal_tmp = _tmp_path(self.journal_path)
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_and_fsync(journal_tmp, _journal_bytes(journal))
            atomic_replace(journal_tmp, self.journal_path)
        except OSError as exc:
            _unlink_quiet(journal_tmp)
            self._cleanup_staged(staged)
            raise IntegrityError(
                f"could not record the write journal ({type(exc).__name__}: {exc}); "
                f"no artifact was changed", path=self.journal_path) from exc
        applied: List[Dict[str, Any]] = []
        try:
            for stage in staged:
                atomic_replace(stage["tmp"], stage["item"]["target"])
                applied.append(stage["item"])
        except Exception as exc:  # noqa: BLE001 - roll back on any interruption we can catch
            rolled_back, failures = self._rollback(applied)
            self._cleanup_staged(staged)
            if rolled_back:
                raise IntegrityError(
                    f"canonical write failed ({type(exc).__name__}: {exc}); every artifact "
                    f"was rolled back to its previous bytes", path=self.journal_path) from exc
            raise IntegrityError(
                f"canonical write failed ({type(exc).__name__}: {exc}) and rollback is "
                f"incomplete ({failures}); the journal was kept — run "
                f"`askovo issues recover <study> --apply`", path=self.journal_path) from exc
        for item in self._entries:
            try:
                current = item["target"].read_bytes()
            except OSError as exc:
                raise IntegrityError(
                    f"cannot verify {item['target']} after writing: {exc}; the journal was "
                    f"kept for recovery", path=item["target"]) from exc
            if sha256_bytes(current) != item["new_sha256"]:
                raise IntegrityError(
                    f"post-write verification failed for {item['target']}; the journal was "
                    f"kept for recovery", path=item["target"])
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise IntegrityError(
                f"canonical writes are complete but the journal could not be removed: {exc}; "
                f"run `askovo issues recover <study> --apply` to clean it up",
                path=self.journal_path) from exc
        _fsync_dir(self.journal_path.parent)
        self._entries = []

    def _rollback(self, applied: List[Dict[str, Any]]) -> Any:
        failures: List[str] = []
        for item in reversed(applied):
            try:
                if item["old"] is None:
                    if item["target"].is_file():
                        item["target"].unlink()
                    _fsync_dir(item["target"].parent)
                else:
                    target = item["target"]
                    tmp = _tmp_path(target)
                    _write_bytes_and_fsync(tmp, item["old"])
                    atomic_replace(tmp, target)
            except OSError as exc:
                failures.append(f"{item['path']}: {type(exc).__name__}: {exc}")
        if failures:
            return False, failures
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            return False, [f"journal cleanup: {type(exc).__name__}: {exc}"]
        _fsync_dir(self.journal_path.parent)
        return True, []

    def _cleanup_staged(self, staged: List[Dict[str, Any]]) -> None:
        for stage in staged:
            _unlink_quiet(stage["tmp"])
        _unlink_quiet(_tmp_path(self.journal_path))

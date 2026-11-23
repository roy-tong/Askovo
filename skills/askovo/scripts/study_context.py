from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_CURRENT_CONTEXT: ContextVar[Any] = ContextVar("askovo_study_context", default=None)


class BoundedJsonlCache:
    def __init__(self, max_entries: int = 32):
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._values: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            value = self._values[key]
            self._values.move_to_end(key)
            return value

    def __setitem__(self, key: Any, value: Any) -> None:
        self.put(key, value)

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


class StudyRepository:
    def __init__(self, study_dir: Any):
        self.study_dir = Path(study_dir).resolve()

    def resolve(self, path: Any) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.study_dir / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.study_dir)
        except ValueError as exc:
            raise ValueError("path escapes the study snapshot: %s" % path) from exc
        return resolved

    def owns(self, path: Any) -> bool:
        try:
            self.resolve(path)
            return True
        except (OSError, ValueError):
            return False

    def read_bytes(self, path: Any) -> bytes:
        return self.resolve(path).read_bytes()

    def transaction(self, purpose: str = ""):
        import write_integrity
        return write_integrity.Transaction(self.study_dir, purpose=purpose)

    def atomic_write_text(self, path: Any, text: str) -> Path:
        import write_integrity
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", prefix=target.name + ".tmp-", dir=str(target.parent), delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            write_integrity.atomic_replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return target


def _parse_jsonl_bytes(payload: bytes) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line_number, raw_line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("line %d must be valid JSON: %s" % (line_number, exc.msg)) from exc
        if not isinstance(value, dict):
            raise ValueError("line %d must be a JSON object" % line_number)
        value["_line_number"] = line_number
        records.append(value)
    return records


class StudyContext:
    def __init__(self, repository: StudyRepository, *, max_cache_entries: int = 32):
        self.repository = repository
        self._bytes = BoundedJsonlCache(max_cache_entries)
        self._json = BoundedJsonlCache(max_cache_entries)
        self._jsonl = BoundedJsonlCache(max_cache_entries)

    def owns(self, path: Any) -> bool:
        return self.repository.owns(path)

    def read_bytes(self, path: Any) -> bytes:
        resolved = self.repository.resolve(path)
        key = str(resolved)
        cached = self._bytes.get(key)
        if cached is None:
            cached = self.repository.read_bytes(resolved)
            self._bytes.put(key, cached)
        return cached

    def read_json(self, path: Any) -> Any:
        resolved = self.repository.resolve(path)
        key = str(resolved)
        cached = self._json.get(key)
        if cached is None:
            cached = json.loads(self.read_bytes(resolved).decode("utf-8"))
            self._json.put(key, cached)
        return copy.deepcopy(cached)

    def read_jsonl(self, path: Any, parser: Optional[Callable[[bytes], List[Dict[str, Any]]]] = None,
                   strict: bool = True) -> List[Dict[str, Any]]:
        resolved = self.repository.resolve(path)
        selected = parser or _parse_jsonl_bytes
        if not strict and parser is None:
            def selected(payload: bytes) -> List[Dict[str, Any]]:
                try:
                    return _parse_jsonl_bytes(payload)
                except (UnicodeDecodeError, ValueError):
                    return []
        raw = self.read_bytes(resolved)
        digest = hashlib.blake2b(raw, digest_size=16).hexdigest()
        parser_key = (getattr(selected, "__module__", ""), getattr(selected, "__qualname__", repr(selected)), strict)
        key = (str(resolved), digest, parser_key)
        cached = self._jsonl.get(key)
        if cached is None:
            cached = selected(raw)
            self._jsonl.put(key, cached)
        return [dict(record) for record in cached]

    @contextmanager
    def activate(self):
        token = _CURRENT_CONTEXT.set(self)
        try:
            yield self
        finally:
            _CURRENT_CONTEXT.reset(token)


def current_study_context() -> Optional[StudyContext]:
    return _CURRENT_CONTEXT.get()

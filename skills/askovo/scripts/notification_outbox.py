"""Transactional research-watch events and receipt-bound delivery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import write_integrity
from study_context import StudyRepository

OUTBOX_RELATIVE = Path("04-findings/research-watch-outbox.jsonl")


def _path(study_dir):
    return Path(study_dir).resolve() / OUTBOX_RELATIVE


def _rows(study_dir):
    return write_integrity.read_jsonl(_path(study_dir), missing_ok=True,
                                     label="research watch outbox") or []


def events_for_txn(study_dir, runs):
    existing = {str(row.get("event_id") or "") for row in _rows(study_dir)
                if row.get("kind") == "event"}
    payload = []
    for run in runs:
        event_id = str(run.get("run_id") or "")
        if not event_id or event_id in existing:
            continue
        payload.append(dict(run, kind="event", event_id=event_id,
                            next_action="处理失败复审" if run.get("status") == "failed" else "查看复审结果"))
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in payload)


def pending(study_dir):
    delivered = {str(row.get("event_id") or "") for row in _rows(study_dir)
                 if row.get("kind") == "delivery" and row.get("status") == "delivered"}
    return [row for row in _rows(study_dir)
            if row.get("kind") == "event" and row.get("event_id") not in delivered]


def deliver_pending(study_dir, sender):
    delivered = 0
    failed = 0
    with StudyRepository(study_dir).transaction("research-watch-delivery") as txn:
        for event in pending(study_dir):
            row = {"kind": "delivery", "event_id": event["event_id"],
                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            try:
                receipt = sender(dict(event))
                if not str(receipt or "").strip():
                    raise ValueError("delivery receipt is required")
            except Exception as exc:
                row.update(status="failed", error="%s: %s" % (type(exc).__name__, str(exc)[:200]))
                failed += 1
            else:
                row.update(status="delivered", receipt=str(receipt or ""))
                delivered += 1
            txn.add(OUTBOX_RELATIVE, json.dumps(row, ensure_ascii=False) + "\n", mode="append")
        txn.commit()
    return {"delivered": delivered, "failed": failed,
            "pending": len(pending(study_dir)), "delivery_adapter": "injected"}

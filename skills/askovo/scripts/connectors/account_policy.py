#!/usr/bin/env python3
"""Persistent per-account platform tiers and collection quotas.

The policy stores identities and limits, never credentials. Callers resolve the
same profile by platform plus account_id/handle in every process. A publishing
quota is not a collection quota: collectors request the ``collect`` action only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent


class AccountPolicyError(ValueError):
    """The persistent account policy is malformed."""


def default_path() -> Path:
    configured = str(os.environ.get("ASKOVO_ACCOUNT_POLICY") or "").strip()
    if configured:
        return Path(configured).expanduser()
    checkout = HERE.parents[3] if len(HERE.parents) > 3 else None
    if checkout is not None and (checkout / "skills" / "askovo").is_dir():
        return checkout / ".askovo" / "account-quotas.json"
    return Path.home() / ".askovo" / "account-quotas.json"


def _path(path: Optional[Path] = None) -> Path:
    return Path(path).expanduser() if path is not None else default_path()


def quota_db_path(path: Optional[Path] = None) -> Path:
    """All studies using one policy share the same account quota ledger."""
    return _path(path).resolve().parent / "quota.db"


def load_profiles(path: Optional[Path] = None) -> list[Dict[str, Any]]:
    source = _path(path)
    if not source.is_file():
        return []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccountPolicyError(f"cannot read account policy {source}: {exc}") from exc
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list) or any(not isinstance(row, dict) for row in accounts):
        raise AccountPolicyError(f"account policy {source}: accounts must be an array of objects")
    return accounts


def _account_key(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def profile_for(
    platform: str,
    account: str = "",
    *,
    path: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    name = str(platform or "").strip().lower()
    candidates = [row for row in load_profiles(path)
                  if str(row.get("platform") or "").strip().lower() == name]
    key = _account_key(account)
    if key:
        candidates = [row for row in candidates if key in {
            _account_key(row.get("account_id")), _account_key(row.get("handle")),
        }]
    if len(candidates) != 1:
        return None
    return dict(candidates[0])


def view_for(
    platform: str,
    action: str = "collect",
    account: str = "",
    *,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    profile = profile_for(platform, account, path=path)
    if profile is None:
        return {
            "platform": str(platform), "account_id": "", "handle": "",
            "account_tier": "unknown", "subscription_tier": "",
            "source": "unconfigured", "daily_cap": None,
        }
    cap = (profile.get("daily_caps") or {}).get(action)
    if cap is not None and (type(cap) is not int or cap < 0):
        raise AccountPolicyError(
            f"{platform}/{action}: daily cap must be a non-negative integer")
    return {
        "platform": str(platform),
        "account_id": str(profile.get("account_id") or ""),
        "handle": str(profile.get("handle") or ""),
        "account_tier": str(profile.get("account_tier") or
                            profile.get("subscription_tier") or "unknown"),
        "subscription_tier": str(profile.get("subscription_tier") or ""),
        "source": str(profile.get("source") or "unspecified"),
        "daily_cap": cap,
    }

#!/usr/bin/env python3
"""Initialize and audit an askovo research study.

This CLI intentionally uses only the Python standard library. It validates
research structure and claim eligibility; it does not collect data, call a
model, or prove population-level demand.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import sure_engine  # noqa: E402


def _read_version() -> str:
    """Single source of truth: <repo>/VERSION, shared by CLI, MCP, and packaging."""
    for candidate in (
        Path(__file__).resolve().parents[3] / "VERSION",
        Path(__file__).resolve().parents[1] / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "dev"


ASKOVO_VERSION = _read_version()

LEVELS = {"E0", "E1", "E2", "E3", "E4+", "E4-", "E5"}
CORPUS_ROLES = {
    "direct_solution",
    "open_scene",
    "substitute_rejector",
    "post_purchase_support",
    "control",
}
STAGES = ("design", "evidence", "decision", "full")
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "assets" / "open-source-connectors.json"
PLATFORM_MAP_PATH = Path(__file__).resolve().parents[1] / "assets" / "platform-map.json"

PLAN_TYPE_WEIGHTS = {
    "forum": 0.35,
    "social": 0.30,
    "video": 0.20,
    "ecommerce": 0.30,
    "crowdfunding": 0.10,
}
PLAN_ROLE_WEIGHTS = {
    "direct_solution": 0.30,
    "open_scene": 0.30,
    "substitute_rejector": 0.15,
    "post_purchase_support": 0.15,
    "control": 0.10,
}
PLAN_MAX_PLATFORM_SHARE = 0.65
PLAN_MODES = ("standard", "unnamed_experience")
GROUNDING_PATHS = {
    "edge_language",
    "substitute_behavior",
    "psychophysical",
    "cross_domain",
    "discipline",
}
LEXICON_TERM_TYPES = {"proto_word", "behavior", "dimension", "analogy", "discipline_term"}
LEXICON_MIN_TERMS = 5
LEXICON_MIN_PATHS = 2
PLAN_PLATFORM_BIAS = {
    "reddit": "Subreddit self-selection and search ranking bias",
    "x": "Public-post reach bias; reposts are distribution, not demand",
    "youtube": "Creator-selection bias; comments skew toward engaged viewers",
    "amazon": "Historical reviews through 2023-09 only; purchase-verified skew",
    "jd": "No reviewed connector; route unavailable",
    "taobao": "No reviewed connector; route unavailable",
    "kickstarter": "No reviewed connector; route unavailable",
    "zhihu": "No reviewed connector; route unavailable",
    "weibo": "No reviewed connector; route unavailable",
    "bilibili": "No reviewed connector; route unavailable",
    "modian": "No reviewed connector; route unavailable",
}

CONNECTOR_CONFIG_REQUIRED = {
    "connector_id",
    "connector_revision",
    "connector_license",
    "policy_status",
    "data_rights_reviewed_at",
    "data_rights_basis",
}
CONNECTOR_PROVENANCE_REQUIRED = {
    "collection_run_id",
    "connector_id",
    "connector_revision",
}

STUDY_REQUIRED = {
    "study_id",
    "title",
    "decision",
    "scope",
    "hypotheses",
    "quality_gates",
    "stopping_rules",
    "restart_rules",
}
DECISION_REQUIRED = {"question", "owner", "deadline", "options", "minimum_evidence"}
SCOPE_REQUIRED = {
    "target_users",
    "markets",
    "languages",
    "source_time_window",
    "unit_of_observation",
    "allowed_sources",
    "prohibited_inferences",
}
GATE_REQUIRED = {
    "min_evidence_records",
    "required_corpus_roles",
    "max_source_family_share",
    "max_normalized_duplicate_rate",
    "require_counter_evidence_for_validated",
}
EVIDENCE_REQUIRED = {
    "record_id",
    "user_role",
    "scene_trigger",
    "task_outcome",
    "current_substitute",
    "friction_cost",
    "consequence",
    "evidence_level",
    "evidence_basis",
    "corpus_role",
    "source_family",
    "source_ref",
    "normalized_text_hash",
}
JUDGMENT_REQUIRED = {
    "id",
    "title",
    "user_role",
    "scene",
    "task",
    "current_substitute",
    "friction",
    "consequence",
    "solution",
    "acceptance_conditions",
    "problem_evidence_ids",
    "solution_evidence_ids",
    "commercial_evidence_ids",
    "counter_evidence_ids",
    "status",
    "confidence",
    "gaps",
    "next_test",
}
REDDIT_REQUIRED = {
    "source_platform",
    "source_channel",
    "source_url",
    "thread_id",
    "reddit_item_id",
    "source_content_type",
    "source_query",
    "source_sort",
    "source_time_filter",
    "created_at",
    "collected_at",
    "content_status",
} | CONNECTOR_PROVENANCE_REQUIRED
REDDIT_CONFIG_REQUIRED = {
    "enabled",
    "researcher_role",
    "collection_mode",
    "access_basis",
    "terms_reviewed_at",
    "retention_rule",
    "min_unique_subreddits",
    "min_unique_threads",
    "max_subreddit_share",
    "max_thread_share",
    "require_original_source",
    "treat_ai_summaries_as_discovery_only",
} | CONNECTOR_CONFIG_REQUIRED
REDDIT_COLLECTION_MODES = {"historical_search", "live_monitoring", "mixed"}
REDDIT_ACCESS_BASES = {"official_api"}
X_REQUIRED = {
    "source_platform",
    "source_url",
    "x_post_id",
    "conversation_id",
    "x_post_type",
    "source_query",
    "source_search_mode",
    "created_at",
    "collected_at",
    "last_verified_at",
    "content_status",
} | CONNECTOR_PROVENANCE_REQUIRED
X_CONFIG_REQUIRED = {
    "enabled",
    "researcher_role",
    "collection_mode",
    "access_basis",
    "terms_reviewed_at",
    "retention_rule",
    "min_unique_conversations",
    "min_unique_days",
    "max_conversation_share",
    "max_repost_share",
    "max_single_day_share",
    "require_original_source",
    "treat_ai_summaries_as_discovery_only",
} | CONNECTOR_CONFIG_REQUIRED
X_ACCESS_BASES = {"official_api"}
X_POST_TYPES = {"original", "reply", "quote", "repost"}
YOUTUBE_REQUIRED = {
    "source_platform",
    "source_channel",
    "source_url",
    "youtube_video_id",
    "youtube_item_id",
    "youtube_content_type",
    "source_query",
    "source_order",
    "created_at",
    "collected_at",
    "last_verified_at",
    "refresh_due_at",
    "content_status",
} | CONNECTOR_PROVENANCE_REQUIRED
YOUTUBE_CONFIG_REQUIRED = {
    "enabled",
    "researcher_role",
    "collection_mode",
    "access_basis",
    "terms_reviewed_at",
    "retention_rule",
    "min_unique_channels",
    "min_unique_videos",
    "max_channel_share",
    "max_video_share",
    "require_original_source",
    "treat_ai_summaries_as_discovery_only",
} | CONNECTOR_CONFIG_REQUIRED
YOUTUBE_ACCESS_BASES = {"official_api"}
YOUTUBE_CONTENT_TYPES = {"video", "transcript_segment", "top_level_comment", "reply"}

MARKETPLACE_ADAPTERS = ("amazon", "jd", "taobao")
MARKETPLACE_REQUIRED = {
    "source_platform",
    "source_url",
    "commerce_product_id",
    "commerce_variant_id",
    "commerce_store_id",
    "commerce_brand",
    "commerce_record_id",
    "commerce_content_type",
    "commerce_transaction_status",
    "source_completeness",
    "source_query",
    "created_at",
    "collected_at",
    "content_status",
} | CONNECTOR_PROVENANCE_REQUIRED
MARKETPLACE_CONFIG_REQUIRED = {
    "enabled",
    "researcher_role",
    "collection_mode",
    "access_basis",
    "terms_reviewed_at",
    "retention_rule",
    "min_unique_products",
    "min_unique_stores",
    "min_unique_brands",
    "max_product_share",
    "max_store_share",
    "max_brand_share",
    "max_single_month_share",
    "require_variant_id",
    "require_original_source",
    "treat_ai_summaries_as_discovery_only",
} | CONNECTOR_CONFIG_REQUIRED
MARKETPLACE_ACCESS_BASES = {
    "amazon": {"historical_dataset"},
    "jd": set(),
    "taobao": set(),
}
COMMERCE_CONTENT_TYPES = {
    "review",
    "follow_up_review",
    "review_snippet",
    "question",
    "answer",
    "return_record",
    "review_topic",
    "return_topic",
    "rating_only",
    "seller_response",
}
COMMERCE_TRANSACTION_STATUSES = {
    "verified_purchase",
    "transaction_linked",
    "unverified",
    "vine_free_product",
    "incentivized_disclosed",
    "unknown",
    "not_applicable",
}
COMMERCE_COMPLETENESS = {"full_text", "snippet", "aggregate", "rating_only"}

KICKSTARTER_REQUIRED = {
    "source_platform",
    "source_url",
    "campaign_id",
    "creator_id",
    "kickstarter_content_type",
    "campaign_status",
    "commercial_status",
    "privacy_status",
    "source_query",
    "created_at",
    "collected_at",
    "content_status",
} | CONNECTOR_PROVENANCE_REQUIRED
KICKSTARTER_CONFIG_REQUIRED = {
    "enabled",
    "researcher_role",
    "collection_mode",
    "access_basis",
    "terms_reviewed_at",
    "retention_rule",
    "backer_data_policy",
    "allow_personal_data",
    "min_unique_campaigns",
    "min_unique_creators",
    "max_campaign_share",
    "max_creator_share",
    "max_single_day_share",
    "require_original_source",
    "treat_ai_summaries_as_discovery_only",
} | CONNECTOR_CONFIG_REQUIRED
KICKSTARTER_ACCESS_BASES: set[str] = set()
KICKSTARTER_CONTENT_TYPES = {
    "campaign_page",
    "funding_snapshot",
    "comment",
    "creator_update",
    "faq",
    "pledge_record",
    "refund_record",
    "fulfillment_record",
    "tracker_snapshot",
}
KICKSTARTER_CAMPAIGN_STATUSES = {
    "prelaunch",
    "live",
    "successful",
    "failed",
    "canceled",
    "suspended",
    "unknown",
}
KICKSTARTER_COMMERCIAL_STATUSES = {
    "none",
    "public_aggregate",
    "pledged",
    "pledge_adjusted",
    "charged",
    "dropped",
    "refunded",
    "fulfilled",
    "not_applicable",
}
KICKSTARTER_PRIVACY_STATUSES = {"public", "deidentified", "aggregate"}


@dataclass
class Finding:
    check_id: str
    status: str
    detail: str
    stage: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.check_id,
            "status": self.status,
            "detail": self.detail,
            "stage": self.stage,
        }


@dataclass
class Audit:
    study_dir: Path
    requested_stage: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(self, check_id: str, status: str, detail: str, stage: str) -> None:
        self.findings.append(Finding(check_id, status, detail, stage))

    @property
    def status(self) -> str:
        return "fail" if any(item.status == "fail" for item in self.findings) else "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requested_stage": self.requested_stage,
            "study_dir": str(self.study_dir),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": self.metrics,
            "checks": [item.as_dict() for item in self.findings],
            "meaning": (
                "A pass confirms configured structural, product-reasoning, and evidence-chain gates only. "
                "It does not prove prevalence, market size, product success, release readiness, or causal demand."
            ),
        }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if not normalized:
            return True
        if normalized in {"tbd", "todo", "[fill]", "待填写", "待确认"}:
            return True
        if normalized.startswith(("tbd:", "todo:", "待填写", "待确认")):
            return True
    return False


def _missing_fields(value: Any, required: Iterable[str]) -> list[str]:
    if not isinstance(value, dict):
        return ["<object required>"]
    return sorted(field for field in required if field not in value or _is_missing(value[field]))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_connector_registry() -> dict[str, Any]:
    value = _load_json(REGISTRY_PATH)
    if not isinstance(value, dict) or not isinstance(value.get("connectors"), list):
        raise ValueError(f"invalid connector registry: {REGISTRY_PATH}")
    return value


def _connector_index() -> dict[str, dict[str, Any]]:
    registry = _load_connector_registry()
    result: dict[str, dict[str, Any]] = {}
    for item in registry["connectors"]:
        if not isinstance(item, dict) or _is_missing(item.get("id")):
            raise ValueError(f"connector registry contains an invalid entry: {REGISTRY_PATH}")
        connector_id = str(item["id"])
        if connector_id in result:
            raise ValueError(f"duplicate connector id in registry: {connector_id}")
        result[connector_id] = item
    return result


def _load_platform_map() -> dict[str, Any]:
    value = _load_json(PLATFORM_MAP_PATH)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("regions"), dict)
        or not isinstance(value.get("platforms"), dict)
    ):
        raise ValueError(f"invalid platform map: {PLATFORM_MAP_PATH}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} must be a JSON object")
        value["_line_number"] = line_number
        records.append(value)
    return records


def _study_paths(root: Path) -> dict[str, Path]:
    return {
        "study": root / "study.json",
        "sources": root / "01-sources" / "source-plan.csv",
        "evidence": root / "02-data" / "evidence.jsonl",
        "codebook": root / "03-codebook" / "codebook.csv",
        "reasoning": root / "04-findings" / "product-reasoning.json",
        "judgments": root / "04-findings" / "demand-judgments.json",
        "audit_dir": root / "05-audit",
    }


def _reddit_config(study: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(study, dict):
        return None
    adapters = study.get("source_adapters")
    if not isinstance(adapters, dict):
        return None
    reddit = adapters.get("reddit")
    return reddit if isinstance(reddit, dict) else None


def _source_adapter_config(
    study: dict[str, Any] | None, adapter_name: str
) -> dict[str, Any] | None:
    if not isinstance(study, dict):
        return None
    adapters = study.get("source_adapters")
    if not isinstance(adapters, dict):
        return None
    config = adapters.get(adapter_name)
    return config if isinstance(config, dict) else None


def _validate_reddit_config(study: dict[str, Any] | None) -> list[str]:
    config = _reddit_config(study)
    if config is None:
        return ["missing study.json source_adapters.reddit"]
    errors: list[str] = []
    missing = _missing_fields(config, REDDIT_CONFIG_REQUIRED)
    if missing:
        errors.append("reddit adapter missing: " + ", ".join(missing))
        return errors
    if config.get("enabled") is not True:
        errors.append("source_adapters.reddit.enabled must be true")
    if config.get("researcher_role") != "external_third_party":
        errors.append("reddit researcher_role must be external_third_party")
    if config.get("collection_mode") not in REDDIT_COLLECTION_MODES:
        errors.append(
            "reddit collection_mode must be one of: "
            + ", ".join(sorted(REDDIT_COLLECTION_MODES))
        )
    if config.get("access_basis") not in REDDIT_ACCESS_BASES:
        errors.append(
            "reddit access_basis must be one of: " + ", ".join(sorted(REDDIT_ACCESS_BASES))
        )
    if config.get("require_original_source") is not True:
        errors.append("reddit require_original_source must be true")
    if config.get("treat_ai_summaries_as_discovery_only") is not True:
        errors.append("reddit AI summaries must be discovery-only")
    try:
        datetime.fromisoformat(str(config.get("terms_reviewed_at", ""))[:10])
    except ValueError:
        errors.append("reddit terms_reviewed_at must be an ISO date")
    try:
        if int(config.get("min_unique_subreddits", 0)) < 1:
            errors.append("reddit min_unique_subreddits must be at least 1")
        if int(config.get("min_unique_threads", 0)) < 1:
            errors.append("reddit min_unique_threads must be at least 1")
        max_subreddit_share = float(config.get("max_subreddit_share", 0))
        max_thread_share = float(config.get("max_thread_share", 0))
        if not 0 < max_subreddit_share <= 1:
            errors.append("reddit max_subreddit_share must be in (0, 1]")
        if not 0 < max_thread_share <= 1:
            errors.append("reddit max_thread_share must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("reddit numeric thresholds must be valid numbers")
    return errors


def _is_reddit_record(record: dict[str, Any]) -> bool:
    source_family = str(record.get("source_family", "")).strip().lower()
    source_platform = str(record.get("source_platform", "")).strip().lower()
    return source_family == "reddit" or source_platform in {
        "reddit",
        "reddit.com",
        "www.reddit.com",
    }


def _validate_connector_selection(
    adapter_name: str, config: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    try:
        registry = _connector_index()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"cannot load open-source connector registry: {exc}"]

    connector_id = str(config.get("connector_id", "")).strip()
    selected = registry.get(connector_id)
    if selected is None:
        return [
            f"{adapter_name} connector_id {connector_id or '<empty>'} is not in "
            "assets/open-source-connectors.json"
        ]
    if selected.get("platform") != adapter_name:
        errors.append(
            f"{adapter_name} connector {connector_id} belongs to platform "
            f"{selected.get('platform')}"
        )

    decision = str(selected.get("decision", ""))
    if decision == "blocked":
        errors.append(f"{adapter_name} connector {connector_id} is blocked by the registry")
    elif decision not in {"supported", "historical_only"}:
        errors.append(f"{adapter_name} connector {connector_id} has unknown decision {decision}")

    expected_revision = str(selected.get("reviewed_revision", ""))
    if str(config.get("connector_revision", "")) != expected_revision:
        errors.append(
            f"{adapter_name} connector_revision is not the reviewed revision "
            f"{expected_revision} for {connector_id}"
        )
    expected_license = str(selected.get("license", ""))
    if str(config.get("connector_license", "")) != expected_license:
        errors.append(
            f"{adapter_name} connector_license must be {expected_license} for {connector_id}"
        )

    access_basis = str(config.get("access_basis", ""))
    allowed_access_bases = {
        str(value) for value in selected.get("allowed_access_bases", [])
    }
    if access_basis not in allowed_access_bases:
        expected = ", ".join(sorted(allowed_access_bases)) or "none"
        errors.append(
            f"{adapter_name} access_basis {access_basis or '<empty>'} is not permitted "
            f"for {connector_id}; expected {expected}"
        )

    policy_status = str(config.get("policy_status", ""))
    expected_policy_status = (
        "historical_data_only" if decision == "historical_only" else "approved_for_study"
    )
    if policy_status != expected_policy_status:
        errors.append(
            f"{adapter_name} policy_status must be {expected_policy_status} "
            f"for connector decision {decision}"
        )
    if decision == "historical_only" and config.get("collection_mode") != "historical_search":
        errors.append(
            f"{adapter_name} historical-only connector requires collection_mode=historical_search"
        )

    try:
        datetime.fromisoformat(str(config.get("data_rights_reviewed_at", ""))[:10])
    except ValueError:
        errors.append(f"{adapter_name} data_rights_reviewed_at must be an ISO date")
    return errors


def _validate_source_adapter_config(
    study: dict[str, Any] | None,
    adapter_name: str,
    required: set[str],
    access_bases: set[str],
) -> list[str]:
    config = _source_adapter_config(study, adapter_name)
    if config is None:
        return [f"missing study.json source_adapters.{adapter_name}"]
    errors: list[str] = []
    missing = _missing_fields(config, required)
    if missing:
        errors.append(f"{adapter_name} adapter missing: " + ", ".join(missing))
        return errors
    if config.get("enabled") is not True:
        errors.append(f"source_adapters.{adapter_name}.enabled must be true")
    if config.get("researcher_role") != "external_third_party":
        errors.append(f"{adapter_name} researcher_role must be external_third_party")
    if config.get("collection_mode") not in REDDIT_COLLECTION_MODES:
        errors.append(
            f"{adapter_name} collection_mode must be one of: "
            + ", ".join(sorted(REDDIT_COLLECTION_MODES))
        )
    if config.get("access_basis") not in access_bases:
        errors.append(
            f"{adapter_name} access_basis must be one of: " + ", ".join(sorted(access_bases))
        )
    if config.get("require_original_source") is not True:
        errors.append(f"{adapter_name} require_original_source must be true")
    if config.get("treat_ai_summaries_as_discovery_only") is not True:
        errors.append(f"{adapter_name} AI summaries must be discovery-only")
    try:
        datetime.fromisoformat(str(config.get("terms_reviewed_at", ""))[:10])
    except ValueError:
        errors.append(f"{adapter_name} terms_reviewed_at must be an ISO date")
    errors.extend(_validate_connector_selection(adapter_name, config))
    return errors


def _record_connector_errors(
    record: dict[str, Any], study: dict[str, Any] | None, adapter_name: str
) -> list[str]:
    config = _source_adapter_config(study, adapter_name)
    if config is None:
        return []
    record_id = str(record.get("record_id", "<unknown>"))
    errors: list[str] = []
    if record.get("connector_id") != config.get("connector_id"):
        errors.append(
            f"{record_id} connector_id does not match source_adapters.{adapter_name}"
        )
    if record.get("connector_revision") != config.get("connector_revision"):
        errors.append(
            f"{record_id} connector_revision does not match source_adapters.{adapter_name}"
        )
    return errors


def _validate_x_config(study: dict[str, Any] | None) -> list[str]:
    errors = _validate_source_adapter_config(study, "x", X_CONFIG_REQUIRED, X_ACCESS_BASES)
    config = _source_adapter_config(study, "x")
    if errors or config is None:
        return errors
    try:
        if int(config.get("min_unique_conversations", 0)) < 1:
            errors.append("x min_unique_conversations must be at least 1")
        if int(config.get("min_unique_days", 0)) < 1:
            errors.append("x min_unique_days must be at least 1")
        for field_name in ("max_conversation_share", "max_repost_share", "max_single_day_share"):
            value = float(config.get(field_name, 0))
            if not 0 < value <= 1:
                errors.append(f"x {field_name} must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("x numeric thresholds must be valid numbers")
    return errors


def _validate_youtube_config(study: dict[str, Any] | None) -> list[str]:
    errors = _validate_source_adapter_config(
        study, "youtube", YOUTUBE_CONFIG_REQUIRED, YOUTUBE_ACCESS_BASES
    )
    config = _source_adapter_config(study, "youtube")
    if errors or config is None:
        return errors
    try:
        if int(config.get("min_unique_channels", 0)) < 1:
            errors.append("youtube min_unique_channels must be at least 1")
        if int(config.get("min_unique_videos", 0)) < 1:
            errors.append("youtube min_unique_videos must be at least 1")
        for field_name in ("max_channel_share", "max_video_share"):
            value = float(config.get(field_name, 0))
            if not 0 < value <= 1:
                errors.append(f"youtube {field_name} must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("youtube numeric thresholds must be valid numbers")
    return errors


def _validate_marketplace_config(
    study: dict[str, Any] | None, adapter_name: str
) -> list[str]:
    errors = _validate_source_adapter_config(
        study,
        adapter_name,
        MARKETPLACE_CONFIG_REQUIRED,
        MARKETPLACE_ACCESS_BASES[adapter_name],
    )
    config = _source_adapter_config(study, adapter_name)
    if errors or config is None:
        return errors
    if config.get("require_variant_id") is not True:
        errors.append(f"{adapter_name} require_variant_id must be true")
    try:
        for field_name in ("min_unique_products", "min_unique_stores", "min_unique_brands"):
            if int(config.get(field_name, 0)) < 1:
                errors.append(f"{adapter_name} {field_name} must be at least 1")
        for field_name in (
            "max_product_share",
            "max_store_share",
            "max_brand_share",
            "max_single_month_share",
        ):
            value = float(config.get(field_name, 0))
            if not 0 < value <= 1:
                errors.append(f"{adapter_name} {field_name} must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append(f"{adapter_name} numeric thresholds must be valid numbers")
    return errors


def _validate_kickstarter_config(study: dict[str, Any] | None) -> list[str]:
    errors = _validate_source_adapter_config(
        study,
        "kickstarter",
        KICKSTARTER_CONFIG_REQUIRED,
        KICKSTARTER_ACCESS_BASES,
    )
    config = _source_adapter_config(study, "kickstarter")
    if errors or config is None:
        return errors
    if config.get("allow_personal_data") is not False:
        errors.append("kickstarter allow_personal_data must be false for the evidence workspace")
    try:
        for field_name in ("min_unique_campaigns", "min_unique_creators"):
            if int(config.get(field_name, 0)) < 1:
                errors.append(f"kickstarter {field_name} must be at least 1")
        for field_name in (
            "max_campaign_share",
            "max_creator_share",
            "max_single_day_share",
        ):
            value = float(config.get(field_name, 0))
            if not 0 < value <= 1:
                errors.append(f"kickstarter {field_name} must be in (0, 1]")
    except (TypeError, ValueError):
        errors.append("kickstarter numeric thresholds must be valid numbers")
    return errors


def _is_x_record(record: dict[str, Any]) -> bool:
    source_family = str(record.get("source_family", "")).strip().lower()
    source_platform = str(record.get("source_platform", "")).strip().lower()
    return source_family in {"x", "twitter"} or source_platform in {
        "x",
        "x.com",
        "www.x.com",
        "twitter",
        "twitter.com",
        "www.twitter.com",
    }


def _is_youtube_record(record: dict[str, Any]) -> bool:
    source_family = str(record.get("source_family", "")).strip().lower()
    source_platform = str(record.get("source_platform", "")).strip().lower()
    return source_family == "youtube" or source_platform in {
        "youtube",
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
    }


def _is_marketplace_record(record: dict[str, Any], adapter_name: str) -> bool:
    source_family = str(record.get("source_family", "")).strip().lower()
    source_platform = str(record.get("source_platform", "")).strip().lower()
    aliases = {
        "amazon": {"amazon", "amazon.com", "www.amazon.com"},
        "jd": {"jd", "jd.com", "www.jd.com", "jingdong"},
        "taobao": {"taobao", "taobao.com", "www.taobao.com", "tmall", "tmall.com"},
    }
    return source_family == adapter_name or source_platform in aliases[adapter_name]


def _is_kickstarter_record(record: dict[str, Any]) -> bool:
    source_family = str(record.get("source_family", "")).strip().lower()
    source_platform = str(record.get("source_platform", "")).strip().lower()
    return source_family == "kickstarter" or source_platform in {
        "kickstarter",
        "kickstarter.com",
        "www.kickstarter.com",
    }


def _source_day(value: Any) -> str:
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _source_month(value: Any) -> str:
    text = str(value).strip()
    return text[:7] if len(text) >= 7 else text


def _date_has_expired(value: Any) -> bool:
    text = str(value).strip()
    if len(text) == 10:
        try:
            return datetime.fromisoformat(text).date() < datetime.now(timezone.utc).date()
        except ValueError:
            return True
    try:
        due = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return True
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due < datetime.now(timezone.utc)


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _check_design(audit: Audit, paths: dict[str, Path]) -> dict[str, Any] | None:
    if not paths["study"].is_file():
        audit.add("study_contract", "fail", "missing study.json", "design")
        return None
    try:
        study = _load_json(paths["study"])
    except (OSError, json.JSONDecodeError) as exc:
        audit.add("study_contract", "fail", f"cannot parse study.json: {exc}", "design")
        return None

    errors: list[str] = []
    missing = _missing_fields(study, STUDY_REQUIRED)
    if missing:
        errors.append("study missing: " + ", ".join(missing))
    if isinstance(study, dict):
        for key, required in (
            ("decision", DECISION_REQUIRED),
            ("scope", SCOPE_REQUIRED),
            ("quality_gates", GATE_REQUIRED),
        ):
            nested_missing = _missing_fields(study.get(key), required)
            if nested_missing:
                errors.append(f"{key} missing: " + ", ".join(nested_missing))
        hypotheses = study.get("hypotheses", [])
        if isinstance(hypotheses, list):
            for index, hypothesis in enumerate(hypotheses, start=1):
                missing_h = _missing_fields(hypothesis, {"id", "statement", "falsified_if"})
                if missing_h:
                    errors.append(f"hypothesis {index} missing: " + ", ".join(missing_h))
        else:
            errors.append("hypotheses must be an array")
        decision = study.get("decision", {})
        if isinstance(decision, dict):
            for field_name in ("options", "minimum_evidence"):
                if not isinstance(decision.get(field_name), list):
                    errors.append(f"decision.{field_name} must be an array")
            options = decision.get("options")
            if isinstance(options, list):
                if len(options) < 2:
                    errors.append("decision.options must contain at least two choices")
                if any(_is_missing(option) for option in options):
                    errors.append("decision.options cannot contain blank or placeholder choices")
        scope = study.get("scope", {})
        if isinstance(scope, dict):
            for field_name in SCOPE_REQUIRED - {"source_time_window", "unit_of_observation"}:
                if not isinstance(scope.get(field_name), list):
                    errors.append(f"scope.{field_name} must be an array")
            window = scope.get("source_time_window")
            missing_window = _missing_fields(window, {"start", "end"})
            if missing_window:
                errors.append("scope.source_time_window missing: " + ", ".join(missing_window))
            else:
                try:
                    start = datetime.strptime(str(window["start"]), "%Y-%m-%d").date()
                    end = datetime.strptime(str(window["end"]), "%Y-%m-%d").date()
                    if start > end:
                        errors.append("scope.source_time_window start must not be after end")
                except (TypeError, ValueError):
                    errors.append("scope.source_time_window dates must use YYYY-MM-DD")
        gates = study.get("quality_gates", {})
        if isinstance(gates, dict):
            configured_roles = {str(value) for value in gates.get("required_corpus_roles", [])}
            invalid_configured_roles = sorted(configured_roles - CORPUS_ROLES)
            if invalid_configured_roles:
                errors.append("quality_gates has unknown corpus roles: " + ", ".join(invalid_configured_roles))
            try:
                if int(gates.get("min_evidence_records", 0)) < 1:
                    errors.append("quality_gates.min_evidence_records must be at least 1")
                source_share = float(gates.get("max_source_family_share", 0))
                duplicate_rate = float(gates.get("max_normalized_duplicate_rate", -1))
                if not 0 < source_share <= 1:
                    errors.append("quality_gates.max_source_family_share must be in (0, 1]")
                if not 0 <= duplicate_rate <= 1:
                    errors.append("quality_gates.max_normalized_duplicate_rate must be in [0, 1]")
            except (TypeError, ValueError):
                errors.append("quality_gates numeric thresholds must be valid numbers")

    audit.add(
        "study_contract",
        "fail" if errors else "pass",
        "; ".join(errors) if errors else "decision, scope, hypotheses and gates are explicit",
        "design",
    )

    source_errors: list[str] = []
    source_rows: list[dict[str, str]] = []
    if not paths["sources"].is_file():
        source_errors.append("missing 01-sources/source-plan.csv")
    else:
        try:
            with paths["sources"].open(encoding="utf-8-sig", newline="") as handle:
                source_rows = list(csv.DictReader(handle))
        except OSError as exc:
            source_errors.append(str(exc))
        required_columns = {
            "corpus_role",
            "source_family",
            "route_or_query",
            "target_records",
            "cap_share",
            "access_status",
            "known_bias",
        }
        if source_rows:
            missing_columns = sorted(required_columns - set(source_rows[0]))
            if missing_columns:
                source_errors.append("missing columns: " + ", ".join(missing_columns))
            else:
                for index, row in enumerate(source_rows, start=2):
                    for column in ("corpus_role", "source_family", "route_or_query", "access_status", "known_bias"):
                        if not str(row.get(column, "")).strip():
                            source_errors.append(f"row {index} has empty {column}")
                    try:
                        if int(row.get("target_records", "0")) < 1:
                            source_errors.append(f"row {index} target_records must be at least 1")
                    except ValueError:
                        source_errors.append(f"row {index} target_records is not an integer")
                    try:
                        cap_share = float(row.get("cap_share", ""))
                        if not 0 < cap_share <= 1:
                            source_errors.append(f"row {index} cap_share must be in (0, 1]")
                    except ValueError:
                        source_errors.append(f"row {index} cap_share is not a number")
        else:
            source_errors.append("source plan has no routes")

    required_roles = set()
    if isinstance(study, dict):
        gates = study.get("quality_gates", {})
        if isinstance(gates, dict) and isinstance(gates.get("required_corpus_roles"), list):
            required_roles = {str(role) for role in gates["required_corpus_roles"]}
    planned_roles = {row.get("corpus_role", "") for row in source_rows}
    unknown_roles = sorted((planned_roles - {""}) - CORPUS_ROLES)
    missing_roles = sorted(required_roles - planned_roles)
    if unknown_roles:
        source_errors.append("unknown corpus roles: " + ", ".join(unknown_roles))
    if missing_roles:
        source_errors.append("required roles without a route: " + ", ".join(missing_roles))
    audit.metrics["planned_routes"] = len(source_rows)
    audit.add(
        "source_plan",
        "fail" if source_errors else "pass",
        "; ".join(source_errors) if source_errors else f"{len(source_rows)} routes cover configured roles",
        "design",
    )
    reddit_planned = any(
        str(row.get("source_family", "")).strip().lower() == "reddit" for row in source_rows
    )
    if reddit_planned:
        reddit_errors = _validate_reddit_config(study if isinstance(study, dict) else None)
        audit.add(
            "reddit_source_design",
            "fail" if reddit_errors else "pass",
            "; ".join(reddit_errors)
            if reddit_errors
            else "Reddit access basis, retention rule and concentration gates are explicit",
            "design",
        )
    x_planned = any(
        str(row.get("source_family", "")).strip().lower() in {"x", "twitter"}
        for row in source_rows
    )
    if x_planned:
        x_errors = _validate_x_config(study if isinstance(study, dict) else None)
        audit.add(
            "x_source_design",
            "fail" if x_errors else "pass",
            "; ".join(x_errors)
            if x_errors
            else "X access basis, retention rule and event/conversation gates are explicit",
            "design",
        )
    youtube_planned = any(
        str(row.get("source_family", "")).strip().lower() == "youtube" for row in source_rows
    )
    if youtube_planned:
        youtube_errors = _validate_youtube_config(study if isinstance(study, dict) else None)
        audit.add(
            "youtube_source_design",
            "fail" if youtube_errors else "pass",
            "; ".join(youtube_errors)
            if youtube_errors
            else "YouTube access basis, refresh rule and channel/video gates are explicit",
            "design",
        )
    for adapter_name in MARKETPLACE_ADAPTERS:
        adapter_planned = any(
            str(row.get("source_family", "")).strip().lower() == adapter_name
            for row in source_rows
        )
        if not adapter_planned:
            continue
        adapter_errors = _validate_marketplace_config(
            study if isinstance(study, dict) else None, adapter_name
        )
        audit.add(
            f"{adapter_name}_source_design",
            "fail" if adapter_errors else "pass",
            "; ".join(adapter_errors)
            if adapter_errors
            else (
                f"{adapter_name} access basis, product hierarchy, transaction status "
                "and concentration gates are explicit"
            ),
            "design",
        )
    kickstarter_planned = any(
        str(row.get("source_family", "")).strip().lower() == "kickstarter"
        for row in source_rows
    )
    if kickstarter_planned:
        kickstarter_errors = _validate_kickstarter_config(
            study if isinstance(study, dict) else None
        )
        audit.add(
            "kickstarter_source_design",
            "fail" if kickstarter_errors else "pass",
            "; ".join(kickstarter_errors)
            if kickstarter_errors
            else (
                "Kickstarter access basis, backer-data boundary, campaign hierarchy "
                "and concentration gates are explicit"
            ),
            "design",
        )

    plan_mode = ""
    if isinstance(study, dict) and isinstance(study.get("plan"), dict):
        plan_mode = str(study["plan"].get("mode", "standard"))
    if plan_mode == "unnamed_experience":
        lexicon_errors: list[str] = []
        lexicon_path = paths["sources"].parent / "lexicon.csv"
        lexicon_rows: list[dict[str, str]] = []
        if not lexicon_path.is_file():
            lexicon_errors.append("missing 01-sources/lexicon.csv")
        else:
            with lexicon_path.open(encoding="utf-8-sig", newline="") as handle:
                lexicon_rows = list(csv.DictReader(handle))
            valid_rows = [
                row
                for row in lexicon_rows
                if all(
                    str(row.get(column, "")).strip()
                    for column in ("term", "term_type", "grounding_path", "expected_signal")
                )
            ]
            unknown_paths = sorted(
                {
                    str(row.get("grounding_path", "")).strip()
                    for row in valid_rows
                }
                - GROUNDING_PATHS
            )
            unknown_types = sorted(
                {str(row.get("term_type", "")).strip() for row in valid_rows} - LEXICON_TERM_TYPES
            )
            if unknown_paths:
                lexicon_errors.append("unknown grounding paths: " + ", ".join(unknown_paths))
            if unknown_types:
                lexicon_errors.append("unknown term types: " + ", ".join(unknown_types))
            if len(valid_rows) < LEXICON_MIN_TERMS:
                lexicon_errors.append(
                    f"{len(valid_rows)} valid terms is below the required {LEXICON_MIN_TERMS}"
                )
            covered_paths = {
                str(row.get("grounding_path", "")).strip() for row in valid_rows
            } & GROUNDING_PATHS
            if len(covered_paths) < LEXICON_MIN_PATHS:
                lexicon_errors.append(
                    f"{len(covered_paths)} grounding path(s) covered; at least "
                    f"{LEXICON_MIN_PATHS} required"
                )
            if "psychophysical" in covered_paths:
                space_path = paths["sources"].parent / "experience-space.csv"
                if not space_path.is_file():
                    lexicon_errors.append(
                        "psychophysical path used but 01-sources/experience-space.csv is missing"
                    )
                else:
                    with space_path.open(encoding="utf-8-sig", newline="") as handle:
                        space_rows = [
                            row
                            for row in csv.DictReader(handle)
                            if str(row.get("dimension", "")).strip()
                        ]
                    if not space_rows:
                        lexicon_errors.append(
                            "experience-space.csv has no stimulus dimensions"
                        )
        audit.metrics["lexicon_terms"] = len(lexicon_rows)
        audit.add(
            "lexicon_grounding",
            "fail" if lexicon_errors else "pass",
            "; ".join(lexicon_errors)
            if lexicon_errors
            else (
                f"{len(lexicon_rows)} lexicon terms ground the study across "
                f"{len({str(row.get('grounding_path', '')).strip() for row in lexicon_rows} & GROUNDING_PATHS)} paths"
            ),
            "design",
        )
    return study if isinstance(study, dict) else None


def _check_x_evidence(
    audit: Audit, records: list[dict[str, Any]], study: dict[str, Any] | None
) -> None:
    x_records = [record for record in records if _is_x_record(record)]
    if not x_records:
        return
    errors = _validate_x_config(study)
    conversation_counts: Counter[str] = Counter()
    day_counts: Counter[str] = Counter()
    repost_count = 0
    for record in x_records:
        record_id = str(record.get("record_id", "<unknown>"))
        missing = _missing_fields(record, X_REQUIRED)
        if missing:
            errors.append(f"{record_id} missing X provenance: " + ", ".join(missing))
            continue
        errors.extend(_record_connector_errors(record, study, "x"))
        if str(record.get("source_family", "")).strip().lower() != "x":
            errors.append(f"{record_id} must use source_family=x")
        post_type = str(record.get("x_post_type", "")).strip().lower()
        if post_type not in X_POST_TYPES:
            errors.append(f"{record_id} x_post_type must be one of: " + ", ".join(sorted(X_POST_TYPES)))
        if str(record.get("content_status", "")).strip().lower() != "present":
            errors.append(
                f"{record_id} content_status is not present; remove it from claim-eligible evidence"
            )
        if post_type == "repost":
            repost_count += 1
            if str(record.get("evidence_level", "")) != "E0":
                errors.append(f"{record_id} is a repost and may only be coded E0")
        conversation_counts[str(record["conversation_id"]).strip()] += 1
        day_counts[_source_day(record["created_at"])] += 1

    config = _source_adapter_config(study, "x")
    conversation_share = (
        max(conversation_counts.values()) / len(x_records) if conversation_counts else 0.0
    )
    day_share = max(day_counts.values()) / len(x_records) if day_counts else 0.0
    repost_share = repost_count / len(x_records) if x_records else 0.0
    if config is not None and not _validate_x_config(study):
        min_conversations = int(config["min_unique_conversations"])
        min_days = int(config["min_unique_days"])
        if len(conversation_counts) < min_conversations:
            errors.append(
                f"{len(conversation_counts)} unique X conversations is below configured minimum {min_conversations}"
            )
        if len(day_counts) < min_days:
            errors.append(f"{len(day_counts)} unique X days is below configured minimum {min_days}")
        if conversation_share > float(config["max_conversation_share"]):
            errors.append(
                f"dominant X conversation share {conversation_share:.1%} exceeds "
                f"{float(config['max_conversation_share']):.1%}"
            )
        if repost_share > float(config["max_repost_share"]):
            errors.append(
                f"X repost share {repost_share:.1%} exceeds {float(config['max_repost_share']):.1%}"
            )
        if day_share > float(config["max_single_day_share"]):
            errors.append(
                f"dominant X day share {day_share:.1%} exceeds {float(config['max_single_day_share']):.1%}"
            )
    audit.metrics["x"] = {
        "records": len(x_records),
        "unique_conversations": len(conversation_counts),
        "unique_days": len(day_counts),
        "dominant_conversation_share": round(conversation_share, 6),
        "dominant_day_share": round(day_share, 6),
        "repost_share": round(repost_share, 6),
    }
    audit.add(
        "x_evidence",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else (
            f"{_count_label(len(x_records), 'record')} with provenance across "
            f"{_count_label(len(conversation_counts), 'conversation')} and "
            f"{_count_label(len(day_counts), 'day')}"
        ),
        "evidence",
    )


def _check_youtube_evidence(
    audit: Audit, records: list[dict[str, Any]], study: dict[str, Any] | None
) -> None:
    youtube_records = [record for record in records if _is_youtube_record(record)]
    if not youtube_records:
        return
    errors = _validate_youtube_config(study)
    channel_counts: Counter[str] = Counter()
    video_counts: Counter[str] = Counter()
    for record in youtube_records:
        record_id = str(record.get("record_id", "<unknown>"))
        missing = _missing_fields(record, YOUTUBE_REQUIRED)
        if missing:
            errors.append(f"{record_id} missing YouTube provenance: " + ", ".join(missing))
            continue
        errors.extend(_record_connector_errors(record, study, "youtube"))
        if str(record.get("source_family", "")).strip().lower() != "youtube":
            errors.append(f"{record_id} must use source_family=youtube")
        content_type = str(record.get("youtube_content_type", "")).strip().lower()
        if content_type not in YOUTUBE_CONTENT_TYPES:
            errors.append(
                f"{record_id} youtube_content_type must be one of: "
                + ", ".join(sorted(YOUTUBE_CONTENT_TYPES))
            )
        if str(record.get("content_status", "")).strip().lower() != "present":
            errors.append(
                f"{record_id} content_status is not present; remove it from claim-eligible evidence"
            )
        if _date_has_expired(record.get("refresh_due_at")):
            errors.append(f"{record_id} refresh_due_at has passed or is invalid")
        if content_type in {"top_level_comment", "reply"} and _is_missing(record.get("comment_thread_id")):
            errors.append(f"{record_id} comment_thread_id is required for comments")
        if content_type == "reply" and _is_missing(record.get("parent_id")):
            errors.append(f"{record_id} parent_id is required for replies")
        if content_type == "transcript_segment" and _is_missing(record.get("transcript_access_basis")):
            errors.append(f"{record_id} transcript_access_basis is required for transcript segments")
        channel_counts[str(record["source_channel"]).strip()] += 1
        video_counts[str(record["youtube_video_id"]).strip()] += 1

    config = _source_adapter_config(study, "youtube")
    channel_share = max(channel_counts.values()) / len(youtube_records) if channel_counts else 0.0
    video_share = max(video_counts.values()) / len(youtube_records) if video_counts else 0.0
    if config is not None and not _validate_youtube_config(study):
        min_channels = int(config["min_unique_channels"])
        min_videos = int(config["min_unique_videos"])
        if len(channel_counts) < min_channels:
            errors.append(
                f"{len(channel_counts)} unique YouTube channels is below configured minimum {min_channels}"
            )
        if len(video_counts) < min_videos:
            errors.append(
                f"{len(video_counts)} unique YouTube videos is below configured minimum {min_videos}"
            )
        if channel_share > float(config["max_channel_share"]):
            errors.append(
                f"dominant YouTube channel share {channel_share:.1%} exceeds "
                f"{float(config['max_channel_share']):.1%}"
            )
        if video_share > float(config["max_video_share"]):
            errors.append(
                f"dominant YouTube video share {video_share:.1%} exceeds "
                f"{float(config['max_video_share']):.1%}"
            )
    audit.metrics["youtube"] = {
        "records": len(youtube_records),
        "unique_channels": len(channel_counts),
        "unique_videos": len(video_counts),
        "dominant_channel_share": round(channel_share, 6),
        "dominant_video_share": round(video_share, 6),
    }
    audit.add(
        "youtube_evidence",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else (
            f"{_count_label(len(youtube_records), 'record')} with provenance across "
            f"{_count_label(len(channel_counts), 'channel')} and "
            f"{_count_label(len(video_counts), 'video')}"
        ),
        "evidence",
    )


def _check_marketplace_evidence(
    audit: Audit,
    records: list[dict[str, Any]],
    study: dict[str, Any] | None,
    adapter_name: str,
) -> None:
    marketplace_records = [
        record for record in records if _is_marketplace_record(record, adapter_name)
    ]
    if not marketplace_records:
        return
    errors = _validate_marketplace_config(study, adapter_name)
    product_counts: Counter[str] = Counter()
    store_counts: Counter[str] = Counter()
    brand_counts: Counter[str] = Counter()
    month_counts: Counter[str] = Counter()
    for record in marketplace_records:
        record_id = str(record.get("record_id", "<unknown>"))
        missing = _missing_fields(record, MARKETPLACE_REQUIRED)
        if missing:
            errors.append(
                f"{record_id} missing {adapter_name} commerce provenance: "
                + ", ".join(missing)
            )
            continue
        errors.extend(_record_connector_errors(record, study, adapter_name))
        if str(record.get("source_family", "")).strip().lower() != adapter_name:
            errors.append(f"{record_id} must use source_family={adapter_name}")
        content_type = str(record.get("commerce_content_type", "")).strip().lower()
        transaction_status = str(record.get("commerce_transaction_status", "")).strip().lower()
        completeness = str(record.get("source_completeness", "")).strip().lower()
        evidence_level = str(record.get("evidence_level", ""))
        if content_type not in COMMERCE_CONTENT_TYPES:
            errors.append(
                f"{record_id} commerce_content_type must be one of: "
                + ", ".join(sorted(COMMERCE_CONTENT_TYPES))
            )
        if transaction_status not in COMMERCE_TRANSACTION_STATUSES:
            errors.append(
                f"{record_id} commerce_transaction_status must be one of: "
                + ", ".join(sorted(COMMERCE_TRANSACTION_STATUSES))
            )
        if completeness not in COMMERCE_COMPLETENESS:
            errors.append(
                f"{record_id} source_completeness must be one of: "
                + ", ".join(sorted(COMMERCE_COMPLETENESS))
            )
        if str(record.get("content_status", "")).strip().lower() != "present":
            errors.append(
                f"{record_id} content_status is not present; remove it from claim-eligible evidence"
            )
        if content_type in {"rating_only", "seller_response"} and evidence_level != "E0":
            errors.append(f"{record_id} {content_type} may only be coded E0")
        if content_type in {"review_snippet", "review_topic"} and evidence_level not in {
            "E0",
            "E1",
            "E2",
        }:
            errors.append(f"{record_id} {content_type} may only be coded E0, E1, or E2")
        if content_type == "question" and evidence_level not in {"E0", "E1"}:
            errors.append(f"{record_id} a commerce question may only be coded E0 or E1")
        if completeness == "rating_only" and evidence_level != "E0":
            errors.append(f"{record_id} rating-only evidence may only be coded E0")
        if completeness == "snippet" and evidence_level not in {"E0", "E1", "E2"}:
            errors.append(f"{record_id} a truncated snippet may only be coded E0, E1, or E2")
        if transaction_status in {"vine_free_product", "incentivized_disclosed"} and evidence_level in {
            "E4+",
            "E5",
        }:
            errors.append(
                f"{record_id} {transaction_status} cannot support paid intent or realized purchase"
            )
        product_counts[str(record["commerce_product_id"]).strip()] += 1
        store_counts[str(record["commerce_store_id"]).strip()] += 1
        brand_counts[str(record["commerce_brand"]).strip().lower()] += 1
        month_counts[_source_month(record["created_at"])] += 1

    total = len(marketplace_records)
    product_share = max(product_counts.values()) / total if product_counts else 0.0
    store_share = max(store_counts.values()) / total if store_counts else 0.0
    brand_share = max(brand_counts.values()) / total if brand_counts else 0.0
    month_share = max(month_counts.values()) / total if month_counts else 0.0
    config = _source_adapter_config(study, adapter_name)
    if config is not None and not _validate_marketplace_config(study, adapter_name):
        for label, counts, field_name in (
            ("products", product_counts, "min_unique_products"),
            ("stores", store_counts, "min_unique_stores"),
            ("brands", brand_counts, "min_unique_brands"),
        ):
            minimum = int(config[field_name])
            if len(counts) < minimum:
                errors.append(
                    f"{len(counts)} unique {adapter_name} {label} is below configured minimum {minimum}"
                )
        for label, share, field_name in (
            ("product", product_share, "max_product_share"),
            ("store", store_share, "max_store_share"),
            ("brand", brand_share, "max_brand_share"),
            ("month", month_share, "max_single_month_share"),
        ):
            maximum = float(config[field_name])
            if share > maximum:
                errors.append(
                    f"dominant {adapter_name} {label} share {share:.1%} exceeds {maximum:.1%}"
                )
    audit.metrics[adapter_name] = {
        "records": total,
        "unique_products": len(product_counts),
        "unique_stores": len(store_counts),
        "unique_brands": len(brand_counts),
        "unique_months": len(month_counts),
        "dominant_product_share": round(product_share, 6),
        "dominant_store_share": round(store_share, 6),
        "dominant_brand_share": round(brand_share, 6),
        "dominant_month_share": round(month_share, 6),
    }
    audit.add(
        f"{adapter_name}_evidence",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else (
            f"{_count_label(total, 'record')} with product/variant provenance across "
            f"{_count_label(len(product_counts), 'product')}, "
            f"{_count_label(len(store_counts), 'store')}, and "
            f"{_count_label(len(brand_counts), 'brand')}"
        ),
        "evidence",
    )


def _check_kickstarter_evidence(
    audit: Audit, records: list[dict[str, Any]], study: dict[str, Any] | None
) -> None:
    kickstarter_records = [record for record in records if _is_kickstarter_record(record)]
    if not kickstarter_records:
        return
    errors = _validate_kickstarter_config(study)
    campaign_counts: Counter[str] = Counter()
    creator_counts: Counter[str] = Counter()
    day_counts: Counter[str] = Counter()
    for record in kickstarter_records:
        record_id = str(record.get("record_id", "<unknown>"))
        missing = _missing_fields(record, KICKSTARTER_REQUIRED)
        if missing:
            errors.append(
                f"{record_id} missing Kickstarter provenance: " + ", ".join(missing)
            )
            continue
        errors.extend(_record_connector_errors(record, study, "kickstarter"))
        if str(record.get("source_family", "")).strip().lower() != "kickstarter":
            errors.append(f"{record_id} must use source_family=kickstarter")
        content_type = str(record.get("kickstarter_content_type", "")).strip().lower()
        campaign_status = str(record.get("campaign_status", "")).strip().lower()
        commercial_status = str(record.get("commercial_status", "")).strip().lower()
        privacy_status = str(record.get("privacy_status", "")).strip().lower()
        evidence_level = str(record.get("evidence_level", ""))
        if content_type not in KICKSTARTER_CONTENT_TYPES:
            errors.append(
                f"{record_id} kickstarter_content_type must be one of: "
                + ", ".join(sorted(KICKSTARTER_CONTENT_TYPES))
            )
        if campaign_status not in KICKSTARTER_CAMPAIGN_STATUSES:
            errors.append(
                f"{record_id} campaign_status must be one of: "
                + ", ".join(sorted(KICKSTARTER_CAMPAIGN_STATUSES))
            )
        if commercial_status not in KICKSTARTER_COMMERCIAL_STATUSES:
            errors.append(
                f"{record_id} commercial_status must be one of: "
                + ", ".join(sorted(KICKSTARTER_COMMERCIAL_STATUSES))
            )
        if privacy_status not in KICKSTARTER_PRIVACY_STATUSES:
            errors.append(
                f"{record_id} privacy_status must be one of: "
                + ", ".join(sorted(KICKSTARTER_PRIVACY_STATUSES))
            )
        if str(record.get("content_status", "")).strip().lower() != "present":
            errors.append(
                f"{record_id} content_status is not present; remove it from claim-eligible evidence"
            )
        if content_type in {"campaign_page", "creator_update", "faq", "tracker_snapshot"} and evidence_level != "E0":
            errors.append(f"{record_id} {content_type} is creator/aggregate context and may only be coded E0")
        if content_type == "funding_snapshot" and evidence_level not in {"E0", "E4+"}:
            errors.append(f"{record_id} funding_snapshot may only be coded E0 or E4+")
        if content_type == "funding_snapshot" and commercial_status != "public_aggregate":
            errors.append(f"{record_id} funding_snapshot requires commercial_status=public_aggregate")
        if commercial_status in {"pledged", "pledge_adjusted", "public_aggregate"} and evidence_level == "E5":
            errors.append(
                f"{record_id} {commercial_status} is not realized use and cannot be coded E5"
            )
        if content_type in {"pledge_record", "refund_record", "fulfillment_record"} and privacy_status == "public":
            errors.append(
                f"{record_id} private backer records must be deidentified or aggregated before evidence use"
            )
        campaign_counts[str(record["campaign_id"]).strip()] += 1
        creator_counts[str(record["creator_id"]).strip()] += 1
        day_counts[_source_day(record["created_at"])] += 1

    total = len(kickstarter_records)
    campaign_share = max(campaign_counts.values()) / total if campaign_counts else 0.0
    creator_share = max(creator_counts.values()) / total if creator_counts else 0.0
    day_share = max(day_counts.values()) / total if day_counts else 0.0
    config = _source_adapter_config(study, "kickstarter")
    if config is not None and not _validate_kickstarter_config(study):
        min_campaigns = int(config["min_unique_campaigns"])
        min_creators = int(config["min_unique_creators"])
        if len(campaign_counts) < min_campaigns:
            errors.append(
                f"{len(campaign_counts)} unique Kickstarter campaigns is below configured minimum {min_campaigns}"
            )
        if len(creator_counts) < min_creators:
            errors.append(
                f"{len(creator_counts)} unique Kickstarter creators is below configured minimum {min_creators}"
            )
        for label, share, field_name in (
            ("campaign", campaign_share, "max_campaign_share"),
            ("creator", creator_share, "max_creator_share"),
            ("day", day_share, "max_single_day_share"),
        ):
            maximum = float(config[field_name])
            if share > maximum:
                errors.append(
                    f"dominant Kickstarter {label} share {share:.1%} exceeds {maximum:.1%}"
                )
    audit.metrics["kickstarter"] = {
        "records": total,
        "unique_campaigns": len(campaign_counts),
        "unique_creators": len(creator_counts),
        "unique_days": len(day_counts),
        "dominant_campaign_share": round(campaign_share, 6),
        "dominant_creator_share": round(creator_share, 6),
        "dominant_day_share": round(day_share, 6),
    }
    audit.add(
        "kickstarter_evidence",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else (
            f"{_count_label(total, 'record')} with campaign provenance across "
            f"{_count_label(len(campaign_counts), 'campaign')} and "
            f"{_count_label(len(creator_counts), 'creator')}"
        ),
        "evidence",
    )


def _check_evidence(
    audit: Audit, paths: dict[str, Path], study: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if paths["codebook"].is_file():
        audit.add("codebook", "pass", "03-codebook/codebook.csv is present", "evidence")
    else:
        audit.add("codebook", "fail", "missing 03-codebook/codebook.csv", "evidence")
    if not paths["evidence"].is_file():
        audit.add("evidence_records", "fail", "missing 02-data/evidence.jsonl", "evidence")
        return [], {}
    try:
        records = _load_jsonl(paths["evidence"])
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        audit.add("evidence_records", "fail", f"cannot parse evidence JSONL: {exc}", "evidence")
        return [], {}

    errors: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    normalized_hashes: list[str] = []
    role_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    for record in records:
        line_number = record.pop("_line_number")
        missing = _missing_fields(record, EVIDENCE_REQUIRED)
        if missing:
            errors.append(f"line {line_number} missing: " + ", ".join(missing))
            continue
        record_id = str(record["record_id"])
        if record_id in by_id:
            errors.append(f"duplicate record_id: {record_id}")
        by_id[record_id] = record
        level = str(record["evidence_level"])
        if level not in LEVELS:
            errors.append(f"{record_id} has invalid evidence_level {level}")
        role = str(record["corpus_role"])
        if role not in CORPUS_ROLES:
            errors.append(f"{record_id} has invalid corpus_role {role}")
        normalized_hashes.append(str(record["normalized_text_hash"]))
        role_counts[role] += 1
        source_counts[str(record["source_family"])] += 1
        level_counts[level] += 1

    gates = study.get("quality_gates", {}) if isinstance(study, dict) else {}
    min_records = int(gates.get("min_evidence_records", 1))
    if len(records) < min_records:
        errors.append(f"{len(records)} records is below configured minimum {min_records}")
    required_roles = {str(value) for value in gates.get("required_corpus_roles", [])}
    missing_roles = sorted(required_roles - set(role_counts))
    if missing_roles:
        errors.append("missing configured corpus roles: " + ", ".join(missing_roles))

    planned_source_families: set[str] = set()
    if paths["sources"].is_file():
        try:
            with paths["sources"].open(encoding="utf-8-sig", newline="") as handle:
                planned_source_families = {
                    str(row.get("source_family", "")).strip()
                    for row in csv.DictReader(handle)
                    if str(row.get("source_family", "")).strip()
                }
        except OSError:
            pass
    unplanned_source_families = sorted(set(source_counts) - planned_source_families)
    if unplanned_source_families:
        errors.append(
            "evidence uses source families absent from source plan: "
            + ", ".join(unplanned_source_families)
        )

    duplicate_count = len(normalized_hashes) - len(set(normalized_hashes))
    duplicate_rate = duplicate_count / len(normalized_hashes) if normalized_hashes else 0.0
    max_duplicate_rate = float(gates.get("max_normalized_duplicate_rate", 1.0))
    if duplicate_rate > max_duplicate_rate:
        errors.append(
            f"normalized duplicate rate {duplicate_rate:.1%} exceeds {max_duplicate_rate:.1%}"
        )
    dominant_share = max(source_counts.values()) / len(records) if records and source_counts else 0.0
    max_source_share = float(gates.get("max_source_family_share", 1.0))
    if dominant_share > max_source_share:
        errors.append(f"dominant source-family share {dominant_share:.1%} exceeds {max_source_share:.1%}")

    audit.metrics.update(
        {
            "evidence_records": len(records),
            "evidence_levels": dict(sorted(level_counts.items())),
            "corpus_roles": dict(sorted(role_counts.items())),
            "source_families": dict(sorted(source_counts.items())),
            "normalized_duplicate_rate": round(duplicate_rate, 6),
            "dominant_source_family_share": round(dominant_share, 6),
        }
    )
    audit.add(
        "evidence_records",
        "fail" if errors else "pass",
        "; ".join(errors) if errors else f"{len(records)} records meet configured evidence gates",
        "evidence",
    )

    reddit_records = [record for record in records if _is_reddit_record(record)]
    if reddit_records:
        reddit_errors = _validate_reddit_config(study)
        subreddit_counts: Counter[str] = Counter()
        thread_counts: Counter[str] = Counter()
        for record in reddit_records:
            record_id = str(record.get("record_id", "<unknown>"))
            missing = _missing_fields(record, REDDIT_REQUIRED)
            if missing:
                reddit_errors.append(f"{record_id} missing Reddit provenance: " + ", ".join(missing))
                continue
            reddit_errors.extend(_record_connector_errors(record, study, "reddit"))
            if str(record.get("source_family", "")).strip().lower() != "reddit":
                reddit_errors.append(f"{record_id} must use source_family=reddit")
            if str(record.get("source_content_type", "")).strip().lower() not in {"post", "comment"}:
                reddit_errors.append(f"{record_id} source_content_type must be post or comment")
            if str(record.get("content_status", "")).strip().lower() != "present":
                reddit_errors.append(
                    f"{record_id} content_status is not present; remove it from claim-eligible evidence"
                )
            subreddit_counts[str(record["source_channel"]).strip().lower()] += 1
            thread_counts[str(record["thread_id"]).strip()] += 1

        config = _reddit_config(study)
        subreddit_share = (
            max(subreddit_counts.values()) / len(reddit_records) if subreddit_counts else 0.0
        )
        thread_share = max(thread_counts.values()) / len(reddit_records) if thread_counts else 0.0
        if config is not None and not _validate_reddit_config(study):
            min_subreddits = int(config["min_unique_subreddits"])
            min_threads = int(config["min_unique_threads"])
            max_subreddit_share = float(config["max_subreddit_share"])
            max_thread_share = float(config["max_thread_share"])
            if len(subreddit_counts) < min_subreddits:
                reddit_errors.append(
                    f"{len(subreddit_counts)} unique subreddits is below configured minimum {min_subreddits}"
                )
            if len(thread_counts) < min_threads:
                reddit_errors.append(
                    f"{len(thread_counts)} unique threads is below configured minimum {min_threads}"
                )
            if subreddit_share > max_subreddit_share:
                reddit_errors.append(
                    f"dominant subreddit share {subreddit_share:.1%} exceeds {max_subreddit_share:.1%}"
                )
            if thread_share > max_thread_share:
                reddit_errors.append(
                    f"dominant Reddit thread share {thread_share:.1%} exceeds {max_thread_share:.1%}"
                )
        audit.metrics["reddit"] = {
            "records": len(reddit_records),
            "unique_subreddits": len(subreddit_counts),
            "unique_threads": len(thread_counts),
            "dominant_subreddit_share": round(subreddit_share, 6),
            "dominant_thread_share": round(thread_share, 6),
        }
        audit.add(
            "reddit_evidence",
            "fail" if reddit_errors else "pass",
            "; ".join(reddit_errors)
            if reddit_errors
            else (
                f"{_count_label(len(reddit_records), 'record')} with route provenance across "
                f"{_count_label(len(subreddit_counts), 'subreddit')} and "
                f"{_count_label(len(thread_counts), 'thread')}"
            ),
            "evidence",
        )
    _check_x_evidence(audit, records, study)
    _check_youtube_evidence(audit, records, study)
    for adapter_name in MARKETPLACE_ADAPTERS:
        _check_marketplace_evidence(audit, records, study, adapter_name)
    _check_kickstarter_evidence(audit, records, study)
    return records, by_id


def _check_decisions(
    audit: Audit,
    paths: dict[str, Path],
    study: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[Any]:
    if not paths["judgments"].is_file():
        audit.add(
            "demand_judgments",
            "fail",
            "missing 04-findings/demand-judgments.json",
            "decision",
        )
        return []
    try:
        judgments = _load_json(paths["judgments"])
    except (OSError, json.JSONDecodeError) as exc:
        audit.add("demand_judgments", "fail", f"cannot parse demand judgments: {exc}", "decision")
        return []
    if not isinstance(judgments, list) or not judgments:
        audit.add("demand_judgments", "fail", "demand judgments must be a non-empty array", "decision")
        return []

    errors: list[str] = []
    allowed_status = {"hypothesis", "needs-validation", "validated", "rejected", "deprioritized"}
    allowed_confidence = {"low", "medium", "high"}
    require_counter = bool(
        (study or {}).get("quality_gates", {}).get("require_counter_evidence_for_validated", True)
    )
    for index, judgment in enumerate(judgments, start=1):
        if not isinstance(judgment, dict):
            errors.append(f"judgment {index} must be an object")
            continue
        judgment_id = str(judgment.get("id") or index)
        array_fields = {
            "problem_evidence_ids",
            "solution_evidence_ids",
            "commercial_evidence_ids",
            "counter_evidence_ids",
            "gaps",
        }
        missing = sorted(field for field in JUDGMENT_REQUIRED if field not in judgment)
        missing.extend(
            sorted(
                field
                for field in JUDGMENT_REQUIRED - array_fields
                if field in judgment and _is_missing(judgment[field])
            )
        )
        if missing:
            errors.append(f"{judgment_id} missing: " + ", ".join(missing))
            continue
        if judgment["status"] not in allowed_status:
            errors.append(f"{judgment_id} has invalid status {judgment['status']}")
        if judgment["confidence"] not in allowed_confidence:
            errors.append(f"{judgment_id} has invalid confidence {judgment['confidence']}")
        reference_groups = {
            "problem": (judgment["problem_evidence_ids"], {"E1", "E2"}),
            "solution": (judgment["solution_evidence_ids"], {"E3"}),
            "commercial": (judgment["commercial_evidence_ids"], {"E4+", "E5"}),
            "counter": (judgment["counter_evidence_ids"], {"E4-", "E0", "E1", "E2", "E3", "E4+", "E5"}),
        }
        all_references = {
            str(value) for values, _ in reference_groups.values() for value in values
        }
        unknown = sorted(all_references - set(evidence_by_id))
        if unknown:
            errors.append(f"{judgment_id} references unknown evidence: " + ", ".join(unknown))
        if judgment["status"] == "validated":
            for chain_name in ("problem", "solution", "commercial"):
                ids, accepted_levels = reference_groups[chain_name]
                observed_levels = {
                    str(evidence_by_id[str(value)]["evidence_level"])
                    for value in ids
                    if str(value) in evidence_by_id
                }
                if not observed_levels.intersection(accepted_levels):
                    errors.append(f"{judgment_id} lacks {chain_name} evidence for validated status")
            if require_counter and not judgment["counter_evidence_ids"]:
                errors.append(f"{judgment_id} lacks counter-evidence for validated status")
            context_key = str(judgment.get("context_key") or "").strip()
            if not context_key:
                errors.append(f"{judgment_id} lacks context_key for validated status")
            else:
                mismatched = sorted(
                    value for value in all_references
                    if value in evidence_by_id
                    and str(evidence_by_id[value].get("context_key") or "").strip() != context_key
                )
                if mismatched:
                    errors.append(
                        f"{judgment_id} has evidence from a different or missing context_key: "
                        + ", ".join(mismatched)
                    )

    audit.metrics["demand_judgments"] = len(judgments)
    audit.metrics["validated_judgments"] = sum(
        1 for item in judgments if isinstance(item, dict) and item.get("status") == "validated"
    )
    audit.add(
        "demand_judgments",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else (
            "1 judgment has traceable evidence references"
            if len(judgments) == 1
            else f"{len(judgments)} judgments have traceable evidence references"
        ),
        "decision",
    )
    return judgments


def _check_product_reasoning(
    audit: Audit,
    paths: dict[str, Path],
    study: dict[str, Any] | None,
    evidence_by_id: dict[str, dict[str, Any]],
    judgments: list[Any],
    design_only: bool = False,
) -> None:
    """Check the product spine without pretending that evidence proves an inference."""
    stage = "design" if design_only else "decision"
    configured = isinstance(study, dict) and isinstance(study.get("product_reasoning"), dict)
    if not paths["reasoning"].is_file():
        if configured:
            audit.add(
                "product_reasoning",
                "fail",
                "missing 04-findings/product-reasoning.json",
                stage,
            )
        else:
            audit.add(
                "product_reasoning",
                "pass",
                "legacy study without a product-reasoning contract; run `askovo chain STUDY` to adopt one",
                stage,
            )
        return
    try:
        data = _load_json(paths["reasoning"])
    except (OSError, json.JSONDecodeError) as exc:
        audit.add("product_reasoning", "fail", f"cannot parse product reasoning: {exc}", stage)
        return
    if not isinstance(data, dict):
        audit.add("product_reasoning", "fail", "product reasoning must be an object", stage)
        return
    audit.metrics["product_reasoning"] = sure_engine.product_reasoning_summary(data)
    errors: list[str] = []
    flow_value = data.get("flow")
    allowed_flows = (list(sure_engine.LEGACY_REASONING_NODES), list(sure_engine.REASONING_NODES))
    if flow_value not in allowed_flows:
        errors.append("flow must be the legacy six-node or current seven-node chain ending in business")
        required_nodes = sure_engine.REASONING_NODES
    else:
        required_nodes = tuple(flow_value)
    chains = data.get("chains")
    if not isinstance(chains, list) or not chains:
        audit.add("product_reasoning", "fail", "chains must be a non-empty array", stage)
        return

    node_statuses = {"hypothesis", "needs-validation", "validated", "rejected", "deprioritized"}
    chain_statuses = {"draft", "hypothesis", "needs-validation", "decided", "rejected", "deprioritized"}
    allowed_confidence = {"low", "medium", "high"}
    judgment_by_id = {
        str(item.get("id")): item for item in judgments if isinstance(item, dict) and item.get("id")
    }
    require_counter = bool(
        (study or {}).get("quality_gates", {}).get("require_counter_evidence_for_validated", True)
    )
    seen_chain_ids: set[str] = set()
    linked_judgment_ids: list[str] = []
    for index, chain in enumerate(chains, start=1):
        if not isinstance(chain, dict):
            errors.append(f"chain {index} must be an object")
            continue
        chain_id = str(chain.get("id") or f"chain-{index}")
        if chain_id in seen_chain_ids:
            errors.append(f"{chain_id} duplicates a chain id")
        seen_chain_ids.add(chain_id)
        for field_name in ("id", "title", "status", "confidence", "next_test"):
            if _is_missing(chain.get(field_name)):
                errors.append(f"{chain_id} missing {field_name}")
        if chain.get("status") not in chain_statuses:
            errors.append(f"{chain_id} has invalid status {chain.get('status')}")
        if chain.get("confidence") not in allowed_confidence:
            errors.append(f"{chain_id} has invalid confidence {chain.get('confidence')}")
        for field_name in ("alternative_explanations", "counter_evidence_ids", "gaps"):
            if not isinstance(chain.get(field_name), list):
                errors.append(f"{chain_id}.{field_name} must be an array")
        if "human_review" in chain and not isinstance(chain.get("human_review"), dict):
            errors.append(f"{chain_id}.human_review must be an object")
        prioritization = chain.get("prioritization", {})
        if not isinstance(prioritization, dict):
            errors.append(f"{chain_id}.prioritization must be an object")
            prioritization = {}
        if chain.get("status") == "decided" and "business" in required_nodes:
            for field_name in ("method", "owner", "rationale"):
                if _is_missing(prioritization.get(field_name)):
                    errors.append(f"{chain_id}.prioritization decided requires {field_name}")
        if "change_log" in chain:
            if not isinstance(chain.get("change_log"), list):
                errors.append(f"{chain_id}.change_log must be an array")
            else:
                for entry in chain.get("change_log", []):
                    if not isinstance(entry, dict):
                        errors.append(f"{chain_id}.change_log entries must be objects")
                        continue
                    for field_name in ("id", "impact", "decision", "projection_sync"):
                        if _is_missing(entry.get(field_name)):
                            errors.append(f"{chain_id}.change_log requires {field_name}")
        states = chain.get("supporting_states", {})
        if not isinstance(states, dict):
            errors.append(f"{chain_id}.supporting_states must be an object")
            states = {}
        state_rules = {
            "delivery": ({"unplanned", "in-progress", "release-ready", "rolling-out", "paused", "rolled-back"}, "release_plan_ref"),
            "outcome": ({"unmeasured", "observing", "positive-observed", "no-effect", "negative", "inconclusive"}, "metric_refs"),
            "causal": ({"not-claimed", "supported", "refuted", "inconclusive"}, "experiment_refs"),
        }
        for state_name, (allowed, reference_field) in state_rules.items():
            value = states.get(state_name, {})
            if not isinstance(value, dict):
                errors.append(f"{chain_id}.supporting_states.{state_name} must be an object")
                continue
            status = str(value.get("status") or "")
            if status and status not in allowed:
                errors.append(f"{chain_id}.{state_name} has invalid supporting status {status}")
            needs_reference = (
                state_name == "delivery" and status in {"release-ready", "rolling-out", "paused", "rolled-back"}
            ) or (
                state_name == "outcome" and status not in {"", "unmeasured"}
            ) or (
                state_name == "causal" and status in {"supported", "refuted"}
            )
            reference = value.get(reference_field)
            if needs_reference and _is_missing(reference):
                errors.append(f"{chain_id}.{state_name}.{status} requires {reference_field}")
        nodes = chain.get("nodes")
        if not isinstance(nodes, dict):
            errors.append(f"{chain_id}.nodes must be an object")
            continue

        all_references: set[str] = set()
        node_references: dict[str, set[str]] = {}
        any_validated_node = False
        for node_name in required_nodes:
            node = nodes.get(node_name)
            prefix = f"{chain_id}.{node_name}"
            if not isinstance(node, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field_name in ("statement", "rationale", "status"):
                if _is_missing(node.get(field_name)):
                    errors.append(f"{prefix} missing {field_name}")
            if node.get("status") not in node_statuses:
                errors.append(f"{prefix} has invalid status {node.get('status')}")
            for field_name in ("evidence_ids", "assumptions"):
                if not isinstance(node.get(field_name), list):
                    errors.append(f"{prefix}.{field_name} must be an array")
            evidence_ids = node.get("evidence_ids") if isinstance(node.get("evidence_ids"), list) else []
            node_references[node_name] = {str(value) for value in evidence_ids}
            all_references.update(node_references[node_name])
            if node.get("status") != "validated":
                continue
            any_validated_node = True
            detail_fields = {
                "scene": ("trigger", "environment", "task_context"),
                "user": ("role", "state", "decision_role"),
                "pain": ("current_substitute", "friction_cost", "consequence"),
                "need": ("desired_outcome", "measure"),
                "feature": ("capability",),
                "product": ("form", "scope"),
                "business": ("market_definition", "geographies", "time_window", "target_segment", "payer", "positioning", "revenue_model", "pricing_hypothesis"),
            }[node_name]
            for field_name in detail_fields:
                if _is_missing(node.get(field_name)):
                    errors.append(f"{prefix} validated requires {field_name}")
            array_details = {
                "need": ("constraints",),
                "feature": ("acceptance_conditions", "alternatives_considered"),
                "product": ("non_goals", "acceptance_criteria"),
                "business": ("geographies", "segments", "pricing", "channels", "competitive_alternatives", "cost_drivers", "unit_economics_inputs", "success_metrics", "non_goals"),
            }.get(node_name, ())
            for field_name in array_details:
                if not isinstance(node.get(field_name), list):
                    errors.append(f"{prefix}.{field_name} must be an array")
                elif node_name != "need" and not node.get(field_name):
                    errors.append(f"{prefix} validated requires non-empty {field_name}")
            if node_name == "business":
                gate = node.get("gate")
                if not isinstance(gate, dict):
                    errors.append(f"{prefix}.gate must be an object")
                else:
                    for field_name in ("stage", "decision", "owner", "resource_commitment", "revisit_trigger"):
                        if _is_missing(gate.get(field_name)):
                            errors.append(f"{prefix}.gate requires {field_name}")
                for segment in node.get("segments", []):
                    if not isinstance(segment, dict):
                        errors.append(f"{prefix}.segments entries must be objects")
                        continue
                    for field_name in ("id", "criteria", "user_refs", "payer", "evidence_ids"):
                        if field_name not in segment or _is_missing(segment[field_name]):
                            errors.append(f"{prefix}.segments requires {field_name}")
                for price in node.get("pricing", []):
                    if not isinstance(price, dict):
                        errors.append(f"{prefix}.pricing entries must be objects")
                        continue
                    for field_name in ("model", "evidence_type", "evidence_ids"):
                        if field_name not in price or _is_missing(price[field_name]):
                            errors.append(f"{prefix}.pricing requires {field_name}")
                for input_item in node.get("unit_economics_inputs", []):
                    if not isinstance(input_item, dict):
                        errors.append(f"{prefix}.unit_economics_inputs entries must be objects")
                        continue
                    for field_name in ("metric", "status"):
                        if _is_missing(input_item.get(field_name)):
                            errors.append(f"{prefix}.unit_economics_inputs requires {field_name}")
                    if not _is_missing(input_item.get("value")) and (
                        _is_missing(input_item.get("unit")) or _is_missing(input_item.get("source_ref"))
                    ):
                        errors.append(f"{prefix}.unit_economics_inputs requires unit and source_ref when value is present")
                for metric in node.get("success_metrics", []):
                    if not isinstance(metric, dict):
                        errors.append(f"{prefix}.success_metrics entries must be objects")
                        continue
                    for field_name in ("metric_id", "definition", "denominator", "window", "guardrail"):
                        if _is_missing(metric.get(field_name)):
                            errors.append(f"{prefix}.success_metrics requires {field_name}")
                estimates = node.get("market_estimates", [])
                if not isinstance(estimates, list):
                    errors.append(f"{prefix}.market_estimates must be an array")
                else:
                    for estimate in estimates:
                        if not isinstance(estimate, dict):
                            errors.append(f"{prefix}.market_estimates entries must be objects")
                            continue
                        for field_name in ("metric", "population_definition", "time_window", "unit", "method", "assumptions"):
                            if field_name not in estimate or _is_missing(estimate[field_name]):
                                errors.append(f"{prefix}.market_estimates requires {field_name}")
                        if not _is_missing(estimate.get("value")):
                            if _is_missing(estimate.get("source_ref")):
                                errors.append(f"{prefix}.market_estimates with a value requires source_ref")
                            if _is_missing(estimate.get("formula")):
                                errors.append(f"{prefix}.market_estimates with a value requires formula")
            if design_only:
                continue
            accepted_levels = {
                "scene": LEVELS - {"E4-"},
                "user": LEVELS - {"E4-"},
                "pain": {"E1", "E2"},
                "need": {"E1", "E2"},
                "feature": {"E3"},
                "product": {"E3"},
                "business": {"E4+", "E5"},
            }[node_name]
            observed_levels = {
                str(evidence_by_id[str(value)].get("evidence_level"))
                for value in evidence_ids
                if str(value) in evidence_by_id
            }
            if not observed_levels.intersection(accepted_levels):
                errors.append(
                    f"{prefix} validated lacks direct evidence at {', '.join(sorted(accepted_levels))}; "
                    "a rationale is still required and is not proved by evidence volume"
                )

        counter_ids = chain.get("counter_evidence_ids") if isinstance(chain.get("counter_evidence_ids"), list) else []
        all_references.update(str(value) for value in counter_ids)
        context_key = str(chain.get("context_key") or "").strip()
        if (chain.get("status") == "decided" or any_validated_node or all_references) and not context_key:
            errors.append(f"{chain_id} evidence-backed or decided chains require context_key")
        if not design_only:
            unknown = sorted(value for value in all_references if value not in evidence_by_id)
            if unknown:
                errors.append(f"{chain_id} references unknown evidence: " + ", ".join(unknown))
            if context_key and (chain.get("status") == "decided" or any_validated_node):
                mismatched = sorted(
                    value for value in all_references
                    if value in evidence_by_id
                    and str(evidence_by_id[value].get("context_key") or "").strip() != context_key
                )
                if mismatched:
                    errors.append(f"{chain_id} has evidence from another context_key: " + ", ".join(mismatched))

            judgment_id = str(chain.get("demand_judgment_id") or "").strip()
            judgment = judgment_by_id.get(judgment_id)
            if judgment_id:
                linked_judgment_ids.append(judgment_id)
            if judgment is None:
                if judgment_id or all_references or chain.get("status") == "decided":
                    errors.append(f"{chain_id} must link an existing demand_judgment_id before citing evidence")
            else:
                if context_key and str(judgment.get("context_key") or "").strip() != context_key:
                    errors.append(f"{chain_id} and linked demand judgment have different context_key values")
                allowed_by_node = {
                    "scene": set(judgment.get("problem_evidence_ids", [])) | set(judgment.get("counter_evidence_ids", [])),
                    "user": set(judgment.get("problem_evidence_ids", [])) | set(judgment.get("counter_evidence_ids", [])),
                    "pain": set(judgment.get("problem_evidence_ids", [])) | set(judgment.get("counter_evidence_ids", [])),
                    "need": set(judgment.get("problem_evidence_ids", [])) | set(judgment.get("counter_evidence_ids", [])),
                    "feature": set(judgment.get("solution_evidence_ids", [])) | set(judgment.get("counter_evidence_ids", [])),
                    "product": set(judgment.get("solution_evidence_ids", []))
                    | set(judgment.get("commercial_evidence_ids", []))
                    | set(judgment.get("counter_evidence_ids", [])),
                    "business": set(judgment.get("commercial_evidence_ids", []))
                    | set(judgment.get("counter_evidence_ids", [])),
                }
                for node_name, references in node_references.items():
                    escaped = sorted(references - {str(value) for value in allowed_by_node[node_name]})
                    if escaped:
                        errors.append(
                            f"{chain_id}.{node_name} evidence is not registered in the linked demand judgment: "
                            + ", ".join(escaped)
                        )
                unregistered_counter = sorted(
                    {str(value) for value in counter_ids} - {str(value) for value in judgment.get("counter_evidence_ids", [])}
                )
                if unregistered_counter:
                    errors.append(f"{chain_id} counter-evidence is not registered in the demand judgment: " + ", ".join(unregistered_counter))
                if chain.get("status") == "decided" and judgment.get("status") != "validated":
                    errors.append(f"{chain_id} decided requires a validated linked demand judgment")

        if chain.get("status") == "decided":
            non_validated = [
                node_name for node_name in required_nodes
                if not isinstance(nodes.get(node_name), dict)
                or nodes[node_name].get("status") != "validated"
            ]
            if non_validated:
                errors.append(f"{chain_id} decided has non-validated nodes: " + ", ".join(non_validated))
            if not chain.get("alternative_explanations"):
                errors.append(f"{chain_id} decided requires at least one alternative explanation")
            if require_counter and not counter_ids:
                errors.append(f"{chain_id} decided lacks counter-evidence")

    if not design_only:
        duplicates = sorted({value for value in linked_judgment_ids if linked_judgment_ids.count(value) > 1})
        if duplicates:
            errors.append("demand judgments linked by more than one product chain: " + ", ".join(duplicates))
        if configured:
            missing_chains = sorted(set(judgment_by_id) - set(linked_judgment_ids))
            if missing_chains:
                errors.append("demand judgments missing a product chain: " + ", ".join(missing_chains))

    audit.add(
        "product_reasoning",
        "fail" if errors else "pass",
        "; ".join(errors)
        if errors
        else f"{len(chains)} product chain(s) make every node and inference rationale explicit",
        stage,
    )


def audit_study(root: Path, stage: str) -> Audit:
    root = root.resolve()
    audit = Audit(root, stage)
    paths = _study_paths(root)
    study = _check_design(audit, paths)
    if stage == "design":
        _check_product_reasoning(audit, paths, study, {}, [], design_only=True)
        return audit
    _, evidence_by_id = _check_evidence(audit, paths, study)
    if stage == "evidence":
        return audit
    judgments = _check_decisions(audit, paths, study, evidence_by_id)
    _check_product_reasoning(audit, paths, study, evidence_by_id, judgments)
    return audit


def _design_gate_failure(study_dir: Path) -> dict[str, Any] | None:
    audit = audit_study(study_dir, "design")
    if audit.status == "pass":
        return None
    return {
        "status": "design_gate_failed",
        "requested_stage": "design",
        "checks": [item.as_dict() for item in audit.findings],
        "next_step": "complete the design contract, then run: askovo check STUDY --stage design",
    }


def command_collect(args: argparse.Namespace) -> int:
    if not getattr(args, "dry_run", False):
        failure = _design_gate_failure(Path(args.study_dir).resolve())
        if failure is not None:
            print(json.dumps(failure, ensure_ascii=False, indent=2))
            return 1
    return sure_engine.cli_collect(args)


def command_queue_run(args: argparse.Namespace) -> int:
    failure = _design_gate_failure(Path(args.study_dir).resolve())
    if failure is not None:
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1
    return sure_engine.cli_queue_run(args)


def _write_report(audit: Audit) -> tuple[Path, Path]:
    paths = _study_paths(audit.study_dir)
    paths["audit_dir"].mkdir(parents=True, exist_ok=True)
    json_path = paths["audit_dir"] / "latest.json"
    md_path = paths["audit_dir"] / "latest.md"
    payload = audit.as_dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Askovo audit",
        "",
        f"- Status: **{audit.status}**",
        f"- Stage: `{audit.requested_stage}`",
        f"- Study: `{audit.study_dir}`",
        "",
        "## Checks",
        "",
        "| Stage | Check | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for finding in audit.findings:
        detail = finding.detail.replace("|", "\\|")
        lines.append(f"| {finding.stage} | `{finding.check_id}` | {finding.status} | {detail} |")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            payload["meaning"],
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _create_workspace(
    target: Path,
    study_id: str,
    title: str,
    decision: str,
    platforms: list[str],
) -> tuple[dict[str, Any], list[str]]:
    template = Path(__file__).resolve().parents[1] / "assets" / "study-template"
    if not template.is_dir():
        raise FileNotFoundError(f"study template not found: {template}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, target, dirs_exist_ok=True)
    connector_template_files = {
        template.parent / "collection-manifest-template.json": (
            target / "01-sources" / "collection-manifest-template.json"
        ),
        template.parent / "raw-connector-envelope-template.jsonl": (
            target / "02-data" / "raw" / "raw-connector-envelope-template.jsonl"
        ),
    }
    for source, destination in connector_template_files.items():
        if source.is_file():
            shutil.copyfile(source, destination)
    study_path = target / "study.json"
    study = _load_json(study_path)
    study["study_id"] = study_id
    study["title"] = title
    study["method_version"] = ASKOVO_VERSION
    study["decision"]["question"] = decision
    platform_templates: list[str] = []
    for platform in sorted(set(platforms)):
        source = template.parent / f"{platform}-route-template.csv"
        destination = target / "01-sources" / f"{platform}-routes.csv"
        shutil.copyfile(source, destination)
        platform_templates.append(str(destination))
        adapters = study.get("source_adapters", {})
        if isinstance(adapters, dict) and isinstance(adapters.get(platform), dict):
            adapters[platform]["enabled"] = True
    study_path.write_text(json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return study, platform_templates


def command_init(args: argparse.Namespace) -> int:
    target = Path(args.study_dir).resolve()
    if target.exists() and any(target.iterdir()):
        print(f"refusing to overwrite non-empty directory: {target}", file=sys.stderr)
        return 2
    try:
        _, platform_templates = _create_workspace(
            target, args.study_id, args.title, args.decision, list(args.platform)
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "created",
                "study_dir": str(target),
                "platform_templates": platform_templates,
                "connector_templates": [
                    str(target / "01-sources" / "collection-manifest-template.json"),
                    str(target / "02-data" / "raw" / "raw-connector-envelope-template.jsonl"),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# audit: gates + deterministic signals + claim-level verdicts


LEVEL_RANK = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4-": 4, "E4+": 5, "E5": 6}
CHAIN_RULES = (
    ("problem", "problem_evidence_ids", {"E1", "E2"}),
    ("solution", "solution_evidence_ids", {"E3"}),
    ("commercial", "commercial_evidence_ids", {"E4+", "E5"}),
)
AUDIT_BOUNDARY = (
    "审计检查产品推理是否断链、现有材料能支持到哪一级：不证明需求或产品成功，不估计总体比例，"
    "不把方案接受当发布就绪，不把观察行为当因果，也不替代人工语义复核与专业签收。"
)


def _load_evidence_by_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        records = _load_jsonl(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = str(record.get("record_id", ""))
        if record_id and str(record.get("evidence_level", "")) in LEVELS:
            evidence_by_id[record_id] = record
    return evidence_by_id


def _claim_verdicts(
    judgments: list[Any],
    evidence_by_id: dict[str, dict[str, Any]],
    require_counter: bool,
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, judgment in enumerate(judgments, start=1):
        if not isinstance(judgment, dict):
            continue
        claim_id = str(judgment.get("id") or index)
        status = str(judgment.get("status") or "")
        reasons: list[str] = []
        chains: dict[str, Any] = {}
        referenced: set[str] = set()

        for name, field, accepted in CHAIN_RULES:
            ids = [str(value) for value in (judgment.get(field) or []) if str(value)]
            referenced.update(ids)
            observed = sorted(
                {str(evidence_by_id[value]["evidence_level"]) for value in ids if value in evidence_by_id},
                key=lambda level: LEVEL_RANK.get(level, -1),
            )
            ok = bool(set(observed) & accepted)
            chains[name] = {"ok": ok, "levels": observed, "evidence_ids": ids}
            if not ok:
                reasons.append(f"缺 {name} 链（需要 {', '.join(sorted(accepted))}）")

        counter_ids = [
            str(value) for value in (judgment.get("counter_evidence_ids") or []) if str(value)
        ]
        referenced.update(counter_ids)
        if require_counter and not counter_ids:
            reasons.append("缺反证")

        unknown = sorted(value for value in referenced if value not in evidence_by_id)
        if unknown:
            reasons.append("引用不存在的证据：" + ", ".join(unknown))

        if status == "validated":
            context_key = str(judgment.get("context_key") or "").strip()
            if not context_key:
                reasons.append("validated 判断缺 context_key")
            else:
                mismatched = sorted(
                    value for value in referenced
                    if value in evidence_by_id
                    and str(evidence_by_id[value].get("context_key") or "").strip() != context_key
                )
                if mismatched:
                    reasons.append("证据 context_key 不一致：" + ", ".join(mismatched))

        all_levels = sorted(
            {str(evidence_by_id[value]["evidence_level"]) for value in referenced if value in evidence_by_id},
            key=lambda level: LEVEL_RANK.get(level, -1),
        )
        max_level = all_levels[-1] if all_levels else "none"

        if status == "validated":
            verdict = "supported" if not reasons else "exceeds_evidence"
        elif status == "rejected":
            verdict = "rejected"
        elif status == "deprioritized":
            verdict = "deprioritized"
        else:
            verdict = "open"

        claims.append(
            {
                "id": claim_id,
                "title": str(judgment.get("title") or ""),
                "claimed_status": status,
                "confidence": str(judgment.get("confidence") or ""),
                "verdict": verdict,
                "max_evidence_level": max_level,
                "chains": chains,
                "counter_evidence": len(counter_ids),
                "gaps": [str(value) for value in (judgment.get("gaps") or [])],
                "next_test": str(judgment.get("next_test") or ""),
                "reasons": reasons,
            }
        )
    return claims


def _audit_next_actions(payload: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for claim in payload["claims"]:
        if claim["verdict"] == "exceeds_evidence":
            actions.append(
                f"把 {claim['id']} 降级为 needs-validation，或补齐：" + "；".join(claim["reasons"])
            )
    failed = {item["id"]: item for item in payload["checks"] if item["status"] == "fail"}
    if "study_contract" in failed:
        actions.append("补全 study.json 的决策问题、假设、证伪条件与停止规则")
    for check_id in sorted(failed):
        if check_id.endswith("_source_design"):
            actions.append(f"补全 {check_id[:-14]} 的 data_rights_basis / retention_rule / terms_reviewed_at")
    if "evidence_records" in failed:
        actions.append("按产品推理节点的缺口补采，不要用无关数据量填补质量门槛")
    if "product_reasoning" in failed:
        detail = failed["product_reasoning"].get("detail", "")
        actions.append("修复产品推理链的节点、推导理由或证据关联：" + detail)
    if "demand_judgments" in failed and not payload["claims"]:
        actions.append("补写 04-findings/demand-judgments.json，并为每条判断挂上证据 id")
    if not payload["claims"]:
        actions.append("先写至少一条 demand judgment，再跑 audit")
    return actions[:8]


def _render_audit_md(payload: dict[str, Any]) -> str:
    verdict_zh = "可支持" if payload["status"] == "pass" else "不可支持（或超出证据）"
    lines = [
        "# Askovo 审计结论",
        "",
        f"- 研究：`{payload['study_id']}` — {payload['study_title']}",
        f"- 方法版本：`{payload['method_version']}`"
        + (f"（⚠ {payload['version_warning']}）" if payload.get("version_warning") else ""),
        f"- 审计时间：{payload['generated_at']}",
        f"- 结论：**{verdict_zh}**",
        "",
    ]
    if payload.get("decision_question"):
        lines.extend(["## 要回答的决定", "", payload["decision_question"], ""])

    reasoning = payload.get("product_reasoning") or {}
    lines.extend(["## 产品推理主链", ""])
    if reasoning.get("chains"):
        lines.append(
            f"- 推理链：{reasoning.get('chains', 0)} 条；已形成产品决策：{reasoning.get('decided', reasoning.get('validated', 0))} 条"
        )
        supporting = reasoning.get("supporting_states", {})
        if supporting:
            lines.append("- 独立支撑状态：" + json.dumps(supporting, ensure_ascii=False))
        lines.append("")
        lines.append("| 节点 | 已填节点 | 证据支持节点 | 有证据引用 |")
        lines.append("| --- | --- | --- | --- |")
        for node in sure_engine.REASONING_NODES:
            item = reasoning.get("nodes", {}).get(node, {})
            lines.append(
                f"| {sure_engine.REASONING_NODE_LABELS[node]} | {item.get('total', 0)} | "
                f"{item.get('validated', 0)} | {item.get('with_evidence', 0)} |"
            )
        lines.append("- 注意：节点有证据不等于推导成立；每条 incoming rationale 与假设仍需人工审查。")
    else:
        lines.append("尚未建立产品推理链；当前结果只是旧版需求证据审计。")
    lines.append("")

    summary = payload["summary"]
    lines.extend(
        [
            "## 材料概况",
            "",
            f"- 证据记录：{summary['records']} 条",
            f"- 重复率：{summary['duplicate_rate']:.1%}",
            f"- 主导来源占比：{summary['dominant_source_share']:.1%}",
            f"- 判断：{summary['claims']} 条（可支持 {summary['supported']}、"
            f"超出证据 {summary['overclaims']}、未定 {summary['open']}）",
            "",
            "## 判断与证据",
            "",
        ]
    )
    if payload["claims"]:
        lines.append("| 判断 | 声称状态 | 最高证据 | 问题链 | 方案链 | 商业链 | 结论 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        verdict_label = {
            "supported": "可支持",
            "exceeds_evidence": "**超出证据**",
            "open": "未定",
            "rejected": "已否决",
            "deprioritized": "降级",
        }
        for claim in payload["claims"]:
            chains = claim["chains"]
            tick = lambda key: "✓" if chains[key]["ok"] else "✗"
            lines.append(
                f"| {claim['id']} {claim['title']} | {claim['claimed_status']} | "
                f"{claim['max_evidence_level']} | {tick('problem')} | {tick('solution')} | "
                f"{tick('commercial')} | {verdict_label.get(claim['verdict'], claim['verdict'])} |"
            )
    else:
        lines.append("尚无 demand judgment。")
    lines.append("")

    lines.extend(["## 缺口与下一步", ""])
    actions = payload.get("next_actions") or []
    if actions:
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("- 未发现需要阻断的缺口；继续补采或进入写作。")
    lines.extend(["", "## 边界", "", payload["meaning"], ""])
    return "\n".join(lines)


def command_demo(args: argparse.Namespace) -> int:
    """Run the bundled synthetic sample in a temporary directory."""
    source = next(
        (
            candidate for candidate in (
                Path(__file__).resolve().parents[3] / "examples" / "sample-study",
                Path(__file__).resolve().parents[1] / "examples" / "sample-study",
            )
            if candidate.is_dir()
        ),
        None,
    )
    if source is None:
        print("bundled sample not found in this installation", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "sample-study"
        shutil.copytree(source, target)
        return command_audit(
            argparse.Namespace(study_dir=str(target), claim=None, json=False)
        )


def command_audit(args: argparse.Namespace) -> int:
    root = Path(args.study_dir).resolve()
    study_path = root / "study.json"
    if not study_path.is_file():
        print(f"missing study.json under {root}", file=sys.stderr)
        return 2
    try:
        study = _load_json(study_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot parse study.json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(study, dict):
        print("study.json must contain an object", file=sys.stderr)
        return 2

    audit = audit_study(root, "full")
    paths = _study_paths(root)
    try:
        signals = _compute_signals(root, study)
    except (OSError, json.JSONDecodeError, ValueError):
        signals = {}
    evidence_by_id = _load_evidence_by_id(paths["evidence"])

    judgments: list[Any] = []
    if paths["judgments"].is_file():
        try:
            loaded = _load_json(paths["judgments"])
            if isinstance(loaded, list):
                judgments = loaded
        except (OSError, json.JSONDecodeError):
            judgments = []
    gates = study.get("quality_gates")
    if not isinstance(gates, dict):
        gates = {}
    require_counter = bool(gates.get("require_counter_evidence_for_validated", True))
    claims = _claim_verdicts(judgments, evidence_by_id, require_counter)

    focus = str(getattr(args, "claim", "") or "").strip()
    if focus:
        needle = focus.casefold()
        claims = [
            claim
            for claim in claims
            if needle in " ".join(
                [claim["id"], claim["title"], claim["claimed_status"]]
            ).casefold()
        ]
        if not claims:
            print(f"no claim matched {focus!r}", file=sys.stderr)
            return 2

    overclaims = [claim for claim in claims if claim["verdict"] == "exceeds_evidence"]
    status = "pass" if audit.status == "pass" and not overclaims else "fail"
    reasoning_summary = audit.metrics.get("product_reasoning", {})
    summary = {
        "records": int(signals.get("record_count", 0) or 0),
        "duplicate_rate": float(signals.get("normalized_duplicate_rate", 0.0) or 0.0),
        "dominant_source_share": float(signals.get("dominant_source_family_share", 0.0) or 0.0),
        "claims": len(claims),
        "supported": sum(1 for claim in claims if claim["verdict"] == "supported"),
        "overclaims": len(overclaims),
        "open": sum(1 for claim in claims if claim["verdict"] == "open"),
        "product_chains": int(reasoning_summary.get("chains", 0) or 0),
        "decided_product_chains": int(reasoning_summary.get("decided", 0) or 0),
    }
    payload: dict[str, Any] = {
        "status": status,
        "study_id": str(study.get("study_id", "")),
        "study_title": str(study.get("title", "")),
        "method_version": str(study.get("method_version") or ASKOVO_VERSION),
        "version_warning": (
            None
            if str(study.get("method_version") or ASKOVO_VERSION) == ASKOVO_VERSION
            else f"study records {study.get('method_version') or 'unknown'}; current runtime is {ASKOVO_VERSION}"
        ),
        "decision_question": str(
            (study.get("decision") if isinstance(study.get("decision"), dict) else {}).get(
                "question", ""
            )
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": [item.as_dict() for item in audit.findings],
        "signals": signals,
        "claims": claims,
        "product_reasoning": reasoning_summary,
        "summary": summary,
        "meaning": AUDIT_BOUNDARY,
    }
    payload["next_actions"] = _audit_next_actions(payload)

    paths["audit_dir"].mkdir(parents=True, exist_ok=True)
    json_path = paths["audit_dir"] / "audit.json"
    md_path = paths["audit_dir"] / "audit.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_audit_md(payload), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Askovo 审计：{payload['study_id']} — {payload['status']}")
        if payload.get("version_warning"):
            print(f"- 版本警告：{payload['version_warning']}")
        print(
            f"- 记录 {summary['records']} 条；重复率 {summary['duplicate_rate']:.1%}；"
            f"主导来源 {summary['dominant_source_share']:.1%}"
        )
        print(
            f"- 判断 {summary['claims']} 条：可支持 {summary['supported']}、"
            f"超出证据 {summary['overclaims']}、未定 {summary['open']}"
        )
        for action in payload["next_actions"][:3]:
            print(f"- 下一步：{action}")
        print(f"- 报告：{md_path}")
    return 0 if status == "pass" else 1


def command_check(args: argparse.Namespace) -> int:
    audit = audit_study(Path(args.study_dir), args.stage)
    payload = audit.as_dict()
    if args.write_report:
        json_path, md_path = _write_report(audit)
        payload["report_files"] = [str(json_path), str(md_path)]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if audit.status == "pass" else 1


def command_connectors(args: argparse.Namespace) -> int:
    try:
        registry = _load_connector_registry()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"cannot load connector registry: {exc}", file=sys.stderr)
        return 2
    connectors = [item for item in registry["connectors"] if isinstance(item, dict)]
    if args.platform:
        connectors = [item for item in connectors if item.get("platform") == args.platform]
    if not args.include_blocked:
        connectors = [item for item in connectors if item.get("decision") != "blocked"]
    connectors.sort(key=lambda item: (str(item.get("platform")), str(item.get("id"))))
    print(
        json.dumps(
            {
                "schema_version": registry.get("schema_version"),
                "reviewed_at": registry.get("reviewed_at"),
                "platform": args.platform,
                "include_blocked": args.include_blocked,
                "count": len(connectors),
                "connectors": connectors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


HISTORICAL_DEFAULT_WINDOW = ("2021-10-01", "2023-09-30")


def _allocate_platform_shares(
    platform_types: dict[str, str]
) -> tuple[dict[str, float], list[str]]:
    """Share sample volume across enabled platforms by platform-type weight.

    Applies an iterative cap so one platform stays under PLAN_MAX_PLATFORM_SHARE
    when at least two platforms are enabled; a lone platform takes everything and
    the caller records a single-family warning.
    """
    warnings: list[str] = []
    if not platform_types:
        return {}, warnings
    if len(platform_types) == 1:
        platform = next(iter(platform_types))
        warnings.append(
            f"{platform} is the only enabled platform; the study cannot pass "
            f"max_source_family_share={PLAN_MAX_PLATFORM_SHARE} without a second source family"
        )
        return {platform: 1.0}, warnings

    raw = {
        platform: PLAN_TYPE_WEIGHTS.get(platform_type, 0.1)
        for platform, platform_type in platform_types.items()
    }
    total = sum(raw.values())
    shares = {platform: value / total for platform, value in raw.items()}
    for _ in range(len(shares)):
        over = {p for p, s in shares.items() if s > PLAN_MAX_PLATFORM_SHARE}
        if not over:
            break
        for platform in over:
            shares[platform] = PLAN_MAX_PLATFORM_SHARE
        remainder = 1.0 - PLAN_MAX_PLATFORM_SHARE * len(over)
        under = {p: raw[p] for p in shares if p not in over}
        under_total = sum(under.values())
        if under_total <= 0:
            break
        for platform, value in under.items():
            shares[platform] = remainder * value / under_total
    return shares, warnings


def _allocate_whole_targets(weights: list[float], total: int) -> list[int]:
    """Allocate an exact total with one record minimum per positive route."""
    if not weights:
        return []
    if total < len(weights):
        raise ValueError(f"target {total} cannot cover {len(weights)} routes with a minimum of 1 each")
    safe_weights = [max(0.0, float(weight)) for weight in weights]
    weight_total = sum(safe_weights)
    if weight_total <= 0:
        safe_weights = [1.0] * len(weights)
        weight_total = float(len(weights))
    remaining = total - len(weights)
    raw_additions = [remaining * weight / weight_total for weight in safe_weights]
    allocated = [1 + int(addition) for addition in raw_additions]
    leftover = total - sum(allocated)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(raw_additions[index] - int(raw_additions[index])), index),
    )
    for index in order[:leftover]:
        allocated[index] += 1
    return allocated


def _scale_route_targets(routes_csv: Path, quota: int) -> None:
    if not routes_csv.is_file():
        return
    with routes_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        return
    current_targets: list[int] = []
    for row in rows:
        try:
            current_targets.append(int(row.get("target_records", "0")))
        except (TypeError, ValueError):
            current_targets.append(0)
    if sum(current_targets) <= 0:
        return
    scaled = _allocate_whole_targets([float(value) for value in current_targets], quota)
    for row, value in zip(rows, scaled):
        row["target_records"] = str(value)
    with routes_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_planned_source_plan(
    source_plan_csv: Path, platform_quotas: dict[str, int]
) -> None:
    fieldnames = [
        "corpus_role",
        "source_family",
        "route_or_query",
        "target_records",
        "cap_share",
        "access_status",
        "known_bias",
        "reasoning_nodes",
    ]
    reasoning_targets = {
        "direct_solution": "feature;product",
        "open_scene": "scene;user;pain;need",
        "substitute_rejector": "pain;need;feature",
        "post_purchase_support": "feature;product",
        "control": "scene;user;pain",
    }
    rows = []
    for platform in sorted(platform_quotas):
        quota = platform_quotas[platform]
        role_targets = dict(zip(
            PLAN_ROLE_WEIGHTS,
            _allocate_whole_targets(list(PLAN_ROLE_WEIGHTS.values()), quota),
        ))
        for role, target in role_targets.items():
            rows.append(
                {
                    "corpus_role": role,
                    "source_family": platform,
                    "route_or_query": f"see 01-sources/{platform}-routes.csv",
                    "target_records": str(target),
                    "cap_share": "0.40",
                    "access_status": "planned",
                    "known_bias": PLAN_PLATFORM_BIAS.get(platform, ""),
                    "reasoning_nodes": reasoning_targets[role],
                }
            )
    with source_plan_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _platform_prerequisites(connector: dict[str, Any]) -> list[str]:
    items = [str(value) for value in connector.get("limits", [])]
    watch = connector.get("policy_watch")
    if isinstance(watch, dict) and watch.get("action_required"):
        items.append(f"policy watch ({watch.get('recheck_by', 'n/a')}): {watch['action_required']}")
    return items


def command_plan(args: argparse.Namespace) -> int:
    target = Path(args.study_dir).resolve()
    args.mode = str(getattr(args, "mode", "standard") or "standard").replace("-", "_")
    if target.exists() and any(target.iterdir()):
        print(f"refusing to overwrite non-empty directory: {target}", file=sys.stderr)
        return 2
    try:
        platform_map = _load_platform_map()
        registry = _connector_index()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    requested_types: list[str] = []
    for token in args.platform_types.split(","):
        token = token.strip().lower()
        if token and token not in requested_types:
            requested_types.append(token)
    invalid_types = [t for t in requested_types if t not in platform_map["platform_types"]]
    if invalid_types:
        print(
            "unknown platform types: "
            + ", ".join(invalid_types)
            + "; valid types: "
            + ", ".join(sorted(platform_map["platform_types"])),
            file=sys.stderr,
        )
        return 2
    if args.sample_size < 1:
        print("--sample-size must be a positive integer", file=sys.stderr)
        return 2

    region_entry = platform_map["regions"].get(args.region, {})
    candidates: list[tuple[str, str]] = []
    for platform_type in requested_types:
        for platform in region_entry.get("platforms_by_type", {}).get(platform_type, []):
            candidates.append((platform_type, platform))

    resolved: list[dict[str, Any]] = []
    for platform_type, platform in candidates:
        entry: dict[str, Any] = {
            "platform": platform,
            "platform_type": platform_type,
            "status": "unavailable",
            "reason": "",
            "quota": 0,
        }
        meta = platform_map["platforms"].get(platform)
        connector_id = str(meta.get("connector_id") or "") if isinstance(meta, dict) else ""
        if not connector_id:
            entry["status"] = "no_reviewed_connector"
            entry["reason"] = (
                str(meta.get("status_note", "no reviewed connector"))
                if isinstance(meta, dict)
                else "platform missing from platform map"
            )
            resolved.append(entry)
            continue
        connector = registry.get(connector_id)
        if connector is None:
            entry["status"] = "missing_from_registry"
            entry["reason"] = f"connector {connector_id} is not in the reviewed registry"
            resolved.append(entry)
            continue
        decision = str(connector.get("decision", ""))
        entry["connector_id"] = connector_id
        entry["connector_revision"] = str(connector.get("reviewed_revision", ""))
        entry["connector_license"] = str(connector.get("license", ""))
        entry["registry_decision"] = decision
        if decision in {"supported", "historical_only"} and sure_engine.connector_review_expired(connector):
            entry["status"] = "review_expired"
            entry["reason"] = str(connector.get("policy_watch", {}).get("recheck_by") or "policy review expired")
        elif decision in {"supported", "historical_only"}:
            entry["status"] = "enabled"
            entry["quota"] = 0
            entry["prerequisites"] = _platform_prerequisites(connector)
            if decision == "historical_only":
                entry["constraints"] = [
                    f"historical data only: {', '.join(map(str, connector.get('usable_scope', [])))}"
                ]
        else:
            entry["status"] = "blocked"
            entry["reason"] = "; ".join(str(v) for v in connector.get("limits", [])) or (
                "registry decision is blocked"
            )
        resolved.append(entry)

    enabled = [item for item in resolved if item["status"] == "enabled"]
    unavailable = [item for item in resolved if item["status"] != "enabled"]

    shares, share_warnings = _allocate_platform_shares(
        {item["platform"]: item["platform_type"] for item in enabled}
    )
    try:
        allocated = _allocate_whole_targets(list(shares.values()), args.sample_size)
    except ValueError as exc:
        print(f"--sample-size is too small for the enabled platforms: {exc}", file=sys.stderr)
        return 2
    platform_quotas = dict(zip(shares, allocated))
    for item in enabled:
        item["quota"] = platform_quotas.get(item["platform"], 0)

    # Validate every quota against its role/route minimums before creating files.
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    for item in enabled:
        template = assets_dir / f"{item['platform']}-route-template.csv"
        try:
            with template.open(encoding="utf-8-sig", newline="") as handle:
                route_count = sum(1 for _ in csv.DictReader(handle))
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        minimum = max(len(PLAN_ROLE_WEIGHTS), route_count)
        if item["quota"] < minimum:
            print(
                f"--sample-size gives {item['platform']} quota {item['quota']}, "
                f"but its {minimum} planned roles/routes need at least {minimum}; "
                "increase the sample or reduce platform types",
                file=sys.stderr,
            )
            return 2

    all_historical = bool(enabled) and all(
        item.get("registry_decision") == "historical_only" for item in enabled
    )
    if args.time_window:
        parts = args.time_window.split(":")
        try:
            if len(parts) != 2:
                raise ValueError("two dates required")
            start = datetime.strptime(parts[0], "%Y-%m-%d").date()
            end = datetime.strptime(parts[1], "%Y-%m-%d").date()
            if start > end:
                raise ValueError("start is after end")
        except ValueError as exc:
            print(f"--time-window must be YYYY-MM-DD:YYYY-MM-DD with start <= end: {exc}", file=sys.stderr)
            return 2
        window = {"start": parts[0], "end": parts[1]}
    elif all_historical:
        window = {"start": HISTORICAL_DEFAULT_WINDOW[0], "end": HISTORICAL_DEFAULT_WINDOW[1]}
    else:
        today = datetime.now(timezone.utc).date()
        window = {
            "start": (today - timedelta(days=365)).isoformat(),
            "end": today.isoformat(),
        }

    study_id = args.study_id or (
        "study-"
        + datetime.now(timezone.utc).strftime("%Y%m%d")
        + "-"
        + hashlib.sha1(
            f"{args.goal}|{args.region}|{args.platform_types}".encode("utf-8")
        ).hexdigest()[:6]
    )
    title = args.title or args.goal
    decision_question = args.decision or f"待填写：围绕「{args.goal}」明确一个要改变的具体产品决定"
    try:
        study, _ = _create_workspace(
            target, study_id, title, decision_question, [item["platform"] for item in enabled]
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    languages = args.languages.split(",") if args.languages else (["zh"] if args.region == "cn" else ["en"])
    scope = study.get("scope", {})
    scope["markets"] = [args.region] + ([args.market] if args.market else [])
    scope["languages"] = [lang.strip() for lang in languages if lang.strip()]
    scope["source_time_window"] = window
    scope["allowed_sources"] = [item["platform"] for item in enabled]
    study["scope"] = scope
    gates = study.get("quality_gates", {})
    gates["min_evidence_records"] = max(30, round(args.sample_size * 0.01))
    study["quality_gates"] = gates
    study["plan"] = {
        "mode": args.mode,
        "goal": args.goal,
        "region": args.region,
        "market": args.market,
        "sample_target": args.sample_size,
        "raw_target_estimate": args.sample_size * 4,
        "platform_types": requested_types,
        "planned_at": datetime.now(timezone.utc).isoformat(),
        "platform_quotas": platform_quotas,
        "feasible_platforms": [item["platform"] for item in enabled],
        "unavailable_platforms": [
            {"platform": item["platform"], "status": item["status"], "reason": item["reason"]}
            for item in unavailable
        ],
        "notes": [
            "region and market are sampling context, not verified residence",
            "sample target is a collection ceiling, not a claim of independent users",
            "raw intake estimate assumes a 3-5x reduction from date, completeness, "
            "relevance, and dedup filters before records become claim eligible",
        ],
    }
    (target / "study.json").write_text(
        json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for item in enabled:
        routes_csv = target / "01-sources" / f"{item['platform']}-routes.csv"
        _scale_route_targets(routes_csv, item["quota"])
    _write_planned_source_plan(target / "01-sources" / "source-plan.csv", platform_quotas)
    if args.mode == "unnamed_experience":
        for template_name, destination_name in (
            ("lexicon-template.csv", "lexicon.csv"),
            ("experience-space-template.csv", "experience-space.csv"),
        ):
            source = Path(__file__).resolve().parents[1] / "assets" / template_name
            if source.is_file():
                shutil.copyfile(source, target / "01-sources" / destination_name)

    feasibility = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "goal": args.goal,
        "region": args.region,
        "market": args.market,
        "requested_platform_types": requested_types,
        "sample_target": args.sample_size,
        "platforms": resolved,
        "warnings": share_warnings
        + (
            ["sample target below 1000 is pilot scale; conclusions stay exploratory"]
            if args.sample_size < 1000
            else []
        )
        + (
            [
                "historical-only connectors are enabled; every conclusion is bounded by "
                f"the dataset period ending {window['end']}"
            ]
            if all_historical
            else []
        ),
        "meaning": (
            "Feasibility reflects registry decisions only. Each enabled platform still needs "
            "study-specific access, policy, and data-rights review before collection."
        ),
    }
    (target / "01-sources" / "feasibility.json").write_text(
        json.dumps(feasibility, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    tasks_lines = [
        "# Collection tasks",
        "",
        f"Study: `{study_id}` — {args.goal}",
        "",
        f"- Region: `{args.region}`" + (f" (market: `{args.market}`)" if args.market else ""),
        f"- Sample target: {args.sample_size}",
        f"- Feasible platforms: {', '.join(item['platform'] for item in enabled) or 'none'}",
        "",
    ]
    if args.mode == "unnamed_experience":
        tasks_lines.extend(
            [
                "## Phase 0 grounding (before route design)",
                "",
                "The studied experience has no settled name yet. Derive the scope and seed lexicon before writing queries:",
                "",
                "1. Edge-language mining: harvest proto-words from open-scene material; record each in `01-sources/lexicon.csv`.",
                "2. Substitute-behavior archaeology: document DIY/appropriation behaviors and their costs (demand fossils, E2).",
                "3. Psychophysical dimension mapping: fill `01-sources/experience-space.csv` with stimulus dimensions and coverage marks.",
                "4. Cross-domain analogy + literature anchors: record anchor claims with explicit bridges; E0 context only.",
                "5. First-principles derivation: terminate every chain in observable behaviors or expressions.",
                "",
                "Gate: lexicon.csv needs at least 5 retained terms across at least 2 grounding paths; experience-space.csv is required when the psychophysical path is used. Downstream route queries must derive from the retained lexicon and uncovered dimensions. Method details: `references/unnamed-experience-research.md`.",
                "",
            ]
        )
    for item in enabled:
        tasks_lines.extend(
            [
                f"## {item['platform']} ({item['platform_type']}) — target {item['quota']} records",
                "",
                f"- Connector: `{item['connector_id']}` @ `{item['connector_revision']}` "
                f"({item['connector_license']}, registry decision `{item['registry_decision']}`)",
            ]
        )
        for constraint in item.get("constraints", []):
            tasks_lines.append(f"- Constraint: {constraint}")
        for prerequisite in item.get("prerequisites", []):
            tasks_lines.append(f"- Prerequisite: {prerequisite}")
        tasks_lines.extend(
            [
                f"- Steps: fill `01-sources/{item['platform']}-routes.csv` queries → complete the "
                f"`source_adapters.{item['platform']}` review fields in `study.json` → pilot the "
                "routes → write a collection manifest per run → scale only routes that yield "
                "their assigned evidence role",
                "- Manifest: copy `01-sources/collection-manifest-template.json` into "
                "`01-sources/manifests/` and complete it for every run",
                "",
            ]
        )
    if unavailable:
        tasks_lines.extend(["## Unavailable routes (do not enable)", ""])
        for item in unavailable:
            tasks_lines.append(
                f"- {item['platform']} ({item['platform_type']}): `{item['status']}` — {item['reason']}"
            )
        tasks_lines.append("")
    tasks_lines.extend(
        [
            "## Design gate before any collection",
            "",
            "1. Complete `decision` (owner, deadline, options, minimum evidence), `hypotheses`, "
            "`stopping_rules`, and `restart_rules` in `study.json`.",
            "2. Run `python3 scripts/askovo.py check STUDY --stage design --write-report`.",
            "3. Do not collect when a platform has no enabled connector; record the gap instead.",
            "",
        ]
    )
    (target / "01-sources" / "tasks.md").write_text("\n".join(tasks_lines), encoding="utf-8")

    summary = {
        "status": "planned" if enabled else "planned_without_feasible_platforms",
        "mode": args.mode,
        "study_dir": str(target),
        "study_id": study_id,
        "goal": args.goal,
        "region": args.region,
        "sample_target": args.sample_size,
        "feasible_platforms": [item["platform"] for item in enabled],
        "platform_quotas": platform_quotas,
        "unavailable_platforms": [
            {"platform": item["platform"], "status": item["status"]} for item in unavailable
        ],
        "warnings": feasibility["warnings"],
        "next_step": "fill the design contract, then run: askovo.py check STUDY --stage design --write-report",
        "feasibility_report": str(target / "01-sources" / "feasibility.json"),
        "task_list": str(target / "01-sources" / "tasks.md"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if enabled else 3


def _compute_signals(root: Path, study: dict[str, Any] | None) -> dict[str, Any]:
    evidence_path = root / "02-data" / "evidence.jsonl"
    records = _load_jsonl(evidence_path) if evidence_path.is_file() else []
    total = len(records)
    record_ids = [str(record.get("record_id", "")) for record in records]
    level_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    role_level: dict[str, Counter[str]] = {}
    family_counts: Counter[str] = Counter()
    source_refs: set[str] = set()
    hash_counts: Counter[str] = Counter()
    dates: list[str] = []
    month_counts: Counter[str] = Counter()
    for record in records:
        level = str(record.get("evidence_level", "unknown"))
        role = str(record.get("corpus_role", "unknown"))
        family = str(record.get("source_family", "unknown")).strip().lower() or "unknown"
        level_counts[level] += 1
        role_counts[role] += 1
        role_level.setdefault(role, Counter())[level] += 1
        family_counts[family] += 1
        source_ref = str(record.get("source_ref", ""))
        if source_ref:
            source_refs.add(source_ref)
        text_hash = str(record.get("normalized_text_hash", ""))
        if text_hash:
            hash_counts[text_hash] += 1
        day = _source_day(record.get("created_at", ""))
        if len(day) == 10 and day[:4].isdigit():
            dates.append(day)
            month_counts[day[:7]] += 1

    duplicate_records = sum(count - 1 for count in hash_counts.values() if count > 1)
    duplicate_rate = (duplicate_records / total) if total else 0.0
    dominant_family, dominant_family_count = (
        (family_counts.most_common(1)[0] if family_counts else ("", 0))
    )
    dominant_family_share = (dominant_family_count / total) if total else 0.0
    top_month, top_month_count = (month_counts.most_common(1)[0] if month_counts else ("", 0))

    problem_records = sum(level_counts[level] for level in ("E1", "E2"))
    solution_records = level_counts.get("E3", 0)
    commercial_records = sum(level_counts[level] for level in ("E4+", "E5"))
    counter_records = level_counts.get("E4-", 0)

    gates = (study or {}).get("quality_gates", {})
    gate_report: dict[str, Any] = {}
    try:
        required_min = int(gates.get("min_evidence_records", 0))
    except (TypeError, ValueError):
        required_min = 0
    gate_report["min_evidence_records"] = {
        "required": required_min,
        "observed": total,
        "status": "pass" if total >= required_min else "fail",
    }
    try:
        max_family_share = float(gates.get("max_source_family_share", 1.0))
    except (TypeError, ValueError):
        max_family_share = 1.0
    gate_report["max_source_family_share"] = {
        "limit": max_family_share,
        "observed": round(dominant_family_share, 6),
        "status": "pass" if dominant_family_share <= max_family_share else "fail",
    }
    try:
        max_duplicate_rate = float(gates.get("max_normalized_duplicate_rate", 1.0))
    except (TypeError, ValueError):
        max_duplicate_rate = 1.0
    gate_report["max_normalized_duplicate_rate"] = {
        "limit": max_duplicate_rate,
        "observed": round(duplicate_rate, 6),
        "status": "pass" if duplicate_rate <= max_duplicate_rate else "fail",
    }
    required_roles = [str(role) for role in gates.get("required_corpus_roles", [])]
    gate_report["required_corpus_roles"] = {
        role: {
            "required": True,
            "observed": role_counts.get(role, 0),
            "status": "pass" if role_counts.get(role, 0) > 0 else "fail",
        }
        for role in required_roles
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": total,
        "unique_record_ids": len(set(record_ids)),
        "normalized_duplicate_records": duplicate_records,
        "normalized_duplicate_rate": round(duplicate_rate, 6),
        "evidence_levels": dict(sorted(level_counts.items())),
        "corpus_roles": dict(sorted(role_counts.items())),
        "role_level_matrix": {
            role: dict(sorted(counter.items())) for role, counter in sorted(role_level.items())
        },
        "source_families": dict(sorted(family_counts.items())),
        "dominant_source_family": dominant_family,
        "dominant_source_family_share": round(dominant_family_share, 6),
        "unique_source_refs": len(source_refs),
        "time_range": {
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None,
            "span_days": (
                (
                    datetime.fromisoformat(max(dates)) - datetime.fromisoformat(min(dates))
                ).days
                if dates
                else None
            ),
            "top_month": top_month or None,
            "top_month_share": round(top_month_count / len(dates), 6) if dates else None,
        },
        "chain_readiness": {
            "problem_E1_E2": problem_records,
            "solution_E3": solution_records,
            "commercial_E4p_E5": commercial_records,
            "counter_E4m": counter_records,
        },
        "gates": gate_report,
        "meaning": (
            "Deterministic corpus signals only. They do not extract scenes, quantify demand, "
            "or replace evidence coding and demand judgments."
        ),
    }


def command_signals(args: argparse.Namespace) -> int:
    root = Path(args.study_dir).resolve()
    study_path = root / "study.json"
    study = None
    if study_path.is_file():
        try:
            study = _load_json(study_path)
        except (OSError, json.JSONDecodeError):
            study = None
    try:
        signals = _compute_signals(root, study if isinstance(study, dict) else None)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"cannot compute signals: {exc}", file=sys.stderr)
        return 2
    output = root / "04-findings" / "signals.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(signals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = dict(signals)
    payload["signals_file"] = str(output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_lexicon(args: argparse.Namespace) -> int:
    root = Path(args.study_dir).resolve()
    lexicon_path = root / "01-sources" / "lexicon.csv"
    if not lexicon_path.is_file():
        print(
            f"missing {lexicon_path}; run plan --mode unnamed-experience and ground the lexicon first",
            file=sys.stderr,
        )
        return 2
    with lexicon_path.open(encoding="utf-8-sig", newline="") as handle:
        lexicon_rows = list(csv.DictReader(handle))
    valid_rows = [
        row
        for row in lexicon_rows
        if str(row.get("term", "")).strip() and str(row.get("grounding_path", "")).strip()
    ]

    evidence_path = root / "02-data" / "evidence.jsonl"
    records: list[dict[str, Any]] = []
    if evidence_path.is_file():
        try:
            records = _load_jsonl(evidence_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"cannot read evidence corpus: {exc}", file=sys.stderr)
            return 2

    term_stats: dict[str, dict[str, Any]] = {}
    path_counts: Counter[str] = Counter()
    path_level_counts: dict[str, Counter[str]] = {}
    for row in valid_rows:
        term = str(row["term"]).strip()
        path = str(row["grounding_path"]).strip()
        term_stats[term] = {
            "grounding_path": path,
            "term_type": str(row.get("term_type", "")).strip(),
            "status": str(row.get("status", "candidate")).strip() or "candidate",
            "records": 0,
            "levels": {},
            "corpus_roles": {},
            "acceptance_share": None,
        }
    for record in records:
        record_path = str(record.get("grounding_path", "")).strip()
        if record_path:
            path_counts[record_path] += 1
            path_level_counts.setdefault(record_path, Counter())[
                str(record.get("evidence_level", "unknown"))
            ] += 1
        terms = record.get("lexicon_terms", [])
        if not isinstance(terms, list):
            continue
        level = str(record.get("evidence_level", "unknown"))
        role = str(record.get("corpus_role", "unknown"))
        for raw_term in terms:
            term = str(raw_term).strip()
            if term not in term_stats:
                continue
            stats = term_stats[term]
            stats["records"] += 1
            levels = stats["levels"]
            levels[level] = str(int(levels.get(level, 0)) + 1)
            roles = stats["corpus_roles"]
            roles[role] = str(int(roles.get(role, 0)) + 1)
    for term, stats in term_stats.items():
        if stats["records"]:
            positive = sum(
                int(count) for level, count in stats["levels"].items() if level in {"E3", "E4+", "E5"}
            )
            stats["acceptance_share"] = round(positive / stats["records"], 6)
        stats["levels"] = dict(sorted(stats["levels"].items()))
        stats["corpus_roles"] = dict(sorted(stats["corpus_roles"].items()))

    zero_yield = sorted(
        term for term, stats in term_stats.items() if stats["records"] == 0
    )
    insufficient_terms: list[str] = []
    if args.min_per_term is not None:
        insufficient_terms = sorted(
            term
            for term, stats in term_stats.items()
            if stats["records"] < args.min_per_term
        )
    sufficiency = {
        "min_per_term": args.min_per_term,
        "status": (
            "not_evaluated"
            if args.min_per_term is None
            else ("sufficient" if not insufficient_terms else "insufficient")
        ),
        "insufficient_terms": insufficient_terms,
        "meaning": (
            "Sufficiency compares graded corpus yield per lexicon term against the "
            "configured minimum. Insufficiency means collect through the planned "
            "routes; it never means loosen the gate or substitute a blocked connector."
        ),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lexicon_terms": len(valid_rows),
        "evidence_records": len(records),
        "terms": term_stats,
        "grounding_path_yield": {
            path: {
                "lexicon_terms": sum(
                    1 for row in valid_rows if str(row["grounding_path"]).strip() == path
                ),
                "evidence_records": path_counts.get(path, 0),
                "levels": dict(sorted(path_level_counts.get(path, Counter()).items())),
            }
            for path in sorted(GROUNDING_PATHS)
        },
        "demand_fossil_records": path_counts.get("substitute_behavior", 0),
        "zero_yield_terms": zero_yield,
        "sufficiency": sufficiency,
        "claim_boundary": (
            "Proto-word clusters are E1 discovery signals; substitute behaviors are E2 "
            "demand fossils; dimension white space and literature anchors are E0 context. "
            "None of them alone proves acceptance of a specific solution."
        ),
    }
    output = root / "04-findings" / "lexicon-yield.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = dict(payload)
    result["lexicon_yield_file"] = str(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if sufficiency["status"] == "insufficient":
        return 1
    return 0


def _aggregate_manifests(manifest_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "runs": 0,
        "invalid_manifests": 0,
        "requested_records": 0,
        "reached_records": 0,
        "written_records": 0,
        "connectors": [],
        "platforms": [],
        "stop_reasons": {},
    }
    if not manifest_dir.is_dir():
        return result
    connectors: set[str] = set()
    platforms: set[str] = set()
    stop_reasons: Counter[str] = Counter()
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            manifest = _load_json(path)
        except (OSError, json.JSONDecodeError):
            result["invalid_manifests"] += 1
            continue
        if not isinstance(manifest, dict):
            result["invalid_manifests"] += 1
            continue
        result["runs"] += 1
        for field_name in ("requested_records", "reached_records", "written_records"):
            legacy_name = field_name.removesuffix("_records")
            try:
                result[field_name] += int(manifest.get(field_name, manifest.get(legacy_name, 0)))
            except (TypeError, ValueError):
                continue
        connector_id = str(manifest.get("connector_id", "")).strip()
        platform = str(manifest.get("platform", "")).strip()
        if connector_id and "待填写" not in connector_id:
            connectors.add(connector_id)
        if platform and "待填写" not in platform:
            platforms.add(platform)
        stop_reason = str(manifest.get("stop_reason", "")).strip()
        if stop_reason and "待填写" not in stop_reason:
            stop_reasons[stop_reason] += 1
    result["connectors"] = sorted(connectors)
    result["platforms"] = sorted(platforms)
    result["stop_reasons"] = dict(sorted(stop_reasons.items()))
    return result


def _format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _render_report(
    root: Path,
    study: dict[str, Any],
    signals: dict[str, Any],
    manifests: dict[str, Any],
    audit_payload: dict[str, Any] | None,
    judgments: list[Any],
    feasibility: dict[str, Any] | None,
) -> str:
    plan = study.get("plan", {}) if isinstance(study.get("plan"), dict) else {}
    decision = study.get("decision", {})
    scope = study.get("scope", {})
    gates = study.get("quality_gates", {})
    audit_status = (audit_payload or {}).get("status", "missing")
    failed_checks = [
        f"{check.get('id', '?')}: {check.get('detail', '')}"
        for check in (audit_payload or {}).get("checks", [])
        if isinstance(check, dict) and check.get("status") == "fail"
    ]
    lines: list[str] = []
    lines.append(f"# {study.get('title', '用户需求研究')} — 调研报告")
    lines.append("")
    lines.append(
        f"- 研究编号：`{study.get('study_id', '')}`　方法版本：`{study.get('method_version', '')}`"
    )
    lines.append(f"- 生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    if audit_status == "pass":
        lines.append("- 阶段检查：**通过**（结构与证据链门槛通过，不证明总体比例）")
    else:
        lines.append(f"- 阶段检查：**未通过（{audit_status}）**。未通过项：")
        for check in failed_checks[:10]:
            lines.append(f"  - {check}")
        lines.append("  在通过 `check --stage full` 之前，本报告的结论只能停留在研究状态输出。")
    lines.append("")

    lines.append("## 1. 研究定位")
    lines.append("")
    if plan:
        lines.append(f"- 研究目标：{plan.get('goal', '')}")
        region = plan.get("region", "")
        market = plan.get("market", "")
        lines.append(f"- 研究范围：`{region}`" + (f"（标注市场：`{market}`，作为采样语境而非常住地）" if market else "（作为采样语境而非常住地）"))
        lines.append(f"- 样本容量目标：{_format_int(plan.get('sample_target', 0))}（采集上限，不是独立用户数）")
        quotas = plan.get("platform_quotas", {})
        if isinstance(quotas, dict) and quotas:
            quota_text = "、".join(
                f"{platform} {_format_int(value)}" for platform, value in sorted(quotas.items())
            )
            lines.append(f"- 平台配额：{quota_text}")
    lines.append(f"- 决策问题：{decision.get('question', '')}")
    options = decision.get("options", [])
    if options:
        lines.append(f"- 决策选项：{'；'.join(str(option) for option in options)}")
    deadline = decision.get("deadline", "")
    if deadline:
        lines.append(f"- 决策期限：{deadline}")
    window = scope.get("source_time_window", {})
    if isinstance(window, dict) and window.get("start"):
        lines.append(f"- 来源时间窗：{window.get('start', '')} 至 {window.get('end', '')}")
    hypotheses = study.get("hypotheses", [])
    if hypotheses:
        lines.append("")
        lines.append("研究假设：")
        for hypothesis in hypotheses:
            if isinstance(hypothesis, dict):
                lines.append(
                    f"- **{hypothesis.get('id', '')}** {hypothesis.get('statement', '')}"
                    f"（证伪条件：{hypothesis.get('falsified_if', '')}）"
                )
    lines.append("")

    lines.append("## 2. 产品与商业推理主链")
    lines.append("")
    reasoning_path = root / "04-findings" / "product-reasoning.json"
    reasoning = None
    if reasoning_path.is_file():
        try:
            loaded_reasoning = _load_json(reasoning_path)
            if isinstance(loaded_reasoning, dict):
                reasoning = loaded_reasoning
        except (OSError, json.JSONDecodeError):
            reasoning = None
    if reasoning is not None:
        lines.extend(sure_engine._product_chain_lines(reasoning))
    else:
        lines.append("尚未建立产品推理链；运行 `askovo chain STUDY`，不要用数据量替代产品推导。")
        lines.append("")

    lines.append("## 3. 数据来源与采集（服务推理缺口）")
    lines.append("")
    lines.append("| 证据角色 | 来源平台 | 路线 | 目标量 | 访问状态 | 已知偏差 | 服务节点 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    source_plan_path = root / "01-sources" / "source-plan.csv"
    if source_plan_path.is_file():
        with source_plan_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                lines.append(
                    f"| {row.get('corpus_role', '')} | {row.get('source_family', '')} | "
                    f"{row.get('route_or_query', '')} | {row.get('target_records', '')} | "
                    f"{row.get('access_status', '')} | {row.get('known_bias', '')} | {row.get('reasoning_nodes', '')} |"
                )
    if manifests.get("runs"):
        lines.append("")
        lines.append(
            f"采集执行：{manifests['runs']} 次运行，请求 {_format_int(manifests['requested_records'])} 条、"
            f"触达 {_format_int(manifests['reached_records'])} 条、写入 {_format_int(manifests['written_records'])} 条。"
        )
        if manifests.get("connectors"):
            lines.append(f"使用连接器：{', '.join(f'`{c}`' for c in manifests['connectors'])}。")
        if manifests.get("stop_reasons"):
            stop_text = "；".join(
                f"{reason} ×{count}" for reason, count in manifests["stop_reasons"].items()
            )
            lines.append(f"停止原因：{stop_text}。")
    else:
        lines.append("")
        lines.append("尚未记录任何采集 manifest；采集量数据缺失。")
    lines.append("")

    lines.append("## 4. 数据质量与关键信号")
    lines.append("")
    total = signals.get("record_count", 0)
    lines.append(
        f"证据库共 {_format_int(total)} 条记录（唯一 ID {_format_int(signals.get('unique_record_ids', 0))} 个，"
        f"唯一来源引用 {_format_int(signals.get('unique_source_refs', 0))} 个）。"
    )
    time_range = signals.get("time_range", {})
    if time_range.get("earliest"):
        lines.append(
            f"来源时间跨度：{time_range.get('earliest')} 至 {time_range.get('latest')}"
            f"（{time_range.get('span_days')} 天）；最大单月占比 {_format_percent(time_range.get('top_month_share'))}"
            f"（{time_range.get('top_month')}）。"
        )
    lines.append("")
    lines.append("证据等级分布：")
    lines.append("")
    lines.append("| 证据等级 | 记录数 | 占比 |")
    lines.append("| --- | --- | --- |")
    for level, count in signals.get("evidence_levels", {}).items():
        share = (count / total) if total else 0
        lines.append(f"| {level} | {_format_int(count)} | {_format_percent(share)} |")
    lines.append("")
    lines.append("证据角色覆盖：")
    lines.append("")
    lines.append("| 证据角色 | 记录数 | 占比 |")
    lines.append("| --- | --- | --- |")
    for role, count in signals.get("corpus_roles", {}).items():
        share = (count / total) if total else 0
        lines.append(f"| {role} | {_format_int(count)} | {_format_percent(share)} |")
    chain = signals.get("chain_readiness", {})
    lines.append("")
    lines.append(
        f"链条就绪度：问题链（E1/E2）{chain.get('problem_E1_E2', 0)} 条；方案链（E3）"
        f"{chain.get('solution_E3', 0)} 条；商业/行为链（E4+/E5）{chain.get('commercial_E4p_E5', 0)} 条；"
        f"反证（E4−）{chain.get('counter_E4m', 0)} 条。"
    )
    gate_report = signals.get("gates", {})
    if gate_report:
        lines.append("")
        lines.append("质量门槛：")
        lines.append("")
        lines.append("| 门槛 | 要求 | 观察 | 状态 |")
        lines.append("| --- | --- | --- | --- |")
        min_gate = gate_report.get("min_evidence_records", {})
        if min_gate:
            lines.append(
                f"| 最小证据量 | {_format_int(min_gate.get('required', 0))} | "
                f"{_format_int(min_gate.get('observed', 0))} | {min_gate.get('status', '')} |"
            )
        family_gate = gate_report.get("max_source_family_share", {})
        if family_gate:
            lines.append(
                f"| 单一来源家族占比上限 | {_format_percent(family_gate.get('limit', 0))} | "
                f"{_format_percent(family_gate.get('observed', 0))} | {family_gate.get('status', '')} |"
            )
        duplicate_gate = gate_report.get("max_normalized_duplicate_rate", {})
        if duplicate_gate:
            lines.append(
                f"| 重复率上限 | {_format_percent(duplicate_gate.get('limit', 0))} | "
                f"{_format_percent(duplicate_gate.get('observed', 0))} | {duplicate_gate.get('status', '')} |"
            )
        for role, item in gate_report.get("required_corpus_roles", {}).items():
            lines.append(
                f"| 角色覆盖：{role} | 需要 ≥1 | {_format_int(item.get('observed', 0))} | {item.get('status', '')} |"
            )
    lexicon_yield_path = root / "04-findings" / "lexicon-yield.json"
    if lexicon_yield_path.is_file():
        try:
            lexicon_yield = _load_json(lexicon_yield_path)
        except (OSError, json.JSONDecodeError):
            lexicon_yield = None
        if isinstance(lexicon_yield, dict):
            lines.append("")
            lines.append("### 命名前研究信号（词表产出）")
            lines.append("")
            path_yield = lexicon_yield.get("grounding_path_yield", {})
            path_bits = []
            for path, item in path_yield.items():
                if isinstance(item, dict) and (
                    item.get("lexicon_terms") or item.get("evidence_records")
                ):
                    path_bits.append(
                        f"{path}（词 {item.get('lexicon_terms', 0)} 个 / 证据 "
                        f"{_format_int(item.get('evidence_records', 0))} 条）"
                    )
            if path_bits:
                lines.append("词表按路径产出：" + "；".join(path_bits) + "。")
            fossils = lexicon_yield.get("demand_fossil_records", 0)
            lines.append(f"需求化石（替代行为 E2 证据）：{_format_int(fossils)} 条。")
            zero_terms = lexicon_yield.get("zero_yield_terms", [])
            if zero_terms:
                lines.append(f"零产出词（需要重设路线或降级状态）：{', '.join(zero_terms)}。")
            sufficiency = lexicon_yield.get("sufficiency", {})
            if isinstance(sufficiency, dict) and sufficiency.get("status") != "not_evaluated":
                insufficient = sufficiency.get("insufficient_terms", [])
                if insufficient:
                    lines.append(
                        f"存量数据充分性：**不足**（低于每词最低 {sufficiency.get('min_per_term')} 条）："
                        + ", ".join(insufficient)
                        + "。需要按计划路线补采。"
                    )
                else:
                    lines.append(
                        f"存量数据充分性：通过（每词 ≥ {sufficiency.get('min_per_term')} 条）。"
                    )
            lines.append(
                "边界：proto-词簇是 E1 发现信号；替代行为是 E2 需求化石；维度白区与文献锚点是 E0 语境，"
                "单独任何一项都不构成对特定方案的接受证据。"
            )
    lines.append("")

    lines.append("## 5. 需求判断")
    lines.append("")
    if judgments:
        lines.append("| 编号 | 判断 | 状态 | 置信 | 问题/方案/商业/反证链 | 缺口 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for judgment in judgments:
            if not isinstance(judgment, dict):
                continue
            chains = (
                f"{len(judgment.get('problem_evidence_ids', []))}/"
                f"{len(judgment.get('solution_evidence_ids', []))}/"
                f"{len(judgment.get('commercial_evidence_ids', []))}/"
                f"{len(judgment.get('counter_evidence_ids', []))}"
            )
            gaps = len(judgment.get("gaps", []))
            lines.append(
                f"| {judgment.get('id', '')} | {judgment.get('title', '')} | "
                f"{judgment.get('status', '')} | {judgment.get('confidence', '')} | {chains} | {gaps} |"
            )
        next_tests = [
            f"- **{judgment.get('id', '')}**：{judgment.get('next_test', '')}"
            for judgment in judgments
            if isinstance(judgment, dict) and judgment.get("next_test")
        ]
        if next_tests:
            lines.append("")
            lines.append("下一步验证：")
            lines.extend(next_tests)
    else:
        lines.append("尚无需求判断；研究还未进入决策阶段。")
    lines.append("")

    lines.append("## 6. 反证与缺口")
    lines.append("")
    blocked = []
    if feasibility and isinstance(feasibility.get("platforms"), list):
        blocked = [
            item
            for item in feasibility["platforms"]
            if isinstance(item, dict) and item.get("status") not in {"enabled"}
        ]
    if blocked:
        lines.append("不可用路线（已审查、保持禁用）：")
        for item in blocked:
            lines.append(
                f"- {item.get('platform', '')}（{item.get('status', '')}）：{item.get('reason', '')}"
            )
        lines.append("")
    missing_roles = [
        role
        for role, item in gate_report.get("required_corpus_roles", {}).items()
        if item.get("status") != "pass"
    ]
    if missing_roles:
        lines.append(f"证据角色缺口：{', '.join(missing_roles)}。")
    if chain.get("counter_E4m", 0) == 0 and total:
        lines.append("证据库中没有 E4− 反证记录；`validated` 判断目前无法通过反证要求。")
    prohibited = scope.get("prohibited_inferences", [])
    if prohibited:
        lines.append("")
        lines.append("禁止推断：")
        for item in prohibited:
            lines.append(f"- {item}")
    lines.append("")

    lines.append("## 7. 结论边界")
    lines.append("")
    insights_path = root / "04-findings" / "insights.md"
    if insights_path.is_file():
        lines.append("### 关键发现（Agent 洞察）")
        lines.append("")
        lines.append(insights_path.read_text(encoding="utf-8").strip())
        lines.append("")
    else:
        lines.append(
            "尚未生成 `04-findings/insights.md`；本报告只包含确定性信号，"
            "场景与语义层发现由 Agent 按 runbook 补充。"
        )
    lines.append("")
    lines.append(
        "本报告基于便利样本与配置门槛。记录数不是用户数，检索地区不是常住地，"
        "任何比例都不能外推为总体市场规模。CLI 通过只说明结构与证据链检查通过，"
        "不证明需求真实性、代表性或因果。"
    )
    return "\n".join(lines) + "\n"


def command_report(args: argparse.Namespace) -> int:
    root = Path(args.study_dir).resolve()
    study_path = root / "study.json"
    if not study_path.is_file():
        print(f"missing study.json under {root}", file=sys.stderr)
        return 2
    try:
        study = _load_json(study_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot parse study.json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(study, dict):
        print("study.json must contain an object", file=sys.stderr)
        return 2

    try:
        # Reports must reflect current artifacts, not stale latest.json/signals.json files.
        signals = _compute_signals(root, study)
        audit_payload: dict[str, Any] | None = audit_study(root, "full").as_dict()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"cannot audit current study artifacts: {exc}", file=sys.stderr)
        return 2

    judgments: list[Any] = []
    judgments_path = root / "04-findings" / "demand-judgments.json"
    if judgments_path.is_file():
        try:
            loaded = _load_json(judgments_path)
            if isinstance(loaded, list):
                judgments = loaded
        except (OSError, json.JSONDecodeError):
            judgments = []

    feasibility = None
    feasibility_path = root / "01-sources" / "feasibility.json"
    if feasibility_path.is_file():
        try:
            loaded_feasibility = _load_json(feasibility_path)
            if isinstance(loaded_feasibility, dict):
                feasibility = loaded_feasibility
        except (OSError, json.JSONDecodeError):
            feasibility = None

    manifests = _aggregate_manifests(root / "01-sources" / "manifests")
    report_text = _render_report(
        root, study, signals, manifests, audit_payload, judgments, feasibility
    )
    output = Path(args.output) if args.output else root / "06-report" / "research-status.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "written",
                "report": str(output),
                "audit_status": audit_payload.get("status"),
                "judgments": len(judgments),
                "manifest_runs": manifests.get("runs", 0),
                "meaning": (
                    "The report assembles configured artifacts. It does not certify truth, "
                    "representativeness, market size, or causality."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# Thin forwarder to the consolidated stage toolbox (scripts/stages/).
# The stage scripts own dataset-pipeline behavior (labeling, dataset building,
# audit workbooks); askovo.py only routes and passes the exit code through.
STAGES_DIR = Path(__file__).resolve().parent / "stages"

STAGE_COMMANDS = (
    "import-feedback-export",
    "label-feedback",
    "build-primary-dataset",
    "build-month-balanced-dataset",
    "extract-candidate-signals",
    "export-metadata-detail",
    "audit-workbook",
)


def command_stage(args: argparse.Namespace) -> int:
    stage = str(args.stage_name).replace("_", "-")
    if stage not in STAGE_COMMANDS:
        print(
            json.dumps(
                {"status": "error", "unknown_stage": stage, "known_stages": list(STAGE_COMMANDS)},
                ensure_ascii=False,
            )
        )
        return 2
    script = STAGES_DIR / f"{stage.replace('-', '_')}.py"
    if not script.exists():
        print(json.dumps({"status": "error", "missing_script": str(script)}, ensure_ascii=False))
        return 2
    completed = subprocess.run([sys.executable, str(script)] + list(args.stage_args))
    return int(completed.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="askovo",
        description="One entry for software/hardware/consumer/automotive/mobile research: route, plan, collect, analyze, deliver.",
    )
    parser.add_argument("--version", action="version", version=f"Askovo {ASKOVO_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="create a study workspace from the bundled template")
    init_parser.add_argument("study_dir")
    init_parser.add_argument("--study-id", required=True)
    init_parser.add_argument("--title", required=True)
    init_parser.add_argument("--decision", required=True)
    init_parser.add_argument(
        "--platform",
        action="append",
        choices=("reddit", "x", "youtube", "amazon", "jd", "taobao", "kickstarter"),
        default=[],
        help="copy and enable a platform route template; repeat for multiple platforms",
    )
    init_parser.set_defaults(func=command_init)

    plan_parser = subparsers.add_parser(
        "plan",
        help="turn goal, region, sample size, and platform types into a study workspace, "
        "quotas, feasibility report, and collection tasks",
    )
    plan_parser.add_argument("study_dir")
    plan_parser.add_argument("--goal", required=True, help="research target: product, user, or scene")
    plan_parser.add_argument(
        "--region",
        required=True,
        choices=("cn", "overseas", "global"),
        help="sampling region; recorded as context, not verified residence",
    )
    plan_parser.add_argument(
        "--sample-size", required=True, type=int, help="target record volume, e.g. 100000"
    )
    plan_parser.add_argument(
        "--platform-types",
        required=True,
        help="comma-separated: forum,social,video,ecommerce,crowdfunding",
    )
    plan_parser.add_argument(
        "--mode",
        choices=("standard", "unnamed_experience", "unnamed-experience"),
        default="standard",
        help="unnamed-experience runs the grounding phase first: edge-language mining, "
        "substitute-behavior archaeology, psychophysical dimensions, and literature anchors "
        "produce the lexicon and scope before keyword routes are designed",
    )
    plan_parser.add_argument("--market", help="optional market label such as us or de")
    plan_parser.add_argument("--languages", help="comma-separated language codes, e.g. en,zh")
    plan_parser.add_argument(
        "--time-window", help="START:END ISO dates, e.g. 2025-01-01:2026-08-31"
    )
    plan_parser.add_argument("--decision", help="decision question this study must inform")
    plan_parser.add_argument("--study-id", help="defaults to a generated dated id")
    plan_parser.add_argument("--title", help="defaults to the goal text")
    plan_parser.set_defaults(func=command_plan)

    signals_parser = subparsers.add_parser(
        "signals", help="compute deterministic corpus signals from evidence.jsonl"
    )
    signals_parser.add_argument("study_dir")
    signals_parser.set_defaults(func=command_signals)

    lexicon_parser = subparsers.add_parser(
        "lexicon",
        help="compute lexicon term yield and stock-corpus sufficiency for an "
        "unnamed-experience study",
    )
    lexicon_parser.add_argument("study_dir")
    lexicon_parser.add_argument(
        "--min-per-term",
        type=int,
        help="minimum graded records per lexicon term for sufficiency; exit 1 when insufficient",
    )
    lexicon_parser.set_defaults(func=command_lexicon)

    report_parser = subparsers.add_parser(
        "report", help="assemble a Chinese research-status report from study artifacts"
    )
    report_parser.add_argument("study_dir")
    report_parser.add_argument(
        "--output", help="report path; defaults to 06-report/research-status.md"
    )
    report_parser.set_defaults(func=command_report)

    demo_parser = subparsers.add_parser(
        "demo", help="run the bundled synthetic sample in a temporary directory"
    )
    demo_parser.set_defaults(func=command_demo)

    route_parser = subparsers.add_parser(
        "route", help="detect product domain, stage, intent and risk from a request"
    )
    route_parser.add_argument("need", help="natural-language research request")
    route_parser.add_argument("--domain", choices=tuple(sure_engine.domain_packs().keys()))
    route_parser.add_argument("--stage", choices=sure_engine.STAGES)
    route_parser.add_argument("--intent", choices=sure_engine.INTENTS)
    route_parser.add_argument("--json", action="store_true")
    route_parser.set_defaults(func=sure_engine.cli_route)

    do_parser = subparsers.add_parser(
        "do", help="route and scaffold a study in one step (the single entry point)"
    )
    do_parser.add_argument("need", help="natural-language research request")
    do_parser.add_argument("--study", help="workspace path; defaults to ./askovo-<domain>-<stage>")
    do_parser.add_argument("--domain", choices=tuple(sure_engine.domain_packs().keys()))
    do_parser.add_argument("--stage", choices=sure_engine.STAGES)
    do_parser.add_argument("--intent", choices=sure_engine.INTENTS)
    do_parser.add_argument("--dry-run", action="store_true", help="route only; write nothing")
    do_parser.add_argument("--ack-risk", action="store_true", help="acknowledge safety/ethics review")
    do_parser.add_argument("--force", action="store_true")
    do_parser.add_argument("--json", action="store_true")
    do_parser.set_defaults(func=sure_engine.cli_do)

    domains_parser = subparsers.add_parser("domains", help="list product research packs")
    domains_parser.add_argument("--json", action="store_true")
    domains_parser.set_defaults(func=sure_engine.cli_domains)

    methods_parser = subparsers.add_parser("methods", help="list methods for a domain and stage")
    methods_parser.add_argument("--domain", required=True, choices=tuple(sure_engine.domain_packs().keys()))
    methods_parser.add_argument("--stage", choices=sure_engine.STAGES)
    methods_parser.add_argument("--json", action="store_true")
    methods_parser.set_defaults(func=sure_engine.cli_methods)

    catalog_parser = subparsers.add_parser("catalog", help="show the method catalog")
    catalog_parser.add_argument("--domain", choices=tuple(sure_engine.domain_packs().keys()))
    catalog_parser.add_argument("--stage", choices=sure_engine.STAGES)
    catalog_parser.add_argument("--json", action="store_true")
    catalog_parser.set_defaults(func=sure_engine.cli_catalog)

    platforms_parser = subparsers.add_parser(
        "platforms", help="rank platforms by data availability, access mode and evidence fit"
    )
    platforms_parser.add_argument("need", help="research question or data request")
    platforms_parser.add_argument("--domain", choices=tuple(sure_engine.domain_packs().keys()))
    platforms_parser.add_argument("--claim-type", action="append", choices=sure_engine.CLAIM_TYPES)
    platforms_parser.add_argument("--bulk", action="store_true", help="prefer platforms with bulk access")
    platforms_parser.add_argument("--json", action="store_true")
    platforms_parser.set_defaults(func=sure_engine.cli_platforms)

    collect_parser = subparsers.add_parser(
        "collect", help="run a platform collector with quota, manifest and dedup"
    )
    collect_parser.add_argument("study_dir")
    collect_parser.add_argument("--platform", required=True)
    collect_parser.add_argument("--query", required=True)
    collect_parser.add_argument("--limit", type=int, default=100)
    collect_parser.add_argument("--dry-run", action="store_true")
    collect_parser.add_argument("--fixture", help="local JSONL/CSV fixture for offline collection")
    collect_parser.add_argument("--cdp-url", help="Chrome DevTools endpoint, e.g. http://127.0.0.1:9222")
    collect_parser.add_argument("--url", help="authorized visible page URL for CDP")
    collect_parser.add_argument("--ack-terms", action="store_true", help="acknowledge platform terms and authorized session")
    collect_parser.set_defaults(func=command_collect)

    analyze_parser = subparsers.add_parser(
        "analyze", help="normalize, dedup and describe collected material"
    )
    analyze_parser.add_argument("study_dir")
    analyze_parser.add_argument("--question", help="optional question to match quotes against")
    analyze_parser.set_defaults(func=sure_engine.cli_analyze)

    instruments_parser = subparsers.add_parser(
        "instruments", help="generate interview/observation/test instruments for a study"
    )
    instruments_parser.add_argument("study_dir")
    instruments_parser.set_defaults(func=sure_engine.cli_instruments)

    import_parser = subparsers.add_parser(
        "import", help="import interviews, CSV, JSONL or text as evidence"
    )
    import_parser.add_argument("study_dir")
    import_parser.add_argument("file")
    import_parser.add_argument("--source-family", default="imported")
    import_parser.add_argument("--evidence-form", default="self_report")
    import_parser.add_argument("--claim-type", default="need", choices=sure_engine.CLAIM_TYPES)
    import_parser.add_argument("--method-id", default="imported")
    import_parser.set_defaults(func=sure_engine.cli_import)

    codebook_parser = subparsers.add_parser("codebook", help="scaffold a claim-type codebook")
    codebook_parser.add_argument("study_dir")
    codebook_parser.set_defaults(func=sure_engine.cli_codebook)

    chain_parser = subparsers.add_parser(
        "chain", help="scaffold and render the scene-user-pain-need-feature-product-business reasoning chain"
    )
    chain_parser.add_argument("study_dir")
    chain_parser.set_defaults(func=sure_engine.cli_chain)

    deliver_parser = subparsers.add_parser(
        "deliver", help="assemble chain-led PM, PRD, BRD, user-operations and tracker deliverables"
    )
    deliver_parser.add_argument("study_dir")
    deliver_parser.add_argument("--kind", choices=("memo", "report", "mrd", "prd", "brd", "ops", "tracker"), default="memo")
    deliver_parser.set_defaults(func=sure_engine.cli_deliver)

    queue_parser = subparsers.add_parser(
        "queue", help="durable collection queue: init/add/run/status/retry"
    )
    queue_sub = queue_parser.add_subparsers(dest="queue_command", required=True)
    queue_init = queue_sub.add_parser("init", help="create the SQLite queue")
    queue_init.add_argument("study_dir")
    queue_init.set_defaults(func=sure_engine.cli_queue_init)
    queue_add = queue_sub.add_parser("add", help="enqueue a collection job")
    queue_add.add_argument("study_dir")
    queue_add.add_argument("--platform", required=True)
    queue_add.add_argument("--query", required=True)
    queue_add.add_argument("--limit", type=int, default=100)
    queue_add.add_argument("--fixture")
    queue_add.add_argument("--cdp-url")
    queue_add.add_argument("--url", help="CDP target page URL")
    queue_add.add_argument("--ack-terms", action="store_true")
    queue_add.add_argument("--max-attempts", type=int, default=3)
    queue_add.set_defaults(func=sure_engine.cli_queue_add)
    queue_run = queue_sub.add_parser("run", help="run workers until the queue drains")
    queue_run.add_argument("study_dir")
    queue_run.add_argument("--workers", type=int, default=2)
    queue_run.add_argument("--min-interval", type=float, default=None, help="override per-platform seconds")
    queue_run.add_argument("--lease-seconds", type=float, default=300)
    queue_run.set_defaults(func=command_queue_run)
    queue_status = queue_sub.add_parser("status", help="show queue counts and recent errors")
    queue_status.add_argument("study_dir")
    queue_status.set_defaults(func=sure_engine.cli_queue_status)
    queue_retry = queue_sub.add_parser("retry", help="move failed jobs back to pending")
    queue_retry.add_argument("study_dir")
    queue_retry.set_defaults(func=sure_engine.cli_queue_retry)

    doctor_parser = subparsers.add_parser("doctor", help="check catalog, packs, method refs and version")
    doctor_parser.set_defaults(func=sure_engine.cli_doctor)

    audit_parser = subparsers.add_parser(
        "audit",
        help="audit a study and explain what the evidence can support (gates + signals + claim verdicts)",
    )
    audit_parser.add_argument("study_dir")
    audit_parser.add_argument(
        "--claim", help="limit the report to claims whose id/title/status matches this text"
    )
    audit_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    audit_parser.set_defaults(func=command_audit)

    check_parser = subparsers.add_parser("check", help="audit one research stage")
    check_parser.add_argument("study_dir")
    check_parser.add_argument("--stage", choices=STAGES, default="full")
    check_parser.add_argument("--write-report", action="store_true")
    check_parser.set_defaults(func=command_check)

    connector_parser = subparsers.add_parser(
        "connectors", help="list reviewed open-source connector decisions"
    )
    connector_parser.add_argument(
        "--platform",
        choices=("reddit", "x", "youtube", "amazon", "jd", "taobao", "kickstarter"),
    )
    connector_parser.add_argument(
        "--include-blocked",
        action="store_true",
        help="include rejected repositories and their reasons",
    )
    connector_parser.set_defaults(func=command_connectors)

    stage_parser = subparsers.add_parser(
        "stage",
        help="forward to a consolidated dataset-pipeline stage script (scripts/stages/); "
        "everything after the stage name is passed through verbatim",
    )
    stage_parser.add_argument(
        "stage_name",
        choices=STAGE_COMMANDS,
        help="label-feedback, build-primary-dataset, audit-workbook, ... (see scripts/stages/README.md)",
    )
    stage_parser.add_argument("stage_args", nargs=argparse.REMAINDER)
    stage_parser.set_defaults(func=command_stage)
    return parser


CLI_COMMANDS = {
    "init", "plan", "signals", "lexicon", "report", "demo", "route", "do", "domains",
    "methods", "catalog", "platforms", "collect", "analyze", "instruments", "import", "queue",
    "codebook", "chain", "deliver", "doctor", "audit", "check", "connectors", "stage",
}


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and not raw[0].startswith("-") and raw[0] not in CLI_COMMANDS:
        # Bare natural-language request in any language: route it through `do`.
        raw = ["do", *raw]
    args = build_parser().parse_args(raw)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

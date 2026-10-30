#!/usr/bin/env python3
"""Import an external feedback export (CSV / JSON / JSONL) into the raw-record
contract: normalized text, stable record ids, hashed authors, quality flags,
and taxonomy annotation.

Provenance (consolidation lineage):

- Base: ``projects/AI眼镜用户研究/scripts/import_feedback_export.py`` — byte-identical
  in ``projects/灵泷视界/用户研究/scripts/`` (the family's terminal form). Its
  broad FIELD_ALIASES (en + zh column names), multi-format reader, date
  normalization (epoch seconds/ms + several formats), derived record ids for
  id-less exports, platform-based source roles, and access-basis audit stamp
  are kept as-is.
- Project-agnostic changes: explicit output path resolved against the current
  directory (no ``ROOT``); sample-bucket inference and dimension annotation go
  through the taxonomy config (a missing taxonomy degrades to "no
  annotation", the import itself still works); field aliases can be extended
  via the taxonomy config (``field_aliases`` merges into the built-ins);
  ``.jsonl.gz`` output supported; ``--salt`` mirrors the connectors'
  anonymization convention (no salt → unsalted hash, cross-run joins need a
  study-stable salt).

I/O contract: external export file → ``data/raw/imports/<batch>.jsonl(.gz)``
(the RAW layer; feeds label_feedback / build_primary_dataset).

Imported text is untrusted source content: it is normalized, hashed, and
echoed as data — never executed or treated as instructions.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from common import (
    Taxonomy,
    author_hash,
    base_quality_flags,
    clean_text,
    is_primary_date,
    month_bucket,
    quality_score,
    read_jsonl,
    stable_text_hash,
    utc_from_timestamp,
    utc_now_iso,
    write_jsonl,
)

FIELD_ALIASES: Dict[str, List[str]] = {
    "id": ["id", "record_id", "comment_id", "review_id", "post_id", "tweet_id", "status_id", "permalink_id", "编号", "评论id", "笔记id", "帖子id", "商品id"],
    "text": ["text", "body", "comment", "content", "review", "review_text", "message", "caption", "full_text", "内容", "正文", "评论", "评论内容", "评价", "评价内容", "笔记内容", "微博内容", "弹幕", "回复内容"],
    "created_at": ["created_at", "created", "date", "published_at", "publishedAt", "timestamp", "time", "review_date", "发布时间", "发表时间", "评论时间", "评价时间", "创建时间", "时间"],
    "author": ["author", "username", "user", "user_id", "author_id", "screen_name", "display_name", "作者", "用户", "用户名", "昵称", "用户昵称", "博主", "up主"],
    "url": ["url", "source_url", "permalink", "link", "review_url", "post_url", "链接", "原文链接", "评论链接", "笔记链接", "商品链接", "页面链接"],
    "score": ["score", "rating", "stars", "like_count", "likes", "upvotes", "helpful_votes", "评分", "星级", "点赞数", "赞", "有用数"],
    "reply_count": ["reply_count", "replies", "comment_count", "comments", "回复数", "评论数", "互动数"],
    "product": ["product", "product_name", "asin", "campaign", "campaign_name", "title", "thread_title", "商品", "商品名称", "产品", "产品名称", "标题", "笔记标题", "视频标题"],
    "channel": ["channel", "source_channel", "subreddit", "creator", "store", "marketplace", "平台", "渠道", "店铺", "账号", "频道", "来源"],
    "query": ["query", "source_query", "keyword", "search_term", "关键词", "搜索词", "话题"],
    "region": ["region", "country", "market", "locale", "language", "地区", "国家", "市场", "语言"],
    "parent_id": ["parent_id", "thread_id", "conversation_id", "video_id", "asin", "campaign_id"],
}


def read_input(path: Path) -> Iterable[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        yield from read_jsonl(path)
        return
    if suffix == ".jsonl":
        yield from read_jsonl(path)
        return
    if suffix == ".json":
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            yield from data
        elif isinstance(data, dict):
            items = data.get("items") or data.get("data") or data.get("records")
            if isinstance(items, list):
                yield from items
            else:
                yield data
        return
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield dict(row)


def first_value(row: Dict[str, Any], explicit: str, aliases: List[str]) -> Any:
    if explicit:
        return row.get(explicit)
    lower_map = {str(k).lower(): k for k in row.keys()}
    for alias in aliases:
        key = lower_map.get(alias.lower())
        if key is not None:
            return row.get(key)
    return None


def normalize_date(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return utc_from_timestamp(value)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        return utc_from_timestamp(float(text))
    if re.fullmatch(r"\d{13}", text):
        return utc_from_timestamp(float(text) / 1000)
    text = text.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    return text


def make_record_id(source_platform: str, source_id: Any, text: str, source_url: Any) -> str:
    if source_id:
        return f"{source_platform}:{source_id}"
    key = str(source_url or "") or stable_text_hash(text) or str(hash(text))
    digest = stable_text_hash(key) or str(abs(hash(key)))
    return f"{source_platform}:imported:{digest}"


def source_role_for(platform: str) -> str:
    platform = (platform or "").lower()
    if platform in {
        "amazon", "bestbuy", "walmart", "newegg", "ecommerce", "app_store",
        "google_play", "jd", "jingdong", "taobao", "tmall", "rakuten",
        "coupang", "qoo10",
    }:
        return "purchase_feedback"
    if platform in {"kickstarter", "indiegogo", "crowdfunding"}:
        return "backer_preorder_or_fulfillment"
    if platform in {
        "x", "twitter", "instagram", "tiktok", "threads", "youtube",
        "xiaohongshu", "xhs", "weibo", "zhihu", "bilibili", "douyin", "kuaishou",
    }:
        return "social_feedback"
    return "imported_feedback"


def normalize_row(row: Dict[str, Any], args: argparse.Namespace, taxonomy: Taxonomy) -> Dict[str, Any] | None:
    text = clean_text(first_value(row, args.text_field, FIELD_ALIASES["text"]))
    if len(text) < args.min_text_chars:
        return None
    created_at = normalize_date(first_value(row, args.created_at_field, FIELD_ALIASES["created_at"]))
    source_url = first_value(row, args.url_field, FIELD_ALIASES["url"])
    source_id = first_value(row, args.id_field, FIELD_ALIASES["id"])
    score = first_value(row, args.score_field, FIELD_ALIASES["score"])
    reply_count = first_value(row, args.reply_count_field, FIELD_ALIASES["reply_count"])
    author = first_value(row, args.author_field, FIELD_ALIASES["author"])
    product = clean_text(first_value(row, args.product_field, FIELD_ALIASES["product"]))
    channel = clean_text(first_value(row, args.channel_field, FIELD_ALIASES["channel"])) or args.source_channel
    query = clean_text(first_value(row, args.query_field, FIELD_ALIASES["query"])) or args.source_query
    region = clean_text(first_value(row, args.region_field, FIELD_ALIASES["region"]))
    flags = base_quality_flags(text, created_at, taxonomy.primary_after_utc)
    if region:
        query = f"{query}|region:{region}" if query else f"region:{region}"
    normalized: Dict[str, Any] = {
        "record_id": make_record_id(args.source_platform, source_id, text, source_url),
        "source_platform": args.source_platform,
        "source_channel": channel or args.source_platform,
        "source_url": source_url,
        "source_query": query or args.source_platform,
        "created_at": created_at,
        "collected_at": utc_now_iso(),
        "author_hash": author_hash(str(author or ""), args.salt or taxonomy.author_salt),
        "text": text,
        "text_hash": stable_text_hash(text),
        "text_excerpt": text[:320],
        "score": score,
        "reply_count": reply_count,
        "parent_id": first_value(row, args.parent_id_field, FIELD_ALIASES["parent_id"]),
        "thread_title": product,
        "thread_url": source_url,
        "product_hint": product or None,
        "source_role": source_role_for(args.source_platform),
        "sample_bucket": taxonomy.infer_sample_bucket(text, query, args.source_platform),
        "month_bucket": month_bucket(created_at),
        "primary_sample_eligible": is_primary_date(created_at, taxonomy.primary_after_utc),
        "quality_score": quality_score(text, flags, score, taxonomy.quality_penalties),
        "sampling_weight": 1.0,
        "quality_flags": flags,
        "import_batch": args.import_batch,
        "import_source_file": str(args.input),
        "consent_or_access_basis": args.access_basis,
    }
    if taxonomy.label_rules or taxonomy.product_terms:
        taxonomy.annotate(normalized)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an external feedback export into the raw-record contract."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-platform", required=True, help="e.g. amazon, x, app_store")
    parser.add_argument(
        "--taxonomy", type=Path, default=None, help="optional taxonomy JSON (annotation + aliases)"
    )
    parser.add_argument("--source-channel", default="")
    parser.add_argument("--source-query", default="")
    parser.add_argument(
        "--access-basis",
        default="official_api_or_export",
        help="audit note: official_api, platform_export, licensed_provider, manual_audit, ...",
    )
    parser.add_argument(
        "--import-batch",
        default=datetime.now(tz=timezone.utc).strftime("%Y%m%d"),
    )
    parser.add_argument("--min-text-chars", type=int, default=20)
    parser.add_argument("--salt", default=None, help="study-stable author-hash salt")
    parser.add_argument("--id-field", default="")
    parser.add_argument("--text-field", default="")
    parser.add_argument("--created-at-field", default="")
    parser.add_argument("--author-field", default="")
    parser.add_argument("--url-field", default="")
    parser.add_argument("--score-field", default="")
    parser.add_argument("--reply-count-field", default="")
    parser.add_argument("--product-field", default="")
    parser.add_argument("--channel-field", default="")
    parser.add_argument("--query-field", default="")
    parser.add_argument("--region-field", default="")
    parser.add_argument("--parent-id-field", default="")
    parser.add_argument(
        "--out", type=Path, default=Path("data/raw/imports/imported_feedback.jsonl.gz")
    )
    args = parser.parse_args()

    taxonomy = Taxonomy.load(args.taxonomy) if args.taxonomy else Taxonomy()
    extra_aliases = (taxonomy.data.get("field_aliases") or {})
    for key, aliases in extra_aliases.items():
        merged = FIELD_ALIASES.get(str(key), [])
        FIELD_ALIASES[str(key)] = merged + [str(a) for a in aliases or [] if a not in merged]

    rows: List[Dict[str, Any]] = []
    seen = set()
    for raw in read_input(args.input):
        row = normalize_row(raw, args, taxonomy)
        if not row:
            continue
        rid = row.get("record_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        rows.append(row)

    write_jsonl(args.out, rows, append=False)
    print(f"imported {len(rows)} normalized records -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

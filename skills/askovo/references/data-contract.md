# Canonical data contract

Use JSONL for full records and CSV/Parquet only as analysis projections. Preserve full source text in the raw or strict-master layer. The compact `02-data/evidence.jsonl` file used by the CLI is an evidence index: it may contain the full text, but it must always retain a stable reference back to the source record.

## Required by the CLI

Every line in `02-data/evidence.jsonl` must contain these fields:

| Field | Meaning |
| --- | --- |
| `record_id` | Stable ID used by demand judgments. |
| `context_key` | Required when cited by a `validated` judgment; must exactly match the judgment's decision-context key. |
| `user_role` | Role or user state supported by the record. |
| `scene_trigger` | Situation and trigger in which the task occurs. |
| `task_outcome` | What the person is trying to complete or achieve. |
| `current_substitute` | Current product, workflow, person, workaround, or non-consumption. |
| `friction_cost` | Time, money, effort, discomfort, integration burden, or risk. |
| `consequence` | What happens when the task or substitute fails. |
| `evidence_level` | `E0`, `E1`, `E2`, `E3`, `E4+`, `E4-`, or `E5`. |
| `evidence_basis` | Short explanation of what was directly observed. |
| `corpus_role` | `direct_solution`, `open_scene`, `substitute_rejector`, `post_purchase_support`, or `control`. |
| `source_family` | Forum, interview, support, ecommerce, telemetry, etc. |
| `source_ref` | URL or privacy-safe local/source record reference. |
| `normalized_text_hash` | Stable exact/near-duplicate key. |

Two optional fields support unnamed-experience (grounding-first) studies; see [unnamed-experience-research.md](unnamed-experience-research.md):

| Field | Meaning |
| --- | --- |
| `lexicon_terms` | Retained seed-lexicon terms this record instantiates (array of strings from `01-sources/lexicon.csv`). |
| `grounding_path` | `edge_language`, `substitute_behavior`, `psychophysical`, `cross_domain`, or `discipline`. |

`askovo.py lexicon` uses these fields to compute per-term yield, acceptance-association proxies, demand-fossil counts, and stock-corpus sufficiency.

Missingness is allowed in the full research schema. For the compact evidence index, use an explicit value such as `unknown` only when the source genuinely does not provide the field; do not fabricate a substitute or consequence to satisfy the schema. Records with critical unknowns should stay below the claim level that needs those fields.

Example:

```json
{"record_id":"support-0042","context_key":"repair-guidance-context","user_role":"现场维修工程师","scene_trigger":"双手正在拆装设备，需要确认下一步操作","task_outcome":"在不停止操作的情况下取得准确指导","current_substitute":"放下工具后查看手机","friction_cost":"中断操作","consequence":"维修时间延长","evidence_level":"E2","evidence_basis":"原文描述了当前做法及其中断","corpus_role":"open_scene","source_family":"professional_forum","source_ref":"https://example.invalid/thread/42#record","normalized_text_hash":"sha256:..."}
```

The example supports a problem/substitute claim. It does not support solution acceptance, purchase intent, or market prevalence. A shared `context_key` prevents unrelated records from satisfying structural gates; human review still decides whether the role, scene, task, and counter-evidence are genuinely relevant.

## Extended provenance and identity fields

| Field | Type | Purpose |
| --- | --- | --- |
| `record_id` | string | Stable source-prefixed identifier. |
| `collection_run_id` | string/null | Links a platform record to one immutable connector manifest. |
| `connector_id` | string/null | Registry ID of the open-source connector used. |
| `connector_revision` | string/null | Pinned upstream commit used by the run. |
| `source_platform` | string | Named platform/site. |
| `source_family` | string | Forum, social, ecommerce, support, Q&A, video comments, etc. |
| `source_channel` | string/null | Community, product, repository, board, channel, or listing. |
| `source_url` | string/null | Traceable public or authorized source. |
| `parent_id` / `thread_id` | string/null | Prevent one long thread from masquerading as broad support. |
| `source_query` | string/null | Query or route that selected the record. |
| `sampling_frame` | string | Product, ecosystem, task, substitute, rejector, event, chronological, export, etc. |
| `sampling_bias_flags` | array | Ranking, logged-out, owner community, active-thread, search, highlighted-review, or other known limitations. |
| `created_at` | ISO string/null | Source time. |
| `date_precision` | string | Exact, day, month, year, approximate, unknown. |
| `collected_at` | ISO string | Collection time. |
| `author_hash` | string/null | Salted hash if needed for dedup; avoid raw identifiers by default. |

## Platform adapter provenance

All subreddits use `source_family=reddit`; all X routes use `source_family=x`; all YouTube channels and videos use `source_family=youtube`. Amazon, JD, Taobao/Tmall, and Kickstarter use their own named source families. Platform diversity is reported within a source family and does not count as independent cross-source confirmation.

When one of these platforms is present, read the shared adapter, open-source connector registry, connector contract, and platform reference. Every row first requires `collection_run_id`, `connector_id`, and `connector_revision`. The CLI additionally requires:

| Platform | Required provenance beyond the generic evidence index |
| --- | --- |
| Reddit | `source_platform`, `source_channel`, `source_url`, `thread_id`, `reddit_item_id`, `source_content_type`, `source_query`, `source_sort`, `source_time_filter`, `created_at`, `collected_at`, `content_status` |
| X | `source_platform`, `source_url`, `x_post_id`, `conversation_id`, `x_post_type`, `source_query`, `source_search_mode`, `created_at`, `collected_at`, `last_verified_at`, `content_status` |
| YouTube | `source_platform`, `source_channel`, `source_url`, `youtube_video_id`, `youtube_item_id`, `youtube_content_type`, `source_query`, `source_order`, `created_at`, `collected_at`, `last_verified_at`, `refresh_due_at`, `content_status` |
| Amazon/JD/Taobao | `source_platform`, `source_url`, product/variant/store/brand/record IDs, `commerce_content_type`, `commerce_transaction_status`, `source_completeness`, `source_query`, `created_at`, `collected_at`, `content_status` |
| Kickstarter | `source_platform`, `source_url`, campaign/creator IDs, `kickstarter_content_type`, `campaign_status`, `commercial_status`, `privacy_status`, `source_query`, `created_at`, `collected_at`, `content_status` |

Reddit comments should retain `parent_id`. X replies should retain `parent_id`; quote posts should retain `quoted_post_id`. YouTube comments require `comment_thread_id` and replies require `parent_id`. Amazon historical records retain ASIN and parent ASIN separately. Deleted, removed, unavailable, expired, or blocked records remain as route/audit tombstones if permitted but must be removed from claim-eligible evidence.

The run manifest lives at `01-sources/manifests/<collection_run_id>.json` and records the connector repository/revision/license, access basis, policy and data-rights review, route/query, requested/reached/written counts, quota/rate state, warnings, and stop reason. Credentials never enter the manifest.

## Content and quality

| Field | Type | Purpose |
| --- | --- | --- |
| `text` | string | Complete feedback text; do not truncate the master. |
| `language` | string/null | Detected or source-provided language. |
| `market_sampling_context` | string/null | Query locale/platform market, not verified residence. |
| `rating` / `score` / `reply_count` | number/null | Source metadata; do not use as demand by itself. |
| `quality_score` | number | Versioned and explainable screening score. |
| `quality_flags` | array | Deleted, duplicate, too short, spam, off-topic, approximate date, etc. |
| `normalized_text_hash` | string | Cross-source exact/near dedup key. |
| `primary_sample_eligible` | boolean | Meets declared date, access, content, quality, and relevance rules. |

## Research design

| Field | Type | Purpose |
| --- | --- | --- |
| `corpus_role` | string | Direct solution, open scene, substitute/rejector, post-purchase/support, control. |
| `month_bucket` | YYYY-MM/null | Time stratum. |
| `scene_labels` | array | Multi-valued activity context. |
| `user_role_labels` | array | Multi-valued role/state. |
| `task_labels` | array | Desired job or outcome. |
| `substitute_labels` | array | Current solution, workaround, or non-consumption. |
| `friction_labels` | array | Time, cost, cognition, comfort, integration, maintenance, risk, etc. |
| `consequence_labels` | array | Rework, loss, error, delay, abandonment, safety, or missed outcome. |
| `solution_response` | string/null | Accept, reject, conditional, neutral, unknown. |
| `demand_evidence_level` | string | `E0`, `E1`, `E2`, `E3`, `E4+`, `E4-`, or `E5`. |
| `evidence_basis` | string | Short explanation or matched rule for the assigned level. |
| `analysis_weight` | number/null | Design weight only. |
| `analysis_weight_basis` | string/null | Exact balancing rule; explicitly not a population weight. |

## Coding provenance

| Field | Type | Purpose |
| --- | --- | --- |
| `codebook_version` | string | Version of definitions used. |
| `coding_method` | string | Rule, LLM, human, or adjudicated. |
| `coder_or_model_version` | string/null | Reproducibility. |
| `coding_confidence` | number/null | Supports review queues, not truth claims. |
| `human_review_status` | string | Unreviewed, sampled, agreed, adjudicated, rejected. |

## Required derived views

Generate without mutating the strict master:

- counts by raw/strict/balanced layer;
- records and unique threads/products by source family and platform;
- monthly/quarterly/half-year distributions;
- evidence-role and evidence-level distributions;
- rejector/returner and paid/deployed coverage;
- scene × role × task × substitute × evidence pivots;
- missingness and approximate-date rates;
- duplicate and near-duplicate removals;
- blocked/failed collection routes;
- high-confidence claim-eligible subsets.

## Audit assertions

Parameterize thresholds in a study config. Test at least:

- strict record count after all filters;
- continuous or explicitly justified time coverage;
- maximum share for one month/event window;
- maximum share for one source family/platform/channel/thread;
- minimum independent source families;
- minimum open-scene, substitute/rejector, and post-purchase/support coverage;
- exact and normalized-text duplicate leakage;
- full-text, source URL, timestamp, and corpus-role completeness;
- language/market-stratum coverage;
- approximate-date cap;
- gold-set agreement and rare-label performance;
- representative positive and negative examples for every published claim.

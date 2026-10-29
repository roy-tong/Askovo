# 数据契约

SURE 的所有判断都建立在文件契约上。目录固定、字段可追溯，才能被 `audit` 和下游复用。

## 目录

```text
study/
├── study.json                    决策、范围、假设、门槛、连接器配置
├── 01-sources/
│   ├── source-plan.csv           证据角色 × 来源 × 路线 × 目标量
│   ├── feasibility.json          plan 生成：平台可行性、配额、准入前提
│   ├── tasks.md                  plan 生成：采集任务
│   ├── *-routes.csv              平台路线模板
│   ├── collection-manifest-template.json
│   └── manifests/                每次采集的运行清单
├── 02-data/
│   ├── evidence.jsonl            证据记录（一行一条）
│   ├── raw/                      原始记录 / connector envelope
│   └── processed/                stages 产物
├── 03-codebook/
│   ├── codebook.csv              编码表
│   └── gold-set.jsonl            人工金标（用于校准）
├── 04-findings/
│   ├── signals.json              signals 生成
│   ├── demand-judgments.json     需求判断台账
│   └── lexicon-yield.json        命名前研究产物
├── 05-audit/
│   ├── audit.json                audit 生成
│   ├── audit.md                  audit 生成
│   ├── latest.json               check --write-report 生成
│   └── latest.md
└── 06-report/
    └── report.md                 report 生成
```

生成物（`05-audit/latest.*`、`06-report/`、`04-findings/signals.json`）不应提交到代码仓库。

## study.json

最小结构：

```json
{
  "study_id": "ai-glasses-2026",
  "title": "AI 眼镜用户不满",
  "method_version": "1.12.0",
  "decision": {
    "question": "是否值得为远程协作做一款新品",
    "owner": "产品负责人",
    "deadline": "2026-11-30",
    "options": ["做", "不做", "先做配件"],
    "minimum_evidence": ["E3 方案接受", "E4+ 付费意图"]
  },
  "scope": {
    "target_users": ["一线维修工程师"],
    "markets": ["overseas"],
    "languages": ["en"],
    "source_time_window": {"start": "2025-10-01", "end": "2026-09-30"},
    "unit_of_observation": "feedback_record",
    "allowed_sources": ["reddit", "x", "youtube"],
    "prohibited_inferences": [
      "Do not infer population prevalence from convenience samples",
      "Do not treat records as unique people without lawful identity resolution"
    ]
  },
  "hypotheses": [
    {"id": "H1", "statement": "…", "falsified_if": "…"}
  ],
  "quality_gates": {
    "min_evidence_records": 1000,
    "required_corpus_roles": ["direct_solution", "open_scene", "substitute_rejector", "post_purchase_support", "control"],
    "max_source_family_share": 0.65,
    "max_normalized_duplicate_rate": 0.02,
    "require_counter_evidence_for_validated": true
  },
  "source_adapters": { "reddit": { "enabled": true, "…": "…" } },
  "stopping_rules": ["…"],
  "restart_rules": ["…"]
}
```

`method_version` 由 `plan` 自动写入当前运行时版本；`{{method_version}}` 是模板占位符，不应留在成稿里。

## evidence.jsonl

一行一条，必填字段：

| 字段 | 说明 |
| --- | --- |
| `record_id` | 稳定唯一 id |
| `user_role` | 用户角色 |
| `scene_trigger` | 触发场景 |
| `task_outcome` | 想完成的任务/结果 |
| `current_substitute` | 当前替代方案 |
| `friction_cost` | 摩擦与成本 |
| `consequence` | 后果 |
| `evidence_level` | `E0`–`E5`（含 `E4+` / `E4-`） |
| `evidence_basis` | 为什么是这个等级 |
| `corpus_role` | 五类证据角色之一 |
| `source_family` | 来源族（必须出现在 source-plan） |
| `source_ref` | 来源引用 |
| `normalized_text_hash` | `sha256:...`，用于去重 |

可选：`collection_run_id`、`connector_id`、`connector_revision`、`lexicon_terms`、`grounding_path`。

## demand-judgments.json

一条判断是一个对象：

| 字段 | 说明 |
| --- | --- |
| `id` | 判断 id |
| `title` | 一句话结论 |
| `user_role` / `scene` / `task` | 必须与证据一致 |
| `current_substitute` / `friction` / `consequence` | 问题链叙事 |
| `solution` / `acceptance_conditions` | 方案与接受条件 |
| `problem_evidence_ids` | 需要 `E1/E2` |
| `solution_evidence_ids` | 需要 `E3` |
| `commercial_evidence_ids` | 需要 `E4+` / `E5` |
| `counter_evidence_ids` | 反证 |
| `status` | `hypothesis` / `needs-validation` / `validated` / `rejected` / `deprioritized` |
| `confidence` | `low` / `medium` / `high` |
| `gaps` | 已知缺口 |
| `next_test` | 最便宜的补证 |

`sure audit` 会逐条核对引用是否存在、链条是否闭合；声称 `validated` 但缺链的会标为 `exceeds_evidence`。

## signals.json

由 `sure signals` 生成，包含：

- `record_count`、`unique_record_ids`、`normalized_duplicate_rate`
- `evidence_levels`、`corpus_roles`、`role_level_matrix`
- `source_families`、`dominant_source_family_share`
- `time_range`
- `chain_readiness`
- `gates`（实际值与门槛对照）

## audit.json

由 `sure audit` 生成，关键字段：

| 字段 | 说明 |
| --- | --- |
| `status` | `pass` / `fail` |
| `checks[]` | 每条门禁的 id、状态、detail、stage |
| `signals` | 同 signals.json |
| `claims[]` | 每条判断的 `verdict`、`max_evidence_level`、`chains`、`reasons` |
| `summary` | 记录数、重复率、主导来源、可支持/超出/未定数量 |
| `next_actions[]` | 按优先级排序的补证动作 |
| `version_warning` | study 记录的版本与当前运行时不一致时的警告 |

完整 schema 与字段级约束见 [../skills/user-demand-research/references/data-contract.md](../skills/user-demand-research/references/data-contract.md)。

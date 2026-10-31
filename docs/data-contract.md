# 数据契约

askovo 的所有判断都建立在文件契约上。目录固定、字段可追溯，才能被 `audit` 和下游复用。

## 目录

```text
study/
├── study.json                    决策、范围、假设、门槛、连接器配置
├── 01-sources/
│   ├── source-plan.csv           推理节点 × 证据角色 × 来源 × 路线 × 目标量
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
│   ├── product-reasoning.json    场景→用户→痛点→需求→特性→产品→商业推理链
│   ├── signals.json              signals 生成
│   ├── demand-judgments.json     需求判断台账
│   └── lexicon-yield.json        命名前研究产物
├── 05-audit/
│   ├── audit.json                audit 生成
│   ├── audit.md                  audit 生成
│   ├── latest.json               check --write-report 生成
│   └── latest.md
└── 06-report/
    ├── report.md                 deliver --kind report：产品与商业推理报告
    ├── research-status.md        report：用户研究状态与证据缺口
    ├── product-reasoning.md      chain：主链可读投影
    ├── mrd.md                    deliver --kind mrd：市场研究与分析投影
    ├── prd.md                    deliver --kind prd：需求研究与分析投影
    ├── brd.md                    deliver --kind brd：商业分析投影
    ├── user-ops.md               deliver --kind ops：用户运营投影
    └── postlaunch-tracker.csv    deliver --kind tracker：验收与回流跟踪
```

生成物（`05-audit/latest.*`、`06-report/`、`04-findings/signals.json`）不应提交到代码仓库。

## product-reasoning.json

`do` 自动创建、`askovo chain` 渲染的产品与商业推理主链，是七段产品与商业语义的机器真值。每个新 chain 固定按 `scene → user → pain → need → feature → product → business` 排列；旧版六节点 chain 仍可读取。

chain 字段：

| 字段 | 说明 |
|---|---|
| `id` / `title` | 价值线程标识与标题 |
| `demand_judgment_id` / `context_key` | 与需求判断精确连接；引用证据时必须一致 |
| `status` | `draft` / `hypothesis` / `needs-validation` / `decided` / `rejected` / `deprioritized` |
| `confidence` | `low` / `medium` / `high`，不是统计置信度 |
| `supporting_states` | 独立的 delivery / outcome / causal 状态及 release、metric、experiment 引用 |
| `nodes` | 下述七节点对象 |
| `alternative_explanations` | 其他解释或替代方案；decided 至少一条 |
| `counter_evidence_ids` | 已在需求判断登记的反证子集 |
| `human_review` | 语义复核、复核人、说明、风险接受；不是自动认证 |
| `prioritization` | 需求优先级方法、因素、负责人、日期和理由 |
| `change_log` | 变更依据、受影响引用、影响、决策和投影同步状态 |
| `gaps` / `next_test` | 当前缺口与下一项最能改变决策的验证 |

每个节点必须包含：

- `statement`：这一节点的明确判断；
- `rationale`：为什么由上一节点推导到这一节点；
- `status`：`hypothesis` / `needs-validation` / `validated` / `rejected` / `deprioritized`；
- `evidence_ids`：直接支撑该节点的证据；
- `assumptions`：尚未验证的推理假设。

专属字段：scene 使用 `trigger/environment/task_context`；user 使用 `role/state/decision_role`；pain 使用 `current_substitute/friction_cost/consequence`；need 使用 `desired_outcome/constraints/measure`；feature 使用 `capability/acceptance_conditions/alternatives_considered`；product 使用 `form/scope/non_goals/acceptance_criteria`。

business 使用 `market_definition`、`geographies`、`time_window`、`included_markets`、`excluded_markets`、`target_segment`、`segments`、`payer`、`positioning`、`revenue_model`、`pricing_hypothesis`、`pricing`、`channels`、`competitive_alternatives`、`cost_drivers`、`market_estimates`、`unit_economics_inputs`、`success_metrics`、`non_goals` 和 `gate`。市场规模条目必须有总体定义、时间窗、单位、方法、假设；有数值时还要有公式和来源。价格、支付意愿、交易与续约分层记录，未知保留 `null` 并登记缺口。

节点证据必须是 linked judgment 已登记证据的子集：scene/user/pain/need 只能引用 problem 或 counter；feature 只能引用 solution 或 counter；product 只能引用 solution、commercial 或 counter；business 只能引用 commercial 或 counter。节点 validated 还需满足对应 E-level；decided chain 要求七节点 validated、linked judgment validated、反证与替代解释齐全，并要求商业门与优先级记录。嵌套引用同样受约束：`segments[].evidence_ids` 可用 problem/commercial/counter 中与细分相关的已登记证据，`pricing[].evidence_ids` 可用 solution/commercial/counter，`change_log[].reason_evidence_ids` 必须是该 judgment 四个证据组之一的已登记证据；三者都必须存在且 context_key 一致。

`decided` 只记录当前产品/商业选择，不表示发布就绪、实验因果或商业成功。完整语义见[产品推理主链](product-reasoning.md)。

## study.json

最小结构：

```json
{
  "study_id": "ai-glasses-2026",
  "title": "AI 眼镜用户不满",
  "method_version": "2.0.1",
  "product_reasoning_version": "2.0",
  "product_reasoning": {
    "flow": ["scene", "user", "pain", "need", "feature", "product", "business"],
    "primary_artifact": "04-findings/product-reasoning.json"
  },
  "delivery": {
    "audiences": ["product_manager", "user_researcher", "user_operations", "market_researcher", "market_analyst", "requirements_analyst", "business_analyst"]
  },
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
| `context_key` | 决策上下文键；被 `validated` 判断引用时必填且必须与判断一致 |
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
| `context_key` | `validated` 必填；同一角色/场景/任务决策上下文的稳定键，所有引用证据必须一致 |
| `title` | 一句话结论 |
| `user_role` / `scene` / `task` | 必须与证据一致 |
| `current_substitute` / `friction` / `consequence` | 问题链叙事 |
| `solution` / `acceptance_conditions` | 方案与接受条件 |
| `problem_evidence_ids` | 需要 `E1/E2`；主链上 need 节点升 `validated` 还须至少含一条 `E2`（观察到的替代/绕行/失败行为），仅 `E1` 陈述停在 `needs-validation` |
| `solution_evidence_ids` | 需要 `E3` |
| `commercial_evidence_ids` | 需要 `E4+` / `E5` |
| `counter_evidence_ids` | 反证 |
| `status` | `hypothesis` / `needs-validation` / `validated` / `rejected` / `deprioritized` |
| `confidence` | `low` / `medium` / `high` |
| `gaps` | 已知缺口 |
| `next_test` | 最便宜的补证 |

`askovo audit` 会逐条核对引用是否存在、链条是否闭合；声称 `validated` 但缺链的会标为 `exceeds_evidence`。

## signals.json

由 `askovo signals` 生成，包含：

- `record_count`、`unique_record_ids`、`normalized_duplicate_rate`
- `evidence_levels`、`corpus_roles`、`role_level_matrix`
- `source_families`、`dominant_source_family_share`
- `time_range`
- `chain_readiness`
- `gates`（实际值与门槛对照）

## audit.json

由 `askovo audit` 生成，关键字段：

| 字段 | 说明 |
| --- | --- |
| `status` | `pass` / `fail` |
| `checks[]` | 每条门禁的 id、状态、detail、stage |
| `signals` | 同 signals.json |
| `claims[]` | 每条判断的 `verdict`、`max_evidence_level`、`chains`、`reasons` |
| `summary` | 记录数、重复率、主导来源、可支持/超出/未定数量 |
| `next_actions[]` | 按优先级排序的补证动作 |
| `version_warning` | study 记录的版本与当前运行时不一致时的警告 |

完整 schema 与字段级约束见 [../skills/askovo/references/data-contract.md](../skills/askovo/references/data-contract.md)。

## route.json（v1.13 单入口路由）

`study.json` 之外单独保存，便于审计“为什么选这个方法”：

| 字段 | 说明 |
|---|---|
| `query` | 原始需求 |
| `domain` / `domain_label` | software/hardware/consumer/automotive/mobile |
| `stage` / `stage_label` | discovery…audit |
| `intent` | route/plan/instruments/sources/collect/analyze/audit/deliver |
| `confidence` / `domain_scores` | 路由置信度与各领域命中分 |
| `risk_flags` | flag + 命中词 |
| `safety_gate` | `clear` / `review` |
| `recommended_methods` | 方法、证据形式、不能证明什么 |
| `alternatives` | 替代方法及不首选原因 |
| `platform_preview` | 平台适配分、可用性、批量能力 |
| `next_commands` | 下一步命令 |

`askovo do` 还会写 `01-sources/platform-plan.json`，保存推荐平台、适配分、访问方式、限制与阻断平台。

## platform-catalog 与 platform manifest

`assets/platform-catalog.json` 记录平台可用性：

- `access_modes`：official_api / authorized_export / historical_dataset / first_party / research_api / licensed_provider
- `auth`、`bulk`、`freshness`
- `decision`：supported / limited / blocked
- `limits`、`bias`、`notes`

每次采集写 `01-sources/manifests/<run_id>.json`：

| 字段 | 说明 |
|---|---|
| `run_id` / `platform` / `query` | 运行标识 |
| `adapter` / `access_basis` / `auth` | 用了什么通道 |
| `requested` / `reached` / `written` | 配额与产出 |
| `raw_file` | 原始记录路径 |
| `limits` / `bias` | 本次已知限制 |
| `started_at` / `finished_at` | 运行时间 |

## normalized.jsonl（跨平台归一化）

`02-data/normalized.jsonl` 一行一条，最小字段：

| 字段 | 说明 |
|---|---|
| `record_id` | 平台前缀稳定 id，如 `github:123`、`reddit:abc` |
| `platform` | 平台 id |
| `source_url` / `author_hash` | 引用与去标识作者 |
| `created_at` / `collected_at` | 原始时间/采集时间 |
| `title` / `text` / `rating` | 内容 |
| `query` / `run_id` | 来源查询与运行 |
| `source_family` / `evidence_form` / `claim_type` | 证据归类 |
| `normalized_text_hash` | 去重键 |
| `language` | 语言（未知写 unknown） |

`import` 的 `02-data/evidence.jsonl` 与归一化记录可以并存；交付与分析会按 `record_id` 去重合并。

## analysis.json（跨平台描述性分析）

| 字段 | 说明 |
|---|---|
| `records` | 去重后记录数 |
| `by_platform` / `by_claim_type` / `by_evidence_form` | 分布 |
| `by_month` | 时间分布 |
| `avg_text_length` | 平均长度 |
| `top_terms` | 高频候选主题（不是结论） |
| `question_matches` | 与问题匹配的片段 |
| `boundary` | 描述性统计、不可推断总体/因果 |

分析结果只用于发现候选主题与缺口，不替代编码、证据分级和人工判断。

## queue.db（v1.14 采集队列）

`01-sources/queue.db` 是 SQLite 队列：

| 表 | 字段/用途 |
|---|---|
| `jobs` | id、platform、query、limit、fixture/cdp_url/url/ack_terms、status、attempts、max_attempts、next_at、lease_until、worker_id、last_error、record_count |
| `rate_state` | platform、next_at；用于跨 worker 的按平台限速 |

状态：`pending` → `running` → `done` / `retry` → `failed`。租约过期的 `running` 会被回收；`retry` 按指数退避。`queue status` 输出按状态/平台的计数与最近错误。

## CDP manifest 字段

CDP 采集额外记录：

- `adapter: cdp`
- `access_basis: cdp_authorized_visible_page`
- `auth: user_browser_session`
- `source_url`、`cdp_base`
- `terms_note`：可见页面、无挑战绕过、平台条款可能限制
- 命中挑战页时返回 `status: challenge`，不写入记录

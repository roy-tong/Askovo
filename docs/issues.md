# Issue → 用户任务/需求结构化（Issues）

> 公开 Issue 导出 → 机器候选 → **人工**接受 → 现有 `evidence → demand-judgments → product-reasoning` 主链。它不新建第二套证据链，也不把「请加按钮」写成「真实用户强需求」。

`askovo issues` 解决的是「只有一堆公开 issue，怎么变成可复核的用户任务/需求判断」。它是 A-01 证据资格模型与 A-02 决策任务的下游：候选只描述导出里写了什么，接受动作才把它写进 canonical 链。

**零网络**：只读本地授权导出（`gh issue list --json …` 形态的 JSONL/JSON）。未来接真 connector 的接口位置是 `issue_structuring.LIVE_CONNECTOR_ENABLED`，**永久为 False**，直到有评审通过的 GitHub 连接器与其访问依据。

## 1. 它做什么

1. **快照**：把授权导出复制进 `02-data/raw/issues/`，记录 SHA-256、获取依据、保留规则与选择偏差（A16）。
2. **规范化**：复用 `sure_engine._normalize_platform_record`，写 `02-data/normalized.jsonl`，与 `collect`/`analyze`/`audit` 同一形状。
3. **抽取候选**：规则法（非模型）产出 PRD 逐字要求的 13 个字段，并标注 `extraction`/`severity_basis` 等派生依据。
4. **聚类**：只合并主题，不消除来源；支持数与反证数分开计数。
5. **人工编辑/接受/拒绝**：接受时写一条 canonical evidence + 一条 demand judgment + 一条 product-reasoning 链，并留可追溯记录。

## 2. 它不做什么

- 不联网、不调 API、不读私有仓库；`visibility != public` 的行直接丢弃并计数，正文不落盘（A18）。
- 不分配证据等级：接受人可以指定，但被 `claim_kind` 封顶（A14）。
- 不把候选当证据：`status: proposed` 的候选不进入审计计数。
- 不自动把候选写进判断：`accept` 必须带具名的人（`AUTH_REQUIRED`）。
- 不用多数票压过反证（A17）。

## 3. 命令

```bash
# 1) 人确认导出可用（快照 + 规范化）；不联网
askovo issues import ./study --file issues.jsonl --authorized-by "research-lead" \
  --since 2026-08-01 --label bug

# 2) 抽取机器候选
askovo issues extract ./study --question "下一版先修哪些解析问题"

# 3) 复核
askovo issues list ./study --claim-kind feature_request
askovo issues status ./study
askovo issues report ./study

# 4) 人工编辑（可追溯）
askovo issues edit ./study --candidate IC-01 --by "product-owner" \
  --set user_role="使用该 CLI 的开发者"

# 5) 接受：写 evidence + demand judgment + product-reasoning 链
askovo issues accept ./study --candidate IC-01 --by "product-owner" \
  --context-key nested-log-parse --judgment-id D03 --evidence-level E2

# 6) 拒绝：写清理由，候选不进入主链
askovo issues reject ./study --candidate IC-02 --by "product-owner" \
  --reason "单一自述，不足以为判断"
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 已导入/已抽取/已记录人工决定（`accepted` 不等于 `validated`） |
| 2 | 输入、来源或语义门禁拒绝（`POLICY_DENIED` / `INPUT_REQUIRED` / `UNSUPPORTED_SCOPE`） |
| 4 | 缺少具名授权人/复核人（`AUTH_REQUIRED`） |

## 4. 机器候选的 13 个字段

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `issue_ref` | `html_url` | `github:owner/repo#123`，可回溯到原始 issue |
| `author_ref` | `user.login` | `github:<login>`；是**账号**引用，不是已证明的自然人 |
| `created_at` / `updated_at` | issue 字段 | 原样保留，便于时间窗复核 |
| `user_task` | 正文首句（第一人称 + 任务/后果） | 抽不到就写 `unknown`，**不**用方案请求顶替 |
| `trigger` | 正文 `when/after/every/当/每次…` 句 | 触发条件 |
| `current_workaround` | 正文 `by hand/manually/手动/重试…` 句 | 当前替代做法 |
| `failure_consequence` | 正文 `fail/breaks/lose/failed/失败/丢失…` 句 | 失败后果 |
| `requested_feature` | 正文 `please add/请加/希望增加…` 句 | 方案请求，不是需求 |
| `severity_candidate` | `claim_kind` + 严重度标签 | `critical\|high\|medium\|low\|unknown`，**不写数字** |
| `source_quote_span` | 正文句子的字符区间 | `{start, end, text}`，`source_text[start:end] == text` 恒成立；抽不到就是 `null` |
| `confidence_basis` | 是否含可复现文本 | `reproducible_text\|self_report_text\|unverified` |
| `representativeness_warning` | 确定性模板 | 每条候选必带，说明样本不能代表总体 |

附加字段（不是 PRD 13 项，但影响可复核性）：`claim_kind`、`severity_basis`、`demand_claim`、`disposition`、`support_count`、`counter_count`、`majority_wins`、`counter_evidence`、`source_refs`、`source_availability`、`source_snapshot`、`maintainer_feedback`、`selection_bias`、`evidence_cap`、`status`、`edits`、`accepted`、`boundary`。

## 5. 语义规则（写在实现里）

| 规则 | 实现 |
| --- | --- |
| 同一登录 10 条 = 1 名观测用户 | `observation.observed_users` 按 `author_ref` 去重；`records_per_author` / `max_records_per_author` 单列 |
| 同一 issue 多评论 ≠ 多用户 | 评论只计入 `comment_count` / `comment_authors`，不进入 `observed_users` |
| 多个账号 ≠ 多个独立的人 | `identity_basis: login_only`，`identity_basis_note` 明说未证明是不同的人 |
| 请求方案 ≠ 强需求 | `claim_kind: feature_request` → `demand_claim: none`、`severity_candidate: unknown`、`evidence_cap: E1`；接受 E2 被 `POLICY_DENIED` 拒绝 |
| 无可复现文本 → unverified | 正文为空 → `confidence_basis: unverified`、`source_quote_span: null`、`claim_kind: unknown` |
| 来源被删 → 保快照 | 快照 + `sha256` + `acquisition_basis` + `retention_rule` + `deleted_records`；候选 `source_availability: snapshot_only` |
| 一条反证不被淹没 | 任一反证 → `disposition: challenged`、`majority_wins: false`，支持/反证分别计数 |
| 私有内容不外扩 | 快照按字段白名单构建；`visibility != public` 直接丢弃；`private_note` 等字段永不落盘 |
| 维护者反馈单列 | `author_association ∈ {MEMBER, OWNER, COLLABORATOR}` → 独立候选 + `maintainer_feedback` 列表，不计入用户 |
| 四类结论不混成一个 `type` | `claim_kind ∈ {bug_reproduction, subjective_complaint, feature_request, observed_behavior}`，无文本时为 `unknown` |

## 6. 接受后写了什么

| 产物 | 内容 |
| --- | --- |
| `02-data/evidence.jsonl` | 一条 canonical evidence（`EVIDENCE_REQUIRED` 全字段），`record_id` 取自候选来源，`context_key` 由接受人指定 |
| `04-findings/demand-judgments.json` | 一条 judgment（`JUDGMENT_REQUIRED` 全字段），`problem_evidence_ids` 指向该 evidence（仅 `observed_behavior`/`bug_reproduction`） |
| `04-findings/product-reasoning.json` | 一条七节点链（`status: hypothesis`），`demand_judgment_id` 指向该 judgment，scene/user/pain/need 可引用该 evidence |
| `04-findings/issue-acceptance.jsonl` | 追加式审计轨迹：`candidate_id`、`accepted_by`、`accepted_at`、`edits`、`evidence`、`judgment_id`、`reason` |
| `04-findings/issue-candidates.json` | 候选状态 `accepted`/`rejected` + `accepted`/`rejected` 引用块 |

接受是幂等的：重复 `accept` 不会写第二条 evidence 或第二条 judgment。`accepted` 只表示「候选进入了主链」，**不**表示 `validated`；`askovo audit` 仍会按证据等级与上下文门复核。

## 7. 选择偏差

`import --since/--label` 会收窄样本。此时 `issue-candidates.json` 的 `selection_bias` 非空，并写清「样本被限制到什么窗口/标签、排除了多少非公开行、不能代表全部用户」。**没有过滤时为空字符串**——不制造不存在的偏差声明。

## 8. 边界

- 记录数不是用户数；登录数也不是人口数。
- 公开 issue 中的要求不是已证实的实际使用行为；`feature_request` 最高只到 E1。
- 快照证明「导入时导出里有什么」，不证明来源仍存在、作者是不同的人、样本代表总体。
- 接受只完成「写入主链」，语义复核、证据定级与业务签收仍由人负责。
- 并发：同一 study 的 `import`/`extract`/`accept` 不做跨进程加锁（A-02 的 decide 任务锁不覆盖这里）；并发运行以最后一次写入为准。

## 9. 验收对照（AC A13–A18）

| AC | 落实 |
| --- | --- |
| A13 | 同一登录 10 条 → `record_count: 10`、`observed_users: 1`、`max_records_per_author: 10`；同一 issue 12 条评论 → 仍 `observed_users: 1` |
| A14 | 「请加按钮」→ `claim_kind: feature_request`、`severity_candidate: unknown`、`demand_claim: none`、`evidence_cap: E1`；接受 E2 返回 `POLICY_DENIED` |
| A15 | 正文为空 → `confidence_basis: unverified`、`source_quote_span: null`、`claim_kind: unknown` |
| A16 | 来源 `state: deleted` → 快照 + `sha256` + `acquisition_basis` + `retention_rule` + `deleted_records` 保留，候选 `source_availability: snapshot_only` |
| A17 | 5 支持 + 1 反证 → `disposition: challenged`、`majority_wins: false`，支持/反证分别计数 |
| A18 | `visibility: private` 行被丢弃并计数；`private_note` 等白名单外字段永不落盘（全 study 文本扫描为证） |

## 10. 与其他文档的关系

- [数据契约](data-contract.md)：canonical evidence/judgment 字段与写入权。
- [研究闭环](research-loop.md)：缺口驱动的采集与候选证据；`issues` 是同一候选层的 issue 专用投影。
- [一问题研究执行器](decide.md)：A-02 的任务编排；A-03 的接受结果可作为它的输入证据。
- [CLI 参考](cli.md)：命令、参数与退出码总表。

## Write integrity (A-07)

Accepting a candidate touches five artifacts: the evidence store, the demand
judgment array, the seven-node chain, the candidate document and the acceptance
trail. They are written as one transaction:

- a journal at `04-findings/.write-journal.json` records the target of every
  write, the old SHA-256 and the new SHA-256, and is fsynced before the first
  visible change;
- each file is installed with an atomic rename; an `OSError` in the middle rolls
  the already-installed files back to their recorded old bytes;
- a canonical file that will not parse is refused (`INTERNAL_ERROR`) before any
  write happens — a corrupt file is never read as "empty" and then overwritten;
- any entry point (`import`, `extract`, `list`, `edit`, `accept`, `reject`,
  `status`, `report`) first resolves a journal left by an interrupted accept,
  so a half-written study can never look like a finished one;
- `askovo issues recover <study>` reports the transaction (dry-run) and
  `--apply` replays it; a file edited by hand after the crash is a conflict, not
  something to overwrite, and the journal stays for a human to resolve;
- a cross-process lock (`04-findings/.write.lock`) serializes writers, so two
  simultaneous accepts produce one judgment, not a lost update.

# 增量研究 Delta（Delta）

> 同一个问题、同一个 study，新素材进来后**只追加、不覆盖**：新增/变更/删除三条来源差异、受影响节点、反证影响、是否需要重审。历史快照永不改写，已批准决定永不被自动推翻。

`askovo delta` 是 A-03（Issue 结构化）与 A-04（Decision Brief）的增量层：它比较两次授权导出的**来源身份 + 更新时间**，产出 `04-findings/deltas/vNNN-<hash>/` 不可变快照与 `06-report/decision-delta.md`。它只读 canonical 链，写回只发生在派生目录。

## 1. 它做什么

1. **按来源身份比对**：`source_id`（`github:<issue id>`）+ `updated_at`（+ 内容 hash 兜底）→ `added` / `changed` / `deleted` 三类。不做"内容相似度"猜测。
2. **append-only 快照**：每次真实变化生成新版本目录（`v001-<sha12>`、`v002-<sha12>`…），旧版本逐字节保留。被删除/被编辑的记录仍能从旧版本读到原文 + hash + 获取权说明（A25）。
3. **四块 `decision_delta.md`**：新增证据、已影响节点（哪些 canonical 节点引用了变化的记录）、反证影响、建议是否重审。每条都能点到具体 `record_id` 与旧版本路径。
4. **门禁**：新反证只把 `needs_re_review` 置真，**不**改写已批准的 `DecisionSnapshot`（A27）。
5. **降级可读**：来源不可达/无权限时，仍能 `show` 上次可用结果，但整份投影标 `stale` + 原因 + 上次成功时间（A28）。

## 2. 它不做什么

- 不覆盖历史：版本目录一旦写出就不再重写；`v001` 的 `evidence.jsonl` 在任何后续同步后都字节不变。
- 不自动批准、不自动推翻：`decision_record_mutated` 恒为 `false`；`delta approve` 只记录**声明式**批准（`identity_basis: declaration_only`），不构成业务批准证明。
- 不把编辑当新增：作者改名、issue 重写都不会变成新的独立用户或新证据（A26）。
- 不把"无变化"说成"生成了新版本"：重复同步是 no-op，版本号与索引都不动（A24）。
- 不联网：只读本地授权导出，`LIVE_CONNECTOR_ENABLED` 仍为 `False`。

## 3. 命令

```bash
# 1) 同步授权导出（人工确认数据权利）；无变化时不生成新版本
askovo delta sync ./study --file issues-v2.jsonl --authorized-by "research-lead"
askovo delta sync ./study --file issues-v2.jsonl --authorized-by "research-lead" --label bug

# 2) 查看差异（默认最新版本；可指定版本；可输出 Markdown）
askovo delta show ./study
askovo delta show ./study --version v001-1c42dd5a8a0f --format md
askovo delta status ./study

# 3) 人工记录批准（DecisionSnapshot，声明式）
askovo delta approve ./study --by "product-owner" --approval-ref "SIGNOFF-001" \
  --option option-A

# 4) 绑定 decide 任务（A-02 的显式拒绝已由本工单替代）
askovo decide delta A-TASK-1A2B3C4D --workspace ./decide-workspace --since latest-accepted
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 已同步/已读取（`noop: true` 也是成功；`stale` 时 `show` 仍返回 0，见下） |
| 1 | `show`/`status` 读到 `stale` 投影（来源不可达，结果不是最新） |
| 2 | 用法/输入错误（无导出、无快照、版本不存在） |
| 4 | 缺具名授权人/批准人（`AUTH_REQUIRED`） |

## 4. 产物与不可变约定

```
04-findings/deltas/
  index.jsonl                     # 追加式：一行一个版本，永不重写
  state.json                      # 最近检查/成功时间、最近错误、获取依据与保留规则
  v001-<sha12>/                   # 不可变
    evidence.jsonl                # 冻结的来源记录（含 content_hash）
    snapshot.json                 # DecisionSnapshot（PRD §10.2 字段）
    delta.json                    # 该版本的差异文档
    decision_delta.md             # 四块 Markdown
  v002-<sha12>/...
  decision-snapshots/DS-001.json  # 已批准决定（追加式；delta 永不改写）
06-report/decision-delta.md       # 最新差异的可读投影
```

版本号 = `v<序号三位>-<证据快照 sha256 前 12 位>`：内容相同则版本目录必然相同，天然幂等。`index.jsonl` 只追加，`test_index_is_append_only` 断言新索引以旧索引为前缀。

## 5. 差异文档契约（`askovo.decision-delta/1`）

| 字段 | 含义 |
| --- | --- |
| `version` / `supersedes` / `accepted_version` | 当前版本、上一版本、已批准版本的证据快照 hash |
| `has_changes` / `noop` / `message` | 是否有变化；无变化时明确写"无变化" |
| `counts` | `added` / `changed` / `deleted` / `unchanged` / `total` |
| `deletion_basis` | `same_window_export` / `no_previous_snapshot` / `not_asserted`（过滤条件不同时**不**推断删除） |
| `added[]` | `{source_id, issue_ref, author_ref, updated_at, title, content_hash}` |
| `changed[]` | `{source_id, previous_hash, current_hash, previous_updated_at, current_updated_at, fields[], previous_author_ref, current_author_ref, previous_ref}` |
| `deleted[]` | `{source_id, previous_hash, previous_ref, acquisition_basis, retention_rule}` |
| `identity` | `{observed_users, previous_observed_users, new_users[], identity_drift[], identity_basis, note}` |
| `affected_nodes[]` | `{record_id, chain_id, nodes[], why}` |
| `counter_impact[]` | `{record_id, chain_id, issue_ref, why}` |
| `needs_re_review` / `review_basis[]` | 与 `decision_brief.review_signal` **同一个判据** |
| `accepted` / `current` / `differences[]` | 已批准 vs 当前建议；差异按 `kind` 分类 |
| `decision_record_mutated` | 恒为 `false` |
| `stale` / `reason_code` / `freshness` | 降级可读：`status ∈ {fresh, stale}` + 原因 + 上次成功时间 |
| `source` | `{run_id, file, sha256, authorized_by, filters, skipped_private, selection_bias}` |
| `digest` | 去掉 `generated_at` 后的稳定摘要（可复现） |
| `boundary` | 全局边界声明 |

`snapshot.json` 是 PRD §10.2 的 `DecisionSnapshot`：`decision_id`、`study_id`、`question`、`scope`、`hypothesis_ids`、`evidence_snapshot_hash`、`recommendation_snapshot_hash`、`chosen_option`、`approval_ref`、`approved_at`、`next_validation`、`validation_receipts`、`supersedes`、`current_review_status`。**未批准的版本 `approval_ref` 为 `null`**；审批人自填的部分只算声明。

## 6. 验收对照（AC A24–A28）

| AC | 落实 |
| --- | --- |
| A24 | 重复同步 → `noop: true`、`has_changes: false`、版本号与 `index.jsonl` 完全不变、`message` 写"无变化" |
| A25 | 每次变化新建 `vNNN-<hash>/`；旧版本逐字节不变（`test_history_snapshots_are_never_overwritten`）；被删除记录的原文仍可从 `v001/evidence.jsonl` 读到；被编辑记录保留旧 body |
| A26 | 同一 `source_id` 的编辑只算 `changed`；`author_id` 用稳定 `user.id`（`github-user:<id>`），有稳定 id 时改名不算漂移；无稳定 id 时记 `identity_drift` 且 `observed_users` 不增长 |
| A27 | 新反证 → `needs_re_review: true` + `review_basis` + `counter_impact`；`decision_record_mutated: false`；`decision-snapshots/DS-001.json` 的 SHA-256 前后一致；`accepted`/`current`/`differences` 明确列出 current vs accepted |
| A28 | 来源不可达时 `sync` 记错；`show`/`status` 仍返回上次可用快照，`stale: true`、`reason_code: STALE_SOURCE`、`freshness.status: stale`、`last_success_at` 有值，`next_required_action` 要求先恢复来源 |

**A26 的身份归一**：`author_id` 优先取 GitHub `user.id`（改名不影响身份），缺失时退化为 `login:<login>` 并标 `identity_basis: login_only`。观测用户数按**来源**的作者去重，因此一次编辑只会改变来源内容，不会让用户数 +1。

## 7. 与其他文档的关系

- [Issue 结构化](issues.md)：A-03 的导出解析与字段白名单被复用（同一份 `_parse_export` / `_snapshot_row`）。
- [Decision Brief](decision-brief.md)：`needs_re_review` 判据来自 `decision_brief.review_signal`，两处不会各写一遍。
- [一问题研究执行器](decide.md)：`decide delta --since latest-accepted` 是本工单的绑定入口；A-02 的"显式拒绝"已由本工单替代。
- [数据契约](data-contract.md)：canonical 链与写入权；Delta 不新增第二个真相。

## 8. 边界

- Delta 比较的是**导出快照**，不是线上实时状态：`stale` 表示"上次成功之后来源没再确认过"，不表示内容一定变旧。
- 过滤条件（`--since` / `--label`）变化时不推断删除（`deletion_basis: not_asserted`）：缺席可能只是被过滤掉。
- 观测用户数仍是"登录/账号数"，不是人口数；同一人多个账号无法从导出识别。
- 批准是声明式的：`approval_ref` 的身份真实性依赖实际签核机制，CLI 自填人名只算声明。
- 并发：`sync`/`approve` 不跨进程加锁；同一 study 并发同步以最后一次写入为准（内容寻址的版本目录会各自保留，不会互相覆盖）。
- `needs_re_review` 只提示重审，不排序、不推荐新决定；新决定的记录属于人工动作。

# Decision Brief 与 PRD 开发验收投影（Brief）

> 一页决策：问题 → 结论（recommendation）→ 选项 → 证据与反证 → 受限结论 → 不做的选择 → 下一动作 → PRD 验收 → 四态。**只读投影**，不是第二份可编辑真相。

`askovo brief` 把 canonical 七节点主链（`04-findings/product-reasoning.json`）、需求判断（`demand-judgments.json`）、证据（`02-data/evidence.jsonl`）与 `decision_review` 压成一页 `askovo.decision-brief/1`。它只写 `06-report/decision-brief.{json,md}`，**绝不反写** canonical。

## 1. 它做什么

1. **九节一页**（PRD §2.3）：问题/边界/时间窗/负责人、结论、2–5 个同维度选项、支撑证据与反证、受限结论、不做的选择、下一最低成本验证动作、PRD 开发验收清单、四态独立显示。
2. **可追溯**：每条证据带 `record_id` / 源链接 / 采集时间 / 语境 / 资格；每条验收项带 `product-reasoning.json#chains/<id>/nodes/<node>` 引用。
3. **门禁**：引用断裂或输入过期 → `stale`，阻止正式交付，只写诊断草稿。
4. **数字与事实**：数字必须带单位/窗口/来源，否则不予输出并列入 `numbers_without_provenance`；访谈人数、转化率、市场规模没有 canonical 依据时保持 `null`（未知），永不编造。

## 2. 它不做什么

- 不新建可编辑的决策文档：Brief 只读 canonical，写回只发生在 `06-report/`。
- 不分配证据等级、不改判断状态、不把 `decided` 当 `validated`。
- 不给 `confidence` 生造数值概率：排序启发式只写 `heuristic_score`（当前恒为 `null`）且 `calibrated: false`。
- 不替人批准：`approval.approved` 恒为 `false`，`approval_ref` 只来自实际签核机制。
- 不做 A-05 的 `delta`：版本差异、DecisionSnapshot 与 `needs_re_review` 的版本化留给 A-05；本工单只把反证挑战标成"需重审"。

## 3. 命令

```bash
# 一页 Brief（JSON + Markdown 同时写 06-report/）
askovo brief ./study
askovo brief ./study --format md
askovo brief ./study --task A-TASK-1A2B3C4D      # 绑定 decide 任务
askovo brief ./study --output /tmp/brief-out      # 改输出目录

# decide 入口（A-02 的 brief 现在就是同一份 A-04 文档）
askovo decide brief A-TASK-1A2B3C4D --workspace ./decide-workspace --format md
askovo decide result A-TASK-1A2B3C4D --workspace ./decide-workspace
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | Brief 已写出（`partial` 表示仍有缺口，不是失败） |
| 1 | `stale`：引用断裂或输入过期，正式交付被阻止，只写诊断草稿 |
| 2 | 用法/输入错误（无 study、无 canonical 链等） |

## 4. 文档契约（`askovo.decision-brief/1`）

PRD §5 字段逐字保留，并补齐九节与门禁：

| 字段 | 含义 |
| --- | --- |
| `schema` | 恒为 `askovo.decision-brief/1` |
| `task_id` / `study_id` | 绑定的一次决策任务与 study |
| `generated_at` / `source_fingerprint` | 生成时间；四份输入（study / 主链 / 判断 / 证据）的 SHA-256 |
| `canonical_ref` / `canonical_refs` | 唯一真相：`04-findings/product-reasoning.json` 及其同级引用 |
| `artifact_status` | `stale` / `partial`（`ready` 需要已批准决定 + 审计通过 + 无缺口） |
| `reason_code` | `STALE_SOURCE` / `ARTIFACT_PARTIAL` / `null` |
| `diagnostic_only` | `stale` 时为 `true`：只能当草稿看 |
| `stale_reasons[]` | `{code, detail, refs}`，`code ∈ {BROKEN_REFERENCE, INPUT_DRIFT}` |
| `decision_status` | `hold` / `needs_validation` / `needs_review` / `ready` |
| `recommended_option_id` | 只在 `recommend` 时有值，否则 `null` |
| `recommendation` | `{kind, statement, option_id, not_approved: true, heuristic_score, calibrated: false, ranking_basis, confidence, meaning}` |
| `options[]` | 2–5 个，`{id, statement, status, dimensions{user,task,opportunity,cost,risk}, dimensions_basis: chain_level, evidence_ids, counter_evidence_ids}` |
| `evidence[]` / `counter_evidence[]` | `{record_id, source_url, collected_at, context_key, evidence_level, qualification, excerpt, challenge}` |
| `limitations[]` | 样本偏差、不能代表总体、无商业行为证据、禁止推断 |
| `rejected_options[]` | 不做的选择及原因（未选择 ≠ 已被证伪） |
| `verification_actions[]` | `{action, owner, falsified_if, stop_condition, cost, requires, status}` |
| `prd_acceptance` | `{checklist[], undefined, non_goals[], linked_issues[], note}` |
| `states` | `{decision_state, delivery_state, outcome_state, causality_state, independent, note}` |
| `numbers[]` | `{kind, metric, value, unit, time_window, source_ref, formula, population_definition, status, unavailable_reason}` |
| `research_facts` | `{interviews_conducted, conversion_rate, market_size_estimate, basis}`；未知为 `null` |
| `fabrication` | `{invented_facts[], numbers_without_provenance[], checked_numbers, checked_fields[], boundary}` |
| `approval` | `{approved: false, approved_by: null, approval_ref: null, identity_basis: declaration_only, note}` |
| `challenge` | `needs_re_review` 时给出 `{counter_evidence_ids, why, previous_recommendation, previous_decision_state, next}` |
| `gaps[]` / `next_validation[]` | 缺口与验证清单（A-02 兼容字段） |
| `review_status` | `decision_review` 的 `pass` / `needs_work` / `fail` |
| `boundary` | 全局边界声明 |

## 5. 九节与 canonical 的映射

| §2.3 节 | 来源 | 字段 |
| --- | --- | --- |
| 1 问题/边界/时间窗/负责人 | `study.json` | `question.text` / `question.scope.prohibited_inferences` / `question.time_window` / `question.decision_owner` |
| 2 结论 | `business.gate.decision` + 审计判定 | `recommendation.kind` / `decision_status` |
| 3 选项 | `study.decision.options` × 链节点 | `options[].dimensions`（user/task/opportunity 取 user/need/pain 节点，cost 取 `cost_drivers`，risk 取 `non_goals`） |
| 4 证据与反证 | `evidence.jsonl` + A-01 资格 | `evidence[]` / `counter_evidence[]` |
| 5 受限结论 | `scope.prohibited_inferences` + 缺口 | `limitations[]` |
| 6 不做的选择 | 未推荐选项 | `rejected_options[]` |
| 7 下一动作 | `chain.next_test` + 审计失败项 + 链缺口 | `verification_actions[]` |
| 8 PRD 验收 | `feature.acceptance_conditions` / `product.acceptance_criteria` / `product.non_goals` | `prd_acceptance` |
| 9 四态 | `chain.supporting_states` + 批准记录 | `states` |

**A20 的字段一致性**：验收清单的 `source_field` 直接就是 PRD 原字段名（`acceptance_conditions` / `acceptance_criteria`），`source_ref` 固定为 `04-findings/product-reasoning.json#chains/<id>/nodes/<node>`。清单为空时 `undefined: true` 并写明"尚未定义，不是没有验收"。

## 6. `stale` 门禁

| 触发 | code | 后果 |
| --- | --- | --- |
| 链节点/反证/判断引用了 `evidence.jsonl` 中不存在的记录 | `BROKEN_REFERENCE` | `artifact_status: stale`、`reason_code: STALE_SOURCE`、`delivery_state: blocked`、`diagnostic_only: true`、退出码 1 |
| 链关联的 `demand_judgment_id` 不存在 | `BROKEN_REFERENCE` | 同上 |
| canonical 主链在 `05-audit/decision-review.json` 之后被修改 | `INPUT_DRIFT` | 同上 |

`stale` 时 Brief 仍然渲染（诊断草稿），但 `next_required_action` 明确要求先重跑 `askovo review` 修复断链，不得当作正式交付。

## 7. 数字与事实（A22/A23）

- 每个 market estimate / unit-economics 输入都进 `numbers[]`；缺 `unit` / `time_window` / `source_ref` 任一项时 `value` 置 `null` 并写 `unavailable_reason`，同时列入 `fabrication.numbers_without_provenance`。
- `value` 是说明性文本（例如 "Synthetic behavior only"）时不算数字，`value` 置 `null` 并说明；不进入 unprovenanced 列表。
- `success_metrics` 的目标值一律 `null` + `predeclared`：预声明门槛不是已测量结果。
- `research_facts` 只从 canonical 读取；没有就是 `null`。Markdown 不会出现"共访谈 N 位""转化率为 X"这类未来源的断言。
- `heuristic_score` 恒为 `null`，`calibrated` 恒为 `false`：排序启发式不是概率。

## 8. 验收对照（AC A19–A23）

| AC | 落实 |
| --- | --- |
| A19 | 链未引用任何证据或审计无支持判断 → `recommendation.kind: hold`、`decision_status: hold`、`recommended_option_id: null`，没有任何选项被标 `recommended`，`approval.approved: false` |
| A20 | 验收项 `source_field` 与 PRD 原字段一致，`source_node` ∈ {feature, product}，`source_ref` 指回 `product-reasoning.json#chains/<id>/nodes/<node>`；空清单 `undefined: true` |
| A21 | 链上有反证 → `needs_re_review: true`、`decision_status: needs_review`、`challenge.counter_evidence_ids` 列出反证、`counter_evidence[]` 展示原文、`challenge.previous_recommendation` 保留被挑战的建议 |
| A22 | 数字缺单位/窗口/来源时不输出数值并列入 `numbers_without_provenance`；完整数字在 `numbers[]` 中四项齐全；`null` 必带 `unavailable_reason` |
| A23 | `research_facts` 全 `null`、`fabrication.invented_facts: []`、Markdown 无"共访谈/访谈了/转化率为"等断言；`heuristic_score` 不是概率 |

## 9. 边界

- Brief 是投影，不是批准：`decision_status: ready` 也不等于 `decision_approved`；`delivered` 不等于业务成功。
- 选项的五个维度是**链级**取值（`dimensions_basis: chain_level`）：本工单不伪造选项级的独立评估；需要选项级比较时应为每个选项建立独立证据。
- 未选选项的"原因"在没有 DecisionRecord 时是"主链未给出取舍理由"，不是编造的理由。
- 反证挑战只标 `needs_re_review`；版本化差异、`DecisionSnapshot` 与 `delta` 属于 A-05。
- 并发：Brief 生成不跨进程加锁；以最后一次写入为准。

## 10. 与其他文档的关系

- [数据契约](data-contract.md)：canonical 主链与写入权。
- [一问题研究执行器](decide.md)：A-02 的任务编排；`decide brief`/`decide result` 复用本工单的同一份 Brief。
- [决策复盘](cli.md#review决策复盘)：`decision_review` 的六个维度；Brief 直接消费它的检查项。
- [Issue 结构化](issues.md)：A-03 的接受结果会进入 Brief 引用的证据链。

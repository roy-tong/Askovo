# 一问题研究执行器（Decide）

> 一个问题 → 一个受跟踪的研究任务。`askovo decide` 是 `do` + `loop` + `deliver` 之上的**只读编排层**：它登记任务、写研究计划、执行人工已授权的信封、交付带缺口的 partial Decision Brief。它**不**授权、**不**评估、**不**新建第二套判断数据库。

`askovo decide` 解决的是「用户只给了一个问题和授权范围，怎么把它变成一个有状态、可中断、可恢复、不越权的任务」。采集本身没有新通道：仍然走 `research_loop`（`loop plan/authorize/run`）和 `collect_platform`，Design gate、平台策略与 `study.scope.allowed_sources` 全部保留。

## 1. 它做什么

1. **规范化输入**：把 `askovo.decision-task/1` 文档校验成冻结的任务输入；不支持的 `decision_type` / 来源返回解释与建议，不转成貌似成功的任务。
2. **确定交付物与最少角色**：`prioritize_features` 与 `validate_hypothesis` 各自绑定 primary deliverable 与最小角色集，不调用全部 80 个岗位。
3. **绑定或脚手架 study**：复用 study 模板与 canonical 主链（`study.json`、`04-findings/product-reasoning.json`、`demand-judgments.json`）；未提供的上下文保留为假设/占位。
4. **规划一次**：按输入 hash 幂等——同一输入只会有一个 task、一份 study、一份 loop plan。
5. **受门禁执行**：`--run` 只在人工 `loop authorize` 之后推进；decide 自己绝不 authorize、绝不调用 `loop assess`。
6. **投影状态与产物**：C-01 状态字段、预算、缺口、partial Brief、Evidence Index、Validation Backlog 与 canonical 引用。

## 2. 它不做什么

- 不自授权：`--run` 遇到未授权的信封只报告 `AUTH_REQUIRED` 与下一步命令，不读取任何记录。
- 不自动评估：loop 候选保持 `status: proposed`、`proposed_evidence_level: null`；只有人工 `loop assess` 能关闭缺口。
- 不编造结论：缺数据时 `artifact_status: partial` 并逐条列缺口；`decision_state` 永远是 `not_approved`。
- 不把 `delivered` / `brief_ready` 当成 `decision_approved` 或 `hypothesis_validated`。
- 不访问私有仓库、不走被目录阻断的来源、不用登录态或浏览器自动化绕过策略。

## 3. 命令

```bash
# 1) 登记 + 规划（默认 dry-run：只写计划，不读一条记录）
askovo decide start --input task.json --study ./study
askovo decide "下一版先修哪些问题" --repo owner/repo --approved-by owner

# 2) 人工授权信封（唯一能解锁采集的步骤，必须由具名的人执行）
askovo loop authorize ./study --by "researcher-name"

# 3) 恢复并推进（幂等：同一输入不会重复导入，也不会重采已完成数据）
askovo decide start --task A-TASK-1A2B3C4D --run --workspace ./decide-workspace

# 4) 查看状态（C-01 字段：next_actor / next_required_action / blocked_reason_code …）
askovo decide status A-TASK-1A2B3C4D --workspace ./decide-workspace

# 5) 取结果：partial Brief + 证据索引 + 验证清单 + canonical 引用
askovo decide brief A-TASK-1A2B3C4D --workspace ./decide-workspace --format md
askovo decide result A-TASK-1A2B3C4D --workspace ./decide-workspace

# 6) 取消：之后不再读取、不再有外部效果
askovo decide cancel A-TASK-1A2B3C4D --by owner --workspace ./decide-workspace

# 7) 专家入口（A-02 显式拒绝，A-04 交付）
askovo decide review A-TASK-1A2B3C4D --by product-owner   # exit 2, UNSUPPORTED_SCOPE
askovo decide delta A-TASK-1A2B3C4D --since latest-accepted # exit 2, UNSUPPORTED_SCOPE
```

`--workspace` 缺省为 `$ASKOVO_DECIDE_HOME` 或 `./askovo-decide`；`--study` 缺省时在 `studies/<task_id>/` 下从模板脚手架一份。

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 任务已登记/已规划/已推进，状态合法（含 `needs_input`、`interrupted`、`review_required`） |
| 2 | 输入、权限、来源或状态错误；stdout 是带 `reason_code` 的 JSON 拒绝，不是成功文档 |

## 4. 输入契约（PRD §2.2）

```json
{
  "schema": "askovo.decision-task/1",
  "question": "下一版应该优先处理哪些日志解析问题？",
  "product": {"kind": "github_repository", "repo": "owner/repo"},
  "decision_type": "prioritize_features",
  "audience": {"description": "使用该 CLI 的开发者", "confidence": "declared"},
  "source_scope": {"issues": true, "discussions": false, "updated_since": "2026-08-01",
                   "fixture": "01-sources/authorized/export.jsonl"},
  "authorization": {"approved_by": "owner", "allowed_sources": ["github"], "max_records": 200},
  "deadline": "2026-12-01",
  "delivery": {"primary": "decision_brief", "secondary": ["evidence_index"]}
}
```

- 第一阶段 `decision_type` 只支持 `prioritize_features` / `validate_hypothesis`；其他类型返回 `UNSUPPORTED_SCOPE` 并列出支持项与后续工单建议。
- `authorization.approved_by` 与 `authorization.allowed_sources` 必须同时存在，否则任务停在 `needs_input`（`AUTH_REQUIRED`）并给出可执行的人工导入任务。**这是声明，不是授权**：真正的采集门仍是 `loop authorize`。
- `source_scope.fixture` 是离线授权导出。**decide 自己脚手架 study 时**会被复制进 `01-sources/authorized/` 并登记到 `study.research_loop.fixtures`（study 拥有自己的快照；`research_loop.eligible_sources` 只接受 study 内的 fixture）。**`--study` 绑定时**以被绑定 study 自己的 `research_loop.fixtures` 为准，decide 不会改写别人的 study 文件；若该 study 没有可用来源，任务停在 `needs_input` 并列出 import tasks。
- 任务级 `source_scope.fixture` 同时也是「这个任务自己声明了可执行离线路线」的判据：声明了就在人工授权前停在 `scoped`（投影 `AUTH_REQUIRED`），没声明则直接 `needs_input`（`AUTH_REQUIRED` + 导入任务）。
- `--mode discover|validate` 是 PRD §2.4 的研究模式别名，映射到 `prioritize_features` / `validate_hypothesis`；`optimize` 返回 `UNSUPPORTED_SCOPE`。

## 5. 状态与原因码（C-01 映射）

产品层状态是 loop 状态的投影，不替换任何 canonical 结构：

```
created → scoped → collecting → analyzed → review_required → brief_ready → delivered
异常：needs_input | blocked | interrupted | cancelled
```

| 产品状态 | 含义 | 典型下一个动作 |
| --- | --- | --- |
| `created` | 任务已登记 | 重新 `decide start` 完成规划 |
| `scoped` | 计划已写、等待人工授权；**不是**业务完成 | `loop authorize` → `start --run` |
| `collecting` | 正在执行已授权信封 | 等待本轮结束 |
| `analyzed` | 本轮采集与分析完成 | 人工语义复核 |
| `review_required` | 候选证据等待人工定级 | `loop assess` |
| `brief_ready` | partial Brief 已写出 | 业务方阅读并决定 |
| `delivered` | 合同定义的交付物已产生 | 验收结果；不等于 `decision_approved` |
| `needs_input` | 缺授权/来源/文件 | 见 `next_required_action` 的 import tasks |
| `blocked` | 被策略或来源硬门禁拒绝 | 排查后重建任务 |
| `interrupted` | 上一动作结果未知，必须 reconcile | 检查 journal 后显式重规划 |
| `cancelled` | 已取消，不再读取 | 新问题新建任务 |

原因码取自 C-01 §3 注册表。decide 实际会发出：`INPUT_REQUIRED`（缺问题/文件/日期等事实）、`AUTH_REQUIRED`（缺授权或来源）、`REVIEW_REQUIRED`（候选待人工定级）、`UNSUPPORTED_SCOPE`（决策类型、来源或专家入口超出本工单）、`POLICY_DENIED`（取消后重跑、信封超出声明来源）、`ARTIFACT_PARTIAL`（Brief 有缺口）、`RATE_LIMITED`（连接器被目录阻断）、`INTERNAL_ERROR`（study 合同损坏或未知状态）。`STALE_SOURCE` 与 `INDETERMINATE_EXTERNAL_ACTION` 暂未映射，留给后续工单。

`status` 每次都必须返回 C-01 六字段 + `state`/`budget`：`next_actor`、`next_required_action`、`blocked_reason_code`、`last_updated_at`、`has_pending_external_effect`、`artifact_refs`。缺少明确下一步的 `review_required` 视为不达标。

## 6. 产物

| 路径 | 内容 |
| --- | --- |
| `tasks/<task_id>/task.json` | 原子写入的任务状态（`phase_history`、`plan`、`budget`、`artifacts`） |
| `tasks/<task_id>/run-log.jsonl` | 追加式运行日志（start / gate / transition / brief） |
| `tasks/<task_id>/brief.json` / `brief.md` | partial Decision Brief（九节 + 缺口 + 受限结论） |
| `studies/<task_id>/…` | 脚手架 study；绑定 study 时写 `studies/<task_id>.json` 绑定指针 |
| `04-findings/research-loop.json` | 由 `research_loop` 拥有，decide 只读 |
| `04-findings/loop-candidates.json` | 候选证据（`status: proposed`，无证据等级） |

## 7. MCP 高层入口（PRD §10.3）

| 工具 | 输入 | 输出 |
| --- | --- | --- |
| `askovo_decide_start` | `workspace`、`task`（`askovo.decision-task/1`）、`run`、`study` | `{exit_code, result: <status 投影>}`；未授权不读数据 |
| `askovo_decide_status` | `workspace`、`task_id` | 同一套 C-01 字段 |
| `askovo_decide_result` | `workspace`、`task_id` | `brief` / `evidence_index` / `validation_backlog` / `canonical_refs` / `review_status` |

三个入口复用 CLI 的编排函数（`askovo.py decide …`），不 fork 第二套行为；`review` / `delta` / `export` 属于专家入口，A-02 只做显式拒绝。

## 8. 边界（必须一起读）

- **记录上限**：`authorization.max_records` 同时写入 loop envelope（`max_records_total`）。上限 2 就只会导入 2 条，绝不读到第 3 条。
- **取消**：`cancel` 之后任何 `--run` 都返回 `POLICY_DENIED`，loop 状态与记录数保持取消前样子。
- **幂等**：同一输入重复 `start` 复用同一 `task_id`、同一 study、同一 plan；`--run` 恢复时若 loop 已完成，只做状态吸收，不重跑、不重复导入、不新增候选。
- **中断**：loop 处于 `needs_review` / `interrupted_run` 时任务进 `interrupted`，要求人工 reconcile；**中断中的动作绝不自动重放**。
- **partial**：存在未解决缺口或没有已支持判断时，Brief 是 `artifact_status: partial` + `ARTIFACT_PARTIAL`，逐条列缺口并给出下一个最低成本验证动作；不补访谈、不补转化率、不补样本比例。
- **证据与决策分离**：`evidence_qualified` ≠ `decision_approved`；`report_delivered` ≠ `hypothesis_validated`；公开 issue 里的要求 ≠ 已证实的实际使用行为。

## 9. 验收对照（AC A6–A12）

| AC | 落实 |
| --- | --- |
| A6 | 缺令牌/来源权限：`needs_input` + `AUTH_REQUIRED` + 可执行 import tasks，不产生 research-loop 计划、不读取 |
| A7 | `max_records=2` 时 envelope、`totals.records` 与 `normalized.jsonl` 都不超过 2 条 |
| A8 | `cancel` 后 `--run` 返回 `POLICY_DENIED`，loop 仍为 `planned`、记录数 0 |
| A9 | 相同输入重复 start 复用同一 task/study/plan；`--run` 不重复导入、不新增候选 |
| A10 | loop `needs_review` 时任务进 `interrupted`，要求 reconcile，记录数保持 0、轮次为空 |
| A11 | 相同输入的 `task_id`、`plan.digest`、`budget.max_records` 完全一致 |
| A12 | 缺数据时 `artifact_status: partial`、`ARTIFACT_PARTIAL`、逐条缺口，`decision_state: not_approved` |

## 10. 与其他文档的关系

- [研究闭环](research-loop.md)：缺口检测、信封授权与候选证据的唯一实现，decide 只编排它。
- [CLI 参考](cli.md)：命令、参数与退出码总表。
- [数据契约](data-contract.md)：canonical 主链与写入权；decide 不新增第二个真相。
- [能力进度](feature-status.md)：A-02 的实现状态与未覆盖边界。

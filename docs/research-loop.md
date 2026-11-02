# 研究闭环（Research Loop）

> 把审计发现的缺口变成受控采集动作，多轮执行、每轮重新审计，最后交付「已验证 / 未验证 / 无法验证 / 下一步」的复盘。它负责编排，不替人做语义判断。

`askovo research` 解决的是「宿主 Agent 已经想好要采什么，怎么安全执行」；研究闭环解决的是「证据不够时，下一步该采什么、采完是否更接近可判断」。两者共用 `collect_platform`、平台策略、来源适配器和 Design gate，不存在第二条采集通道。

缺口有明确的生命周期：`open → collected → analyzed → resolved / unresolvable`。**采集到候选记录不等于缺口闭合**；只有具名操作者执行 `loop assess`，才能把缺口标记为 `resolved` 或 `unresolvable`。

## 1. 它做什么

1. **检测缺口**：读取 `askovo audit` 的逐条判断结果与 `04-findings/product-reasoning.json` 的节点状态，找出缺链、缺反证、超出证据、节点无证据、单一来源、语料角色缺失等问题。
2. **生成动作**：每个可采集缺口 × 每个合规来源生成一条采集动作；已有候选但未分析的缺口生成一条确定性分析动作。查询词由判断标题/节点判断加意图提示确定性拼接，不调用模型。
3. **执行轮次**：在授权信封内逐条执行 `collect_platform`；分析动作只读取已存候选，做计数、来源分布、去重与样例汇总，不联网、不消耗采集预算。每轮结束跑一次描述性分析与 `audit_payload`，记录缺口变化。
4. **停止与复盘**：收敛、候选待分析、分析完毕待人工评估、预算耗尽、来源不可用或中断时停止，写出候选证据清单、分析产物和「已验证 / 未验证 / 无法验证 / 下一步」报告。

## 2. 它不做什么

- 不分配证据等级，不修改 `demand-judgments.json`，不把任何判断置为 `validated`。
- 采集到的记录只是**候选证据**，不进入审计计数；人工定级并写入判断后，结论才会改变。
- 分析动作只做确定性描述，不判断证据支持还是反对某个假设，也不自动把缺口标成已解决。
- 不绕过平台策略、未启用的适配器、`study.scope.allowed_sources` 或 Design gate；被目录阻断的平台仍记为缺口。
- 不替代人工语义复核、财务/市场评审和业务签收。

## 3. 命令

```bash
# 1) 检测缺口并写出计划（尚不可执行）
askovo loop plan ./study --max-rounds 3 --max-actions 3 --max-records 300

# 2) 由具名操作者授权该信封
askovo loop authorize ./study --by "researcher-name"

# 3) 执行；--authorize 可在同一步完成授权
askovo loop run ./study
askovo loop run ./study --authorize --by "researcher-name"

# 4) 查看状态与复盘报告
askovo loop status ./study
askovo loop report ./study

# 5) 由具名操作者评估缺口是否闭合（唯一能关闭缺口的路径）
askovo loop assess ./study --gap "claim:D02:commercial" --verdict resolved \
  --by "researcher-name" --evidence R01 --reason "两条已付费记录直接支持该判断"
askovo loop assess ./study --gap "claim:D02:commercial" --verdict unresolvable \
  --by "researcher-name" --reason "目标来源不再提供可核验的付费行为数据"

# 6) 记录宿主 Agent / 评审人提供的证据映射（片段 → 假设，只校验出处）
askovo loop map ./study --file mappings.json --by "researcher-name"

# 7) 查看系统建议（只读；不关闭缺口）
askovo loop advise ./study
```

`loop advise` 按已记录的映射给出建议：无映射为 `insufficient`，只有支持为 `resolved_candidate`，只有反证为 `unresolvable_candidate`，两者都有为 `conflicted`。建议不改变任何状态，最终仍由 `loop assess` 由具名的人确认。

`mappings.json` 的每条记录必须带 `record_id`、`hypothesis_id`（必须已在 `study.json` 声明）、`stance`（`supports` / `contradicts` / `contextual`）和 `quote`；`record_id` 必须来自已采集候选。映射不会写入证据等级，也不会改变判断状态。

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 计划已写、已授权、执行完成，或报告已生成 |
| 1 | Design gate 未通过，拒绝采集 |
| 3 | 闭环被阻断（无可采来源、来源耗尽、连接器阻断） |
| 4 | 未授权，或信封被修改导致授权过期 |
| 2 | 用法、状态或文件错误 |

## 4. 缺口类型

| kind | 触发条件 | 能否自动采集 |
| --- | --- | --- |
| `exceeds_evidence` | 声称 `validated`，但缺链、缺反证、引用不存在或 `context_key` 不一致 | 能 |
| `open_claim` | 判断未定，且有证据链未闭合 | 能 |
| `missing_counter` | 三条链已齐，但没有反证记录 | 能 |
| `node_without_evidence` | 推理节点有判断、没有证据 | 能 |
| `unwritten_node` | 节点仍是「待填写」 | 不能：先写判断 |
| `claim_needs_decision` | 链与反证已齐，但判断仍未定 | 不能：这是判断写作 |
| `source_concentration` | 单一来源占比超过 `max_source_family_share` | 能：换来源，不是加量 |
| `missing_corpus_role` | `quality_gates.required_corpus_roles` 有角色为零 | 不能：需要新设计材料 |
| `blocked_source` | 平台被目录阻断，或没有启用的适配器 | 不能：记录缺口 |

缺口按严重度排序并编号（`G01`、`G02`…），每个缺口都有稳定 key（如 `claim:D02:commercial`）。缺口状态随 key 保存在 `research-loop.json` 的 `gap_states` 中：

| 状态 | 含义 | 谁能推进 |
| --- | --- | --- |
| `open` | 还没有候选材料 | 采集动作 → `collected` |
| `collected` | 已有候选记录，但尚未分析 | 分析动作 → `analyzed` |
| `analyzed` | 已有确定性分析，仍需语义判断 | `loop assess` → `resolved` / `unresolvable` |
| `resolved` | 具名操作者用已登记证据关闭了缺口（引用会在 `02-data/evidence.jsonl` 中核对） | 终态 |
| `unresolvable` | 具名操作者认定现有条件下无法闭合，并记录原因 | 终态 |

`loop assess` 的 `--evidence` 必须指向 `02-data/evidence.jsonl` 中已存在的 `record_id`（该文件不存在时只做非空校验）；它证明的是"有人用哪条证据关闭了缺口"，不是"该证据支持结论"。

候选记录只把缺口推到 `collected`；旧版本状态没有 `gap_states`，读取时按候选记录回退为 `collected`，不会误判为已解决。

## 5. 来源与查询

一条动作必须同时满足：

- 平台在 `study.scope.allowed_sources` 中；
- 平台存在于平台目录且 `decision != blocked`；
- 有启用的内置适配器（`github` / `reddit`），或有显式的离线 `fixture`；
- 查询词非空，且来自当前缺口。

离线回放（测试或无网络环境）在 `study.json` 中声明：

```json
{
  "research_loop": {
    "fixtures": {"github": "01-sources/authorized/export.jsonl"}
  }
}
```

fixture 路径必须位于研究目录内；同一 fixture 对所有查询返回同一批记录，第二次采集会因去重得到 0 条新记录，这是预期行为。

查询词由「判断标题或节点判断 + 意图提示」组成（中文判断用中文提示，英文判断用英文提示）：`problem` / `alternative workaround` / `pricing subscription` / `complaint refund cancel`。它可解释、可复现，也不伪装成语义检索。

## 6. 授权信封

授权的是一组边界，不是每一条查询：

```json
{
  "max_rounds": 3,
  "max_actions_per_round": 3,
  "max_records_total": 300,
  "max_records_per_action": 100,
  "allowed_platforms": ["github"],
  "platform_modes": {"github": "fixture"}
}
```

- 执行前校验每条动作的平台、模式与单条上限都在信封内，且动作能映射到已记录缺口。
- 分析动作不受平台集合约束，但仍受信封的动作条数限制；它只读已存候选，不发起任何外部请求。
- 信封哈希与授权绑定；修改平台集合或预算后必须重新授权。
- 授权记录具名操作者与时间，`askovo loop status` 可查。
- **信任模型**：信封是操作边界，不是防篡改安全机制。本地操作者仍可编辑状态文件；真正阻止越界的是平台目录、`allowed_sources`、适配器开关、Design gate 和 `collect_platform` 的既有校验。
- MCP 只能 `plan` / `status` / `report` / `run`，不能授权，也不能 `assess`；授权与语义评估都必须在 CLI 由具名的人完成。

## 7. 轮次与停止原因

每轮：检测缺口 → 优先分析已采集未分析的缺口 → 其余 `open` 缺口生成采集动作 → 执行 → 分析 → 重新审计 → 记录缺口变化。

每轮记录一个类型化决策 `decision`：`continue_collecting` / `analyze_existing` / `request_external_evidence` / `stop_with_reason`。它回答的是「这一轮为什么采、为什么分析、为什么停」，而不是「研究结论是否成立」。

| stop_reason | 含义 |
| --- | --- |
| `converged` | 没有缺口，或所有缺口都已 `resolved` / `unresolvable` |
| `awaiting_analysis` | 有已采集缺口，但本轮动作条数用尽，尚未生成分析 |
| `awaiting_semantic_review` | 缺口已分析，等待具名操作者 `loop assess` |
| `partial_coverage` | 部分缺口已推进，剩余缺口无更多可执行动作 |
| `sources_exhausted` | 有缺口，但所有「缺口 × 来源」组合都已尝试 |
| `no_actionable_source` | 有缺口，但没有任何合规来源 |
| `no_new_material` | 本轮采集没有新增记录（重复材料或空结果） |
| `round_budget` / `record_budget` | 轮次或记录预算用尽 |
| `connector_blocked` | 平台策略过期或租约丢失，立即停止 |
| `interrupted_run` | 上一条动作执行中断，需人工检查后重新规划 |

## 8. 产物

| 文件 | 内容 | 是否入库 |
| --- | --- | --- |
| `04-findings/research-loop.json` | 状态机、信封、授权、缺口快照与 `gap_states`、每轮动作、人工评估 | 否（生成物） |
| `04-findings/loop-candidates.json` | 候选证据：缺口 key、平台、查询、run id、记录样例、`proposed_evidence_level: null` | 否 |
| `04-findings/loop-analysis/<gap>.json` | 确定性分析：记录数、来源分布、去重、样例、输入指纹（`input_fingerprint`）与分析版本，附边界声明 | 否 |
| `04-findings/loop-evaluations.json` | 具名评估：缺口、结论、证据引用、理由、操作者与时间 | 否 |
| `04-findings/loop-mappings.json` | 宿主提供的映射：记录 id、假设 id、原文片段、立场、出处 | 否 |
| `05-audit/research-loop-summary.md` | 已验证 / 未验证 / 无法验证 / 仍需补证 / 待人工评估 / 候选证据 / 下一步 / 边界 | 否 |

候选证据的结构刻意留空证据等级：闭环不知道这条记录在语义上算 E1 还是 E3，只有人能定。分析产物同样不评级，只描述采集到了什么。

## 9. 与 `askovo research` 的区别

| | `askovo research` | `askovo loop` |
| --- | --- | --- |
| 谁决定采什么 | 宿主 Agent 写动作清单 | 闭环按缺口确定性生成 |
| 授权对象 | 动作清单哈希（逐条） | 信封（平台集合 + 预算） |
| 是否复审 | 可选 `--analyze` | 每轮重新审计 |
| 产出 | 执行账本 | 执行账本 + 候选证据 + 复盘报告 |
| 语义判断 | 不涉及 | 不涉及（候选待人工） |

两者都不改变判断状态，也都不把通过审计等同于业务成立。

## 10. 边界

`loop report` 的「已验证结论」只表示现有材料在配置门禁下通过审计，不证明需求存在、样本代表总体、市场规模、因果关系、发布就绪或安全合规。闭环能自动化的是**编排、采集与确定性描述**，不是**语义判断与业务签收**。`loop assess` 记录的是具名操作者的判断，系统不替人作判断，也不因此把判断置为 `validated`。

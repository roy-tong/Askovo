# 产品与商业推理主链

askovo 的主链是：

> **场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业**

它是产品团队共同的推理与交接语言，不是“收集数据后自动生成产品”的公式，也不是严格只允许单向执行的瀑布流程。实际工作可以从一个异常场景、一类用户、一个候选方案或一次运营干预开始，再回到主链检查缺了哪一环。

## 1. 主链与支撑层各管什么

| 层 | 回答的问题 | 主要产物 |
|---|---|---|
| 产品与商业推理主链 | 为什么为这类用户、在这个场景、用这个特性和产品解决这个需求，并形成什么商业闭环 | `04-findings/product-reasoning.json` |
| 需求与证据判断 | 现有材料能支持需求、方案接受和商业行为到哪一步 | `demand-judgments.json`、`evidence.jsonl` |
| 研究执行 | 哪个最弱节点需要访谈、观察、实验或平台材料 | `01-sources/`、`02-data/`、`03-codebook/` |
| 交付与发布 | 方案是否达到质量、合规、兼容和回滚要求 | 领域验证计划、release 引用、测试矩阵 |
| 结果与因果 | 上线后观察到什么；是否有合格设计支持因果结论 | 指标/实验引用、tracker |
| 人工决策 | 是否接受取舍和剩余风险，何时复审 | `human_review`、决策记录 |

**证据不是节点，运营也不是节点。**它们贯穿并回写同一条主链；商业是链上第七个节点，不是交付后补的一页财务表。

## 2. 一条 chain 是一条价值线程

每条 chain 关联一个明确的用户、场景、任务和需求判断。一个需求有多个候选特性、一个产品服务多个场景时，用多条 chain 表达和比较，不把相互矛盾的方案塞进同一个节点。

主链文件是七段产品与商业语义的机器真值；Markdown、MRD、PRD、BRD 和用户运营视图都只是投影。

```text
product-reasoning.json
└── chains[]
    ├── id / context_key / demand_judgment_id
    ├── status / confidence
    ├── supporting_states
    ├── nodes.scene / user / pain / need / feature / product
    ├── nodes.business
    ├── prioritization
    ├── change_log[]
    ├── alternative_explanations[]
    ├── counter_evidence_ids[]
    ├── human_review
    ├── gaps[]
    └── next_test
```

## 3. 七个节点的定义

| 节点 | 必须表达 | 专属字段 | 不能退化为 |
|---|---|---|---|
| 场景 `scene` | 什么触发、环境和任务上下文值得进入决策 | `trigger`、`environment`、`task_context` | “移动端”“一线城市”等没有任务上下文的标签 |
| 用户 `user` | 为什么是该场景中的这个角色、状态与决策角色 | `role`、`state`、`decision_role` | 虚构 persona；把评论记录数当人数 |
| 痛点 `pain` | 当前替代在哪里失效，产生什么摩擦、成本与后果 | `current_substitute`、`friction_cost`、`consequence` | “缺一个按钮”；只有态度没有事件 |
| 需求 `need` | 希望取得的可观察结果及约束，保持解法中立 | `desired_outcome`、`constraints`、`measure` | 把 CSV、AI、摄像头等候选方案写成需求 |
| 特性 `feature` | 哪个候选能力可以改变结果，为什么优于其他候选 | `capability`、`acceptance_conditions`、`alternatives_considered` | 功能提及频率、需求的同义改写 |
| 产品 `product` | 哪些能力组成有边界的价值交付，如何验收 | `form`、`scope`、`non_goals`、`acceptance_criteria` | 无优先级的 feature list；方案喜欢等于发布就绪 |
| 商业 `business` | 这个产品如何形成可验证的商业闭环，下一步商业门是什么 | `market_definition`、`geographies`、`time_window`、`included_markets`、`excluded_markets`、`target_segment`、`segments`、`payer`、`positioning`、`revenue_model`、`pricing_hypothesis`、`pricing`、`channels`、`competitive_alternatives`、`cost_drivers`、`market_estimates`、`unit_economics_inputs`、`success_metrics`、`non_goals`、`gate` | 竞品报价当自己价格；TAM 当本链需求；付费意愿当交易；商业决策当商业成功 |

### 每个节点共有的五个字段

```json
{
  "statement": "当前判断",
  "rationale": "为什么能从上一节点推到本节点",
  "status": "hypothesis",
  "evidence_ids": [],
  "assumptions": ["推导仍需成立的原子假设"]
}
```

`rationale` 是 incoming edge 的说明。`scene.rationale` 解释为什么该场景值得进入当前产品决策；其余六个 rationale 分别对应 `scene→user`、`user→pain`、`pain→need`、`need→feature`、`feature→product`、`product→business` 六条推导边。

**节点有证据，不等于推导成立。**例如：

- 有替代成本证据，不自动证明某个需求应优先；
- 有需求证据，不自动证明某特性是最佳回应；
- 有方案接受证据，不自动证明特性组合、工程质量或商业结果成立。

## 4. 状态不能混用

### 节点状态

`hypothesis / needs-validation / validated / rejected / deprioritized`

这里的 `validated` 只表示该节点满足当前配置的直接证据要求，不表示绝对真实。

### chain 状态

`draft / hypothesis / needs-validation / decided / rejected / deprioritized`

`decided` 是“当前阶段的产品与商业选择已被记录”，不是“产品已被证明”或“商业已经成立”。当前结构门要求七节点 decided chain：

- 七个节点均为 validated；
- 关联 validated demand judgment；
- 有反证和至少一个替代解释；
- 特性有接受条件与备选方案；
- 产品有范围、非目标和验收条件；
- 商业节点有市场边界、细分、价格/收入假设、成本、单位经济输入、成功指标和业务门；
- 优先级有方法、负责人、日期与理由。

PM 可以在证据不足时决定推进，但应保留 `needs-validation`，记录风险接受、反对意见和复审点，而不是把状态改成“已证明”。旧版六节点 chain 仍可读取，新工作区默认使用七节点。

### 独立支撑状态

```json
"supporting_states": {
  "delivery": {"status": "unplanned", "release_plan_ref": ""},
  "outcome": {"status": "unmeasured", "metric_refs": []},
  "causal": {"status": "not-claimed", "experiment_refs": []}
}
```

- `delivery`：unplanned / in-progress / release-ready / rolling-out / paused / rolled-back；
- `outcome`：unmeasured / observing / positive-observed / no-effect / negative / inconclusive；
- `causal`：not-claimed / supported / refuted / inconclusive。

发布状态需要 release 引用；结果状态需要指标引用；因果支持或否定需要实验引用。E3 方案接受不能单独把 delivery 标成 release-ready，E5 真实使用也不能单独把 causal 标成 supported。

## 5. 证据关联规则

`product-reasoning.json` 与 `demand-judgments.json` 通过 `demand_judgment_id + context_key` 连接。

| 主链位置 | 允许引用的已登记证据 |
|---|---|
| scene / user / pain / need | linked judgment 的 problem 或 counter 证据子集 |
| feature | solution 或 counter 证据子集 |
| product | solution + commercial + counter 证据子集 |
| business | commercial + counter 证据子集 |
| chain counter | linked judgment 的 counter 证据子集 |

节点 validated 的直接证据要求：

| 节点 | 最低证据类型 |
|---|---|
| scene / user | E0–E3、E4+、E5 中与语义相符的直接记录 |
| pain / need | E1 / E2 |
| feature / product | E3 方案接受；product 的商业行为另由原需求判断审计 |
| business | E4+ 商业意图或 E5 已实现付费/留存/扩展；不等于可持续商业 |

新证据必须先进入 `evidence.jsonl`，再登记到需求判断，最后挂到主链节点。不能只编辑主链文件来“补出”一条证据链。

## 6. 反证、替代解释与人工复核

每条 chain 使用三类不同信息：

- `assumptions`：推导成立必须额外为真的命题；
- `alternative_explanations`：同一材料还可能怎样解释，或其他方案为何更合理；
- `counter_evidence_ids`：实际观察到的拒绝、满意替代、无痛点或相反行为。

自动门只能检查它们是否被记录、引用是否一致。以下事项仍由人判断：

- 需求是否被偷换成方案；
- 证据是否真的支持 rationale；
- 负例是否被公平处理；
- 抽样、伦理和适用边界是否合适；
- 剩余风险是否值得接受。

`human_review` 记录 `status / reviewer / notes / risk_acceptance`。它是复核记录，不是 CLI 对人工真实性或产品正确性的认证。

`prioritization` 记录需求分析的方法、因素、负责人、日期和理由；`change_log` 记录变更依据、受影响节点、影响判断和投影同步状态。优先级不能由词频直接决定，变更必须先改唯一主链，再同步 MRD/PRD/BRD。

## 7. 工作闭环

```text
决策问题与可选方案
→ 建立主链假设
→ 找最危险且证据最弱的节点/推导
→ 选择方法与来源
→ 采集、分析、编码、反证
→ 更新主链与需求判断
→ MRD 候选市场 / PRD 需求基线 / BRD 商业决策
→ 产品选择、工程验证、发布评审
→ 观察结果/必要时的因果实验
→ 运营干预与学习回写主链
```

这与资深岗位的实践一致：发现与交付可以并行，上线后继续学习；但不同状态不能相互冒名顶替。方法依据见 [岗位方法论](product-methodology.md)。

## 8. 多类职责只读同一事实源

- **产品经理**：读完整 chain、备选方案、范围、非目标、验收、商业门和残余风险；使用 memo、report、MRD/PRD/BRD。
- **用户研究**：读节点证据、假设、反证、替代解释、样本缺口和人工复核；使用 research-status、audit 和补证计划。
- **用户运营**：读 scene/user/pain 的行为分群与语言、feature/product 的干预对象、business 的行为指标、counter 的异议；通过 ops 和 tracker 回流。
- **市场研究/分析**：读商业节点的市场边界、细分、替代、渠道、价格和规模口径；产出 MRD。
- **需求研究/分析**：维护 need→feature→product→business 的 requirement、优先级、验收、追溯与变更；产出 PRD。
- **商业分析**：维护收入、成本、单位经济、资源门、风险与 BRD，不让财务假设替代用户和交付证据。

运营指标必须有事件、分子、分母、窗口、队列和版本口径。公开反馈帮助解释“为什么”，不能直接估计客群规模；行为数据帮助回答“做了什么”，不能单独解释动机或证明干预因果。

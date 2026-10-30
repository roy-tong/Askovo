# 整合层 runbook：product-reasoning 主链如何投影为 MRD/PRD/BRD（B-5）

> 模板组 B-5 的入口文件。本组把 `04-findings/product-reasoning.json` 的同一套产品推理，投影为文档地图、MRD、PRD、BRD、缺口审计、定价研究和关键五问。模板中的示例均为合成内容，不含真实客户与公司名。

## 1. 什么时候用这一组

- 已建立 `04-findings/product-reasoning.json`，需要把同一条主链转成面向决策、产品和运营的文档；
- 主链可以仍处于假设态。允许交付“当前推理 + 缺口 + 下一验证”，不要求先有成熟研究结论；
- 需要检查 MRD、PRD、BRD 是否出现口径漂移、断链、孤儿特性或无依据的商业承诺。

不适用：尚未建立主链文件时，先回 Askovo 主流程创建并填写；只需要研究执行状态时，使用研究状态报告，不以整合文档替代原始证据和审计记录。

## 2. 唯一语义真值与引用格式

**`04-findings/product-reasoning.json` 是主链唯一语义真值。** MRD、PRD、BRD 和其他整合文档都是投影，不是第二套事实源。

主链固定为：

```text
scene → user → pain → need → feature → product → business
场景   → 用户   → 痛点   → 需求   → 特性    → 产品     → 商业
```

每条 chain 使用 `id / context_key / demand_judgment_id / status / confidence / nodes / prioritization / change_log / counter_evidence_ids / gaps / next_test`。每个节点必须保留：

- `statement`：当前节点判断；
- `rationale`：为什么能由上一节点推导到本节点；scene 说明为什么进入当前决策；
- `status`：当前推理状态；
- `evidence_ids`：支撑节点事实或推导的证据记录；
- `assumptions`：尚未消除的假设。

节点专属字段不得改名：

- scene：`trigger / environment / task_context`；
- user：`role / state / decision_role`；
- pain：`current_substitute / friction_cost / consequence`；
- need：`desired_outcome / constraints / measure`；
- feature：`capability / acceptance_conditions / alternatives_considered`；
- product：`form / scope / non_goals / acceptance_criteria`；
- business：`market_definition / geographies / time_window / included_markets / excluded_markets / target_segment / segments / payer / positioning / revenue_model / pricing_hypothesis / pricing / channels / competitive_alternatives / cost_drivers / market_estimates / unit_economics_inputs / success_metrics / non_goals / gate`。

引用格式：

- 节点：`PR01.need`；
- 推导边：`PR01.need→feature`；
- 证据：`PR01.pain + R01/R02`；
- 需求判断：`PR01.demand_judgment_id → D01`。

节点有证据不等于推导成立。六条边都要有 `rationale`，证据等级不能替代“需求为什么推出特性”“特性为什么组成产品”“产品为什么形成这个商业闭环”的理由。商业节点的市场估计、价格、成本、单位经济和资源门不得由 MRD/BRD 自行另存。

## 3. 状态与证据不得混用

- chain 的 `decided` 表示团队在当前证据和约束下作出了产品/商业决策，**不表示产品已被证明或商业已经成立**；七节点 decided 还要求商业门与优先级。拒绝方向用 `rejected`，尚未决策保持 `draft` 或 `hypothesis`。
- `demand-judgments.json` 的 `validated` 只表示需求判断满足其证据门，不等于 chain `decided`，也不等于 PRD 签收、产品验证完成或商业成立。
- E0–E5 按单条记录直接观察到的最强证据定级，不得由低级推断高级。多人一致只影响覆盖、置信度和下一验证设计，不自动升级 E 等级。
- 每个正式结论保留证据 ID、反证、适用范围和缺口。`pass` 只说明结构与配置门通过，不证明总体、因果、市场规模或产品成功。

## 4. 模板分工

| 模板 | 主链投影 | 回答什么 | 主要读者 |
| --- | --- | --- | --- |
| `00-文档地图与阅读指引-模板.md` | 全链索引 | 真值在哪、每份文档投影什么 | 所有人 |
| `02-MRD-市场需求文档-模板.md` | 市场研究/分析 + scene/user/pain/need 与 business 市场部分 | 哪个市场/细分/渠道/价格值得进入，证据与缺口是什么 | 市场研究/分析、产品经理、用户研究、用户运营 |
| `03-PRD-产品需求文档-模板.md` | 需求研究/分析 + feature/product | 用什么特性、产品范围、优先级、验收和追溯回应需求 | 需求分析、产品、研发、设计、用户研究 |
| `01-BRD-商业需求文档-模板.md` | business 节点 | 商业分析：收入、成本、单位经济、资源门、风险和停止条件 | 商业分析、决策者、产品经理、财务/战略 |
| `04-缺口审计与修改意见-模板.md` | 节点 + 推导边 + 投影漂移 | 哪一步最弱、缺什么、何时改真值 | 所有人 |
| `05-定价研究-模板.md` | 商业验证投影 | 如何收费、何时允许定价 | 决策者、商业化、产品 |
| `06-关键五问-模板.md` | 高影响不确定性的决策视图 | 哪些问题最可能改变产品决策 | 决策者及产品/研究/运营/市场/需求/商业职责 |

商业是主链第七个节点，BRD 是商业分析的正式投影，不是主链之外的新事实源。市场研究/分析产出 MRD，需求研究/分析产出 PRD，商业分析产出 BRD；卖点、定价、GTM 和运营动作是下游投影。

## 5. 目录与同步方向

```text
项目/
├── 研究目录/
│   ├── 04-findings/product-reasoning.json   ← 唯一主链语义真值
│   ├── 04-findings/demand-judgments.json    ← 需求判断与证据资格
│   ├── 02-data/evidence.jsonl               ← 证据记录
│   └── 05-audit/                            ← 门禁与审计
└── 0X-整合文档/                             ← 本组模板生成的投影
```

同步只能按以下方向进行：

```text
新证据 / 新实验 / 新决策
  → 更新 evidence、demand judgment 或产品决策记录
  → 人审修改 product-reasoning.json
  → 更新 MRD / PRD / BRD 等投影
  → 在 04 缺口审计登记触发事件与版本
```

不得先在 MRD 改用户、在 PRD 新增特性、在 BRD 改产品承诺，再让主链追随文档。发现投影错误时，回主链修改并重新生成或同步所有投影。

## 6. 推荐写作顺序

```text
00 文档地图：登记 chain / node / edge 与投影位置
├─ 市场研究/分析 → MRD：市场边界、细分、替代、渠道、价格、规模口径
├─ 需求研究/分析 → PRD：need→feature→product、优先级、验收、追溯
└─ 商业分析 → BRD：business、收入成本、单位经济、资源门与停止条件
→ 04：审计节点、推导边、反证、优先级、变更和投影漂移
→ 05 / 06：按商业缺口和高影响不确定性收口
```

这三条是工作流，不是三份事实源，也不存在 MRD 是 PRD 的上游真值或 PRD 是 BRD 的上游真值。三者都回读同一主链；小团队可并行或由同一人完成，但 MRD、PRD、BRD 的产出边界不能混。

## 7. 假设态与成熟态

| | 假设态 | 成熟态 |
| --- | --- | --- |
| chain | 允许 `draft/hypothesis`，显式列 unknown 与最便宜验证 | 可由负责人签为 `decided`，仍保留反证与复审触发器 |
| MRD | 场景、用户、痛点、需求的证据边界和分群假设 | 经持续行为与运营数据校准的分群和需求视图 |
| PRD | 特性候选、备选方案、MVP 范围与验证条件 | 完整 FR/NFR、数据模型、SKU 与版本验收 |
| BRD | 商业假设、业务门、停止条件，不虚构规模与收入 | 有真实成本、交易、留存和单位经济输入 |
| 卖点/运营 | 下游表达假设，等待概念与真实负担测试 | 由已验证主链和实际反馈持续更新 |

## 8. 质量检查

1. **七节点齐全**：没有跳过 scene/user/pain/need 直接写 feature/product，也没有跳过 product→business。
2. **六边闭合**：scene→user、user→pain、pain→need、need→feature、feature→product、product→business 都有 rationale。
3. **无孤儿特性**：每个 feature 回链至少一个 need；每个 product 说明 feature 如何组合成范围与形态；每个商业判断回链 product。
4. **证据不越级**：E 等级不因人数、热度或团队偏好升级；反证和满意替代方案可见。
5. **状态不冒充事实**：chain `decided` 不写成“已验证产品/商业”；需求判断 `validated` 不写成 PRD 已签收。
6. **商业口径完整**：市场估计有边界、总体、时间、单位、公式和来源；价格、成本、单位经济和资源门不被竞品报价或财务假设替代。
7. **优先级和变更可审**：有方法、因素、负责人、日期和理由；变更先改主链并登记投影同步。
8. **卖点在下游**：不得由卖点反推用户需求；卖点只能压缩表达已形成的主链。
9. **投影可回链**：MRD、PRD、BRD 的关键判断都有 chain/node/edge 引用，且对应工作流分别为市场、需求、商业分析。
10. **多职责可读**：产品经理能决策，用户研究能补证，用户运营能回流，市场/需求/商业分析能各自审阅自己的投影。
11. **边界仍在**：保留隐私、授权、安全、禁止推断和人工签收要求。

## 9. 起步命令

```bash
cp -R skills/askovo/templates/integration-docs/ "<项目>/0X-整合文档/"
# 先填 00，再按 02 → 03 → 01 → 04 → 05/06 建立投影
```

复制模板不会生成主链事实。所有占位内容必须回 `product-reasoning.json` 填写，不能用看似完整的文字掩盖空节点。

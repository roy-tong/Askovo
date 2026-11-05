# 研究模式：Discover / Validate / Optimize

Askovo 在「五域 × 生命周期阶段」之外增加一层**研究模式**。领域回答“这是什么产品、证据形式是什么”，阶段回答“现在做到哪一步”，模式回答“这次研究从七节点的哪里进入、先回答什么问题”。

| 模式 | 中文 | 输入 → 输出 | 默认入口 | 典型触发 |
|---|---|---|---|---|
| `discover` | 机会发现 | 想法 → 候选机会 | 场景 | 创业机会、新业务、从 0 到 1、市场空白 |
| `validate` | 假设验证 | 假设 → 支持 / 反证 / 未知 | 需求，或按文本进入特性 / 商业 | 待验证节点、是否成立、试点、证伪 |
| `optimize` | 产品迭代 | 现有产品 → 诊断与改进 | 产品，商业化问题进入商业 | 转化下降、流失、留存、续费、诊断 |

## 入口节点

入口不是结论，只是“先回答什么”的排序。

| 模式 | 入口规则 |
|---|---|
| Discover | 恒为 `scene`（场景）。先找真实发生、可观察的任务与触发条件。 |
| Validate | 默认 `need`（需求）；文本含 付费 / 价格 / 定价 / 商业 / 收入 → `business`；含 功能 / 特性 / 方案 / 形态 → `feature`。商业词优先于功能词。 |
| Optimize | 默认 `product`（产品）；文本含 付费 / 价格 / 收入 / 续费 / 商业 → `business`。 |

`askovo mode` 会输出旋转后的七节点顺序和入口之前的上游节点。例如从商业进入的 Validate：

> 商业 → 场景 → 用户 → 痛点 → 需求 → 特性 → 产品

其中场景、用户、痛点、需求、特性、产品都是**上游节点**，在补证之前只能作为假设。

## 硬边界

> 入口只决定先回答什么，不豁免七节点的证据要求；上游未验证前只能作为假设，不能当作事实。

这意味着一份从 `business` 进入的验证报告，不能因为先回答了付费问题，就把未经验证的痛点、需求或产品直接写成事实。从中间节点进入时，下游结论必须显式依赖上游假设，并列出支持、反证和未知。

## 与五域、七节点、生命周期阶段的关系

- **五域不分叉**：模式不改变软件 / 硬件 / 消费品 / 汽车 / 手机的领域包。同一个 Validate，在软件里可能用任务测试和付费试点，在硬件里还要设计验证、批次和供应证据；模式只决定入口和问题顺序。
- **七节点不豁免**：`场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业` 仍是唯一主链。模式只把这条链旋转到入口节点，不新增第二套链，也不允许跳过节点。
- **阶段映射**：`discovery` / `concept` → Discover；`validation` / `pricing` / `prelaunch` → Validate；`postlaunch` / `audit` / `operate` → Optimize。阶段映射受下面的优先级约束；未列出的阶段（如 `prototype`）不强行映射。
- **模式不是证据等级**：检测置信度只表示“模式判断有多确定”，不等于证据强度，也不把任何节点升级为 `validated`。

## 模式判定优先级

1. 显式 `--mode`：置信度 1.0，来源 `explicit`。
2. 显式 `--stage`：用户明确指定阶段时按阶段映射，置信度 0.85，来源 `stage`。
3. 文本关键词：按命中数打分，置信度 `0.55 + 0.1 × 命中数`，上限 0.95，来源 `text`。
4. 文本没有模式信号、但阶段是关键词推断出来的：使用阶段映射，置信度 0.6，来源 `stage`。
5. 以上都没有：默认 Discover，置信度 0.3，来源 `default`。

关键词推断的阶段不能压过文本信号。例如“验证端侧摄影 App 是否值得做”同时命中 discovery 阶段的“值不值得”和 Validate 的“验证”，结果是 Validate，而不是 Discover。`askovo mode --json` 的 `mode_source` 字段显示本次判断来自哪一级。

## 进入 Research Loop 之后

`askovo loop plan` 读取 study 中的 `research_mode`，在同一套缺口语义上调整动作权重：

| 模式 | 提高权重 | 降低权重 | 原因 |
|---|---|---|---|
| Discover | collect、experiment | analyze | 先扩大机会空间、替代方案与人群样本 |
| Validate | experiment、request_external_evidence | collect | 优先能推翻假设的行为与外部证据 |
| Optimize | analyze | collect | 先诊断已有数据断点与替代解释 |

权重只影响候选动作的相对排序，不把任何动作变成自动执行，也不改变授权、证据等级与语义复核边界。`loop plan --json` 会返回 `research_mode`，每个动作候选带 `mode_weight` 与调整理由。

### Validate 的外部验证交接

当 Validate 的最优动作是 `experiment` 或 `request_external_evidence` 时，系统不会退而继续采集公开评论，而是：

1. 在 gap 上记录 `validation_handoff`（推荐动作、理由、所需授权/参与者）；
2. `loop plan` 输出 `external_validation_tasks`；
3. 该 gap 不再生成采集动作，`loop run` 以 `awaiting_external_validation` 停止，等待真实试点、报价实验或有权使用的外部记录。

这正是「研究判断 → 可执行动作或明确的人工验证交接」的最小闭环；它不会伪造实验结果。

## 与 `askovo route` 的关系

`askovo route` 继续负责五域、阶段、意图、风险和岗位编排，并新增 `research_mode` 字段；原有字段语义不变。无论是否检测出领域（`needs_domain` 或 `routed`），都会带上该对象。

`askovo mode` 是同一契约的独立入口：不需要先确定领域，不写文件，只回答“从哪进、先问什么、何时停”。契约中的 `mode_source` 说明模式来源：显式模式、显式阶段、文本、关键词阶段或默认。

```bash
askovo mode "端侧 AI 摄影创业机会"
askovo mode "验证端侧摄影 App 是否值得做，用户是否愿意付费" --mode validate
askovo mode "为什么我们的注册转化下降" --stage postlaunch --json
askovo route "手机端侧 AI 摄影的创业机会" --json
```

## 不承诺验证结论

`askovo mode` 输出的是研究设计契约：入口、问题、先做动作、停止条件和边界。它不收集数据、不判定需求成立、不证明市场规模或付费意愿，也不替代 E0–E5 证据评审和人工语义复核。真正结论仍要看证据是否与当前节点、上下文和判断相连，以及反证是否被处理。

模式判断是确定性的关键词与阶段规则，可能误判。优先级为：显式 `--mode` > 任务文本信号 > 显式 `--stage` > 关键词推断阶段 > 默认 Discover。**阶段是背景条件（产品处在哪），模式是本次任务类型**；已上线产品研究新市场时，文本仍可判为 Discover，`--stage postlaunch` 不会把它压成 Optimize。

`mode_score` 是关键词命中的启发式分数（`score_basis=keyword_hits`，`calibrated=false`），只用于排序与提示，不是“判断正确的概率”。

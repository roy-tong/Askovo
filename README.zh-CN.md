<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center">
  <a href="README.md">English</a> | <b>简体中文</b>
</p>

# Askovo

**给我一个产品或市场问题，还你一份业务方案——判断建立在采集来的数据上，不是编出来的。**

Askovo 面向产品经理、用户研究、业务分析人员，以及转型全栈、要兼职扛起「挖需求、定产品」职责的研发。默认跑法五步：①把问题框成七节点假设画布；②制定数据爬取方案（平台、关键词、配额）；③经允许的渠道采集大量语料；④从数据里推出场景/用户/痛点/需求/特性/产品/GTM 判断；⑤渲染**业务方案**（`askovo deliver --kind plan`）——每个判断都标注依据强度（●已观察到/◐有线索/○假设，按引用记录自动计算）、数据基础（来源、语料量、时间窗）与来自语料的用户之声，通篇业务语言。MRD/PRD/BRD 与决策包仍是同一条主链面向分析师与决策侧的投影。

当前支持 CLI、Skill 和 MCP；研究动作可由宿主 Agent 规划，也可由 `askovo loop` 从审计缺口生成信封授权下的多轮动作，执行器只运行获批内容。来源缺口和人工语义复核会明确保留。[能力进度与技术取舍](docs/feature-status.md)。

> **场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业**

数据收集、描述性分析、访谈、实验、证据分级和平台连接都只是支撑步骤：它们用于验证某个节点或推导关系，不能代替产品与商业推理本身。

质量约束在引擎里：每条结论内部带证据等级，结论超出证据时 `askovo audit` 直接说出来（退出码 1 可进 CI）。面向业务的交付物里，这些等级只出现在文末方法档案——正文讲的是业务逻辑本身，尚无数据的判断会如实标注"暂无采集数据"。

[官网](https://roy-tong.github.io/Askovo/) · [快速开始](docs/quickstart.md) · [产品与商业推理主链](docs/product-reasoning.md) · [岗位方法论](docs/product-methodology.md) · [平台与连接器](docs/connectors.md)

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-Askovo-111111)](skills/askovo/SKILL.md)
[![CI](https://github.com/roy-tong/askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/askovo/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## 30 秒证明它能工作

```bash
pipx install askovo
askovo do "家用摄像头夜间告警误报，想验证样机" --dry-run
askovo demo
askovo decision --help   # 版本化决策、反证触发的安全暂停与回放
```

<!-- 首屏 demo GIF：用 marketing/demo/askovo-demo.tape 录制（vhs），产物拷到 assets/demo/askovo-demo.gif 后取消注释。
<p align="center">
  <img src="assets/demo/askovo-demo.gif" alt="askovo demo：一句话路由、推理链骨架、审计超证" width="860">
</p>
-->

也可以直接写：`askovo "手机相机夜景和续航" --dry-run`。`--dry-run` 只路由、不写文件；`demo` 运行内置合成样例。

预期关键结果：`status: pass`、`supported: 1`、`overclaims: 0`。这只证明合成样例的结构、推理链和证据引用自洽，**不证明真实需求、产品质量、市场规模或发布可行性**。

## 研究问题 → 决策结果：一次完整交付长什么样

输入一个产品问题，输出一份**业务方案（Business Plan）**——目标场景、用户画像、痛点、需求、特性地图、产品形态与 GTM 路径，每个判断带依据强度（●已观察到/◐有线索/○假设，按引用记录自动计算）、数据基础与语料里的用户之声。以内置合成样例（`examples/sample-study`）为例：

```bash
askovo chain examples/sample-study
askovo deliver examples/sample-study --kind plan   # → 06-report/plan.md（业务语言）
```

方案读起来是一份业务文档："## 2. 目标场景：哪些场景值得做"、"## 4. 痛点：现在怎么办、痛在哪"、"## 8. 商业与 GTM：怎么走向市场"——每个判断标依据强度`●已观察到 / ◐有线索 / ○假设`，下面是`数据基础`（来源 · 语料量 · 时间窗）与`来自语料的声音`（用户原话或典型情况）；尚无数据的判断如实标注"暂无采集数据"。证据编码与原始状态只出现在文末的方法档案，不进正文。

当读者是决策者而不是业务读者时，**决策包（Decision Package）**把同一条主链渲染成决策侧视图——每个判断都能回溯到证据和反证：

> 研究问题：养宠物的远程主人，是否值得为"离家时的宠物看护"跑一个两周的手机巡检试点？

主链跑完（七节点全部 validated，2 条反证在案）后，一条命令生成决策包：

```bash
askovo deliver examples/sample-study --kind decision   # → 06-report/decision-package.md
```

决策包给决策者五个视图：

| 视图 | 回答 |
|---|---|
| 机会地图 Opportunity Map | 哪些方向值得考虑（场景×用户×痛点、节点就绪度、优先级） |
| 证据图 Evidence Graph | 每个判断被哪些证据（带 E0–E5 等级）支持或反驳 |
| 选项与权衡 Options & Trade-offs | 候选方向的收益、代价、反证与替代解释 |
| 决策备忘 Decision Memo | 推荐选择、置信边界、未选择的原因；交付/结果/因果三态分列 |
| 验证清单 Validation Backlog | 最值得下一步验证的未知（缺口、needs-validation 节点、最便宜的证伪测试） |

样例决策备忘（节选，原文为英文合成数据）：优先级方法 "test privacy, acceptance and retained use before any scale decision"；理由 "the smallest test that can reverse the concept; no market-size ranking is claimed"；置信边界——反证 `R05`/`R07`，缺口含 "Privacy controls are not tested in real homes"；三态：交付 `unplanned` / 结果 `observing` / 因果 `not-claimed`。**`decided` 只是选择记录，不是发布或商业证明**——三态互相独立，不得互推。

业务方案、MRD/PRD/BRD 与决策包不是几套结论——它们是同一条主链的业务视图、市场/需求/商业投影与决策侧汇总视图。

三个高频任务都走同一条链，只是收口交付不同：**发现**（产品问题 → 业务方案，决策包作决策侧深读）、**验证**（审查设想 → 验证清单）、**决策**（候选比较 → 决策备忘）。

### 版本化与对抗性 DecisionRecord

`askovo decision` 把决策及回放写入唯一的 canonical `04-findings/product-reasoning.json`，不另建决策真相文件：

```bash
askovo decision record ./study --chain PR01 --by "产品负责人" \
  --decision "支持当前小范围产品机会"
# 前提：R08 已登记、context 相同、有 provenance，且已有 contradicts/反证映射。
# 不提供替代产品建议也能改判。
askovo decision record ./study --chain PR01 --by "产品负责人" --contradiction R08
askovo decision replay ./study --chain PR01
```

第二条记录按确定性规则改为 `hold`，把主链/产品/商业重开为待验证，置信度降一级，并保留改前/改后建议、证据关系与快照。`--recommendation "..."` 只是可选人工覆盖，系统不会编一个新产品。只有 ID、没有已记录矛盾关系会被拒绝。新映射证据不会因此被提升为 validated 判断或因果证明。

## 一条主链，80 个岗位族，10 类行业上下文，五个基础研究域

Askovo 新增的是可执行的**产品创新岗位操作系统**，不是岗位名称附录。80 个岗位族覆盖机会研究、用户/需求研究、产品战略、概念/服务设计、数字体验、实体工程、消费品研发、分层验证、生命周期交付及 ResearchOps/DesignOps。每岗都有使命、职责、KPI 公式与护栏、输入→动作→输出→质量门 SOP、核心交付、工作模板、交接和人类专业边界；十类行业上下文覆盖消费软件、企业软件、AI、智能/传统硬件、快消、服装家居、工业机器人、汽车和医疗健康。

```bash
askovo roles list --json
askovo roles show R52 --industry ai_native
askovo roles recommend "AI 摄影应用概念" --stage concept --task design
askovo roles recommend "仓储机器人现场工序与 ROI" --task decide --scale lean
askovo roles scaffold ./study --role R29 --role R52 --role R72
askovo roles template R52 --output agent-interaction-spec.md
askovo deliver ./study --kind role --role R52  # 主链只读岗位投影
askovo deliver ./study --kind lifecycle        # 十板块岗位导航
```

`do/route` 返回的是**按任务裁剪**的岗位建议，而不是默认上全套 80 岗。系统先判断本次属于决策、发现、定义、设计、验证、上市、运营或审查，再选最小充分岗位，列出暂不纳入岗位及原因，并生成输出合同：主交付物、格式、篇幅、读者、章节结构、证据呈现和行业表达方式。软件决策通常只需 1–3 个岗位；硬件 DVT、医疗器械等高风险任务才扩展为跨职能复核。确认主链后，`roles scaffold` 原子生成 `01-sources/role-workbench/`：任务/输出合同、RACI、绑定的 chain/node、SOP 质量门、KPI 空目标，以及只属于本轮主交付/必要支撑的未复核模板；多链必须加 `--chain`，需要全部岗位模板时显式加 `--all-templates`。它们只组织工作，不建立第二套市场/需求/产品/商业真值，也不会把 SOP 完成变成需求验证、工程批准、临床/安全/合规签收、量产就绪或因果证明。详见[产品创新岗位操作系统](docs/role-operating-system.md)和 [Agent 岗位协议](skills/askovo/references/role-operations.md)。

五个 SURE 基础领域包仍负责方法路由；十个行业覆盖层只改变专业上下文，不分叉七节点 schema。以下主链投影继续服务各自读者：

| 使用者 | 从同一主链获得什么 | 主要交付 |
|---|---|---|
| 产品经理 | 全链取舍、范围、优先级、验收、风险和商业门 | 业务方案、决策 memo、产品/商业报告、BRD 与最终签收 |
| 用户研究 | 场景、用户、痛点、需求证据，反证与语义复核 | 研究状态报告、需求判断、证据台账、补证计划 |
| 用户运营 | 场景×用户分群、真实行为、异议、生命周期干预与反馈回流 | 用户运营投影、tracker、行为和留存证据 |
| 市场研究 / 市场分析 | 市场边界、细分、竞品替代、渠道、价格、规模口径与进入假设 | MRD |
| 需求研究 / 需求分析 | 把用户、市场、业务和技术需要转为特性、产品要求、优先级、验收和追溯 | PRD |
| 商业分析 | 收入模式、价格、成本、单位经济、资源门与风险接受 | BRD |
| 全栈研发 | 转型后自己扛的产品职责：来自所在社区的场景→需求证据、特性取舍、范围与非目标 | 业务方案、PRD |

转型全栈的研发从[全栈研发入门手册](skills/askovo/references/fullstack-developer-playbook.md)进入：先用自己所在的开发者社区语料（GitHub issues、Hacker News、Reddit）做入门证据，用业务方案决定什么值得做，再拿 PRD 当实现依据——都是同一条主链的投影。

小团队可以一人承担多项职责，但工作流和产出不能混：

| 分析工作流 | 正式产出 | 不能冒充 |
|---|---|---|
| 市场研究与市场分析 | MRD：候选市场、细分、替代、渠道、价格与规模口径 | 用户需求成立、产品成功 |
| 需求研究与需求分析 | PRD：场景到需求再到特性、产品及验收的可追溯要求 | 市场需求、商业成立 |
| 商业分析 | BRD：产品到商业模式的决策、资源门、单位经济和剩余风险 | 产品已成功、市场已被证明 |

五类领域共用同一份主链 schema，不各自分叉流程。领域包只改变方法、证据形式、风险门和验收重点。当前重点深耕 **AI 软件、开发者工具与智能硬件**三类场景（五域方法论保持兼容）：

| 领域 | 验证与交付重点 |
|---|---|
| 软件 / SaaS | 工作流、任务可用性、Beta、A/B、队列留存、发布护栏 |
| 硬件 / IoT | 安装维护、样机偏差、实验室与现场、配置基线、RMA |
| 消费品 | 使用场合、概念包装、CLT/HUT、感官、首购与复购 |
| 汽车 | HMI、诊所/模拟器/场地/道路、误用、工程 V&V 与安全边界 |
| 手机 / 可穿戴 | 真实场景、握持与跨端、弱网/功耗/兼容、版本与售后 |

## 核心工作方式

### 1. 先建立产品与商业推理，再决定研究什么

```bash
askovo do "SaaS 订阅留存下降，想看看用户为什么不续费"
askovo chain ./askovo-software-postlaunch
```

`do` 识别领域、生命周期、意图与风险，并创建主链画布。`chain` 渲染同一份机器真值：

```text
04-findings/product-reasoning.json   七节点、推导、假设、反证与决策状态
06-report/product-reasoning.md       人类可读投影
```

每个节点都必须填写：

- `statement`：当前判断；
- `rationale`：为什么能从上一节点推到本节点；
- `assumptions`：推导成立还必须假设什么；
- `evidence_ids`：哪些已登记证据支持它；
- `status`：hypothesis / needs-validation / validated / rejected / deprioritized。

特性还要记录备选方案和接受条件；产品还要记录形态、范围、非目标和验收；商业节点还要记录市场边界、细分、付费者、竞争定位、渠道、价格、成本、市场估计口径、单位经济、成功指标和商业门。链条的 `decided` 只表示记录了当前阶段的产品/商业选择，**不等于研究语义复核、工程验证、发布批准、商业成立或因果效果**。

### 2. 找最弱节点，用研究补证

```bash
askovo check ./study --stage design
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
askovo instruments ./study
askovo collect ./study --platform reddit --query "night alert" --limit 100
askovo analyze ./study --question "夜间误报"
```

`source-plan.csv` 用 `reasoning_nodes` 标明每条路线服务哪个节点，避免为了凑数据量而采集。真实采集前仍必须通过 Design gate、来源授权和适配器检查。

`analyze` 只做归一化、去重、分布、高频候选词和问题匹配片段；它不会自动生成场景、需求、特性或产品结论。

最弱节点不明显时，`askovo loop` 从审计结果推出缺口，按「缺口 × 合规来源」生成查询，在授权信封内分轮执行，每轮重新审计。采集结果只作为候选证据，闭环不分配证据等级、不修改判断。

```bash
askovo loop plan ./study
askovo loop authorize ./study --by "researcher"
askovo loop run ./study
askovo loop report ./study
```

对已有本地 JSONL 的写作/决策缺口，`analyze` 是可执行的离线候选：复用描述性分析器，写入执行记录和后续复核状态，不提升 candidate。采集仍守原授权与 Design gate；实验和外部证据请求不会自动执行。`stop` 与其他动作的正收益评分分离：只有显式 `StopDecision` 同时确认证据足够、剩余未知不改变决定、继续研究不抵成本/风险时才可排第一，否则不能为了停止而停止。

### 3. 同时审计“证据是否够”和“推理是否断”

```bash
askovo check ./study --stage full --write-report
askovo audit ./study --json
askovo review ./study                 # 决策复盘：决策就绪、可证伪、偏差与交付物新鲜度
```

两份文件分工明确：

- `product-reasoning.json`：拥有七段产品语义和推导理由；
- `demand-judgments.json`：拥有需求、方案、商业行为与反证的证据资格判断。

二者通过 `demand_judgment_id + context_key` 连接。节点引用的证据必须已经登记在对应需求判断中，不能靠修改主链文件绕过 E1/E2、E3、E4+/E5、反证和上下文门。其中痛点→需求这条推导边有明确下限：**需求节点升 validated 必须至少含一条 E2（观察到的替代/绕行/失败行为）证据，仅有 E1 口头陈述只能停在 needs-validation**——说了不算，做了才算。

完整主链也不能证明产品/商业成功；证据齐全也不能补偿缺失的推导理由。自动检查只验证结构与配置，关键语义、市场规模、单位经济仍由人工和专业复核。

### 4. 从同一主链生成不同分析与职责交付

```bash
askovo deliver ./study --kind plan    # 业务方案（业务用户默认视图）：九节业务章节 + 依据强度●◐○ + 数据基础 + 用户之声
askovo deliver ./study --kind analysis # 语料分析：采集漏斗、来源/年份/用途分布、节点覆盖与反证
askovo deliver ./study --kind decision # 决策包：机会地图/证据图/选项与权衡/决策备忘/验证清单
askovo deliver ./study --kind report   # 产品与商业推理总报告
askovo deliver ./study --kind mrd      # 市场研究与分析 → MRD
askovo deliver ./study --kind prd      # 需求研究与分析 → PRD
askovo deliver ./study --kind brd      # 商业分析 → BRD
askovo deliver ./study --kind memo     # 产品决策 memo
askovo boundary ./study --requirements req.md --output ai-prd.md  # F2 边界审计：Added/Missing/Inflated 候选清单
askovo cost ./study log --task "audit PRD" --minutes 25           # F4 核验人工分钟（可带无工具基线）
askovo deliver ./study --kind signoff   # F3 干系人签收页：结论+证据等级+边界+签名栏
askovo deliver ./study --kind ops      # 用户运营投影
askovo deliver ./study --kind tracker  # 行为、验收和商业指标跟踪
askovo report ./study                  # 用研状态：06-report/research-status.md
```

`deliver --kind report` 是产品/商业总报告的唯一写入者；`askovo report` 写独立的研究状态文件。业务方案、决策包、MRD、PRD、BRD、运营视图全部由同一条七节点主链投影生成，不是几套平行事实源。

多候选链时，业务方案先给跨链比较表与逐链结论，再把七环节正文只展开一次（优先级最高的那条）；`--kind report` 会填充产品决策一节，不再留占位。多波次语料由 `01-sources/collection-summary.json` 提供漏斗总量。依据强度按节点取级：商业节点只认 E4+/E5，反证不会把它抬成“已观察到”。

## Askovo 与 SURE

**Askovo 是产品；SURE 是底层研究与证据支撑引擎。**

- **Askovo**：主链工作区、五域路由、CLI/Skill/MCP、采集分析和角色交付。
- **SURE（Structured User Research with Evidence）**：方法选择、证据形式与等级、claim 边界、反幸存者偏差、安全门和判断约束。
- 三个入口共用 `sure_engine.py` 与 CLI 命令函数，不分叉行为。

一句话：**Askovo 负责“从用户推理到产品与商业”，SURE 负责“让每一步推理知道证据能支持到哪里”。**

**研发后的增长由 [Growovo](https://github.com/roy-tong/Growovo) 承接**：它消费 askovo 的研究判断做定位与增长（定→造→跑），一手增长反馈以同一套 E0–E5 证据分级回流——上下游交换证据，不重复造研究。

## 研究支撑能力

### 方法路由

```bash
askovo route "汽车座舱语音的接管体验怎么验证" --json
askovo methods --domain automotive --stage validation
```

汽车会路由到诊所、模拟器、封闭场地、道路或自然驾驶；消费品会路由到 CLT/HUT/复购；软件会路由到可用性、Beta、A/B 和队列。

### 平台雷达

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
```

回答“数据在哪里、能否合规获得、能帮助哪个推理节点、不能证明什么”。平台结论分为 `supported`、`limited`、`blocked`；无合规批量通道时，只接受授权导出、研究 API 或合规历史数据集。

### 采集、队列与可复现性

- GitHub 使用官方 Search API；Reddit 使用官方 Data API；其他平台使用授权导出、历史数据集或本地 fixture。
- 每次采集保存 raw envelope、normalized 和 manifest，记录访问依据、权利、条数、丢弃原因、限制和偏差。
- SQLite 队列支持多 worker、租约回收、失败退避、限速和断点续跑。
- CDP 仅限 amazon / instagram / bilibili / weibo 的授权可见页面；X / YouTube 和 blocked 平台不使用它，不绕过验证码、登录墙或平台控制。

详见 [平台与连接器](docs/connectors.md) 和 [CLI 参考](docs/cli.md)。

## 六类结论不能混

| 类型 | 回答 | 不能替代 |
|---|---|---|
| need | 谁在什么场景有什么未满足任务 | 功能请求、个案、普遍率 |
| acceptance | 用户是否理解/接受方案 | 喜欢≠会用/会买 |
| usability | 能否完成任务、是否易学低错 | 好用≠需求成立 |
| performance | 明确条件下是否达标 | 跑分≠体验 |
| commercial | 购买、留存、复购、退换 | 口头意愿≠交易 |
| safety | 使用风险与合规缺口 | 用户试验≠认证 |

E0–E5 只描述需求与商业证据强度，不是产品/商业推理得分。可用性、工程性能、安全、可行性、商业门和发布门分别有各自的验证要求。

## 边界

- 不做未授权抓取，不绕过 blocked connector、登录墙、验证码或平台挑战。
- 不把平台可用当样本代表总体，不把记录数当用户数或客群规模。
- 不把功能提及频率当需求，不把购买意愿当真实购买，不把采用率当产品结果。
- 不把一次喜欢当复购，不把 Beta、无投诉或零事件当安全或可发布。
- 不让需求证据替代可用性、性能、安全、工程 V&V、法规或认证。
- 高风险研究停在 S0，Agent 只能出方案，不能指导执行。
- 所有交付默认草稿；CLI 通过不替代人工语义复核、产品签收或风险接受。

## 安装

Askovo 已发布到 PyPI。用 `pipx` 安装已发布包：

```bash
pipx install askovo
askovo --version
askovo decision --help
```

或使用 venv：

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install askovo
.venv/bin/askovo demo
```

在源码仓库内开发时，改用 `pip install -e .`。

核心 CLI、Skill、MCP 只使用 Python 标准库，兼容 Python 3.9–3.12。可选 Workbook XLSX 和 Amazon HF 工具分别声明 openpyxl/datasets 依赖。

**Agent Skill**

```bash
bash scripts/install-skill.sh
bash scripts/install-skill.sh ~/.codex/skills
```

**MCP**

```json
{
  "mcpServers": {
    "askovo": {
      "command": "askovo",
      "args": ["mcp"]
    }
  }
}
```

MCP 暴露 `askovo_route`、`askovo_do`、`askovo_chain`、`askovo_platforms`、`askovo_collect`、`askovo_analyze`、`askovo_audit`、`askovo_decision`、`askovo_deliver` 等工具，与 CLI 共用行为；`collect` 默认 dry-run。

## 服务与支持

**引擎永久免费开源**：CLI、Agent Skill、MCP 与五域基础领域包均为 MIT，无功能阉割版。付费的只可能是深度领域资产与人工交付，永远不是引擎本身。

| 能力 | 当前边界 |
|---|---|
| 七节点推理链与决策包/MRD/PRD/BRD 投影 | 结构与证据引用自动校验；语义复核由人负责 |
| 证据分级审计（E0–E5，退出码进 CI） | 只验结构与配置门，不证明需求普遍率或市场成功 |
| 平台雷达与采集 | blocked 平台不绕过；采集前须过 Design gate 与授权检查 |
| 人工交付（需求验证 study / 团队工作坊） | 范围与费用按任务商定；商业复购仍在验证 |

人工交付**不公布标准价目**：先邮件 <a href="mailto:tongroy18@gmail.com?subject=Askovo%20%E9%9C%80%E6%B1%82%E9%AA%8C%E8%AF%81%20%E2%80%94%20%E4%BB%BB%E5%8A%A1%E5%88%9D%E5%88%A4&body=%E4%BA%A7%E5%93%81%E4%B8%8E%E9%A2%86%E5%9F%9F%EF%BC%88%E8%BD%AF%E4%BB%B6/%E7%A1%AC%E4%BB%B6/%E6%B6%88%E8%B4%B9%E5%93%81/%E6%B1%BD%E8%BD%A6/%E6%89%8B%E6%9C%BA%EF%BC%89%EF%BC%9A%0A%E6%83%B3%E9%AA%8C%E8%AF%81%E7%9A%84%E9%9C%80%E6%B1%82%E6%88%96%E5%86%B3%E7%AD%96%E9%97%AE%E9%A2%98%EF%BC%9A%0A%E5%86%B3%E7%AD%96%E6%88%96%E8%AF%84%E5%AE%A1%E6%97%A5%E6%9C%9F%EF%BC%9A%0A%E5%B7%B2%E6%9C%89%E7%9A%84%E8%B5%84%E6%96%99%E7%B1%BB%E5%9E%8B%EF%BC%88%E9%A6%96%E5%B0%81%E9%82%AE%E4%BB%B6%E8%AF%B7%E5%8B%BF%E9%99%84%E5%8E%9F%E5%A7%8B%E6%95%B0%E6%8D%AE%EF%BC%89%EF%BC%9A%0A%E8%B0%81%E5%AF%B9%E7%BB%93%E6%9E%9C%E8%B4%9F%E8%B4%A3%EF%BC%9A%0A">tongroy18@gmail.com</a> 描述任务（领域、决策问题、日期、已有资料、谁拍板），合适就给书面报价，确认后开工——[接单页](https://roy-tong.github.io/Askovo/first-look.html)。商业交付与开源引擎守同一条纪律：结论不超出证据表述，语义复核与产品签收由决策人负责。免费支持走 [GitHub Issues](https://github.com/roy-tong/askovo/issues)，响应不承诺 SLA。

<!-- 真实案例（脱敏后回填，沉淀规则见 marketing/services/services.md §4；每单交付后更新）
## 真实案例

| 领域 | 原始问题 | 最弱节点 | 补证动作 | 结论状态 |
|---|---|---|---|---|
-->

## 文档

| 文档 | 内容 |
|---|---|
| [市场、需求与商业分析](docs/business-analysis.md) | 三类分析工作流、职责边界及 MRD/PRD/BRD 的关系 |
| [岗位方法论](docs/product-methodology.md) | 五域 PM、UXR、用户运营与专业分析角色的方法依据 |
| [产品创新岗位操作系统](docs/role-operating-system.md) | 80 岗位族 × 10 生命周期 × 10 行业的职责、KPI、SOP、交接和模板 |
| [产品与商业推理主链](docs/product-reasoning.md) | 七节点、推导边、商业门、反证和人工复核 |
| [快速开始](docs/quickstart.md) | 从 do 到主链、补证、审计和角色交付 |
| [核心概念](docs/concepts.md) | 六类结论、证据形式和禁止推断 |
| [五类产品](docs/modes.md) | 同一主链下的领域验证差异 |
| [数据契约](docs/data-contract.md) | product-reasoning、study、evidence、judgments |
| [SURE 引擎](docs/sure-engine.md) | 产品主链与研究支撑引擎的分工 |
| [平台与连接器](docs/connectors.md) | 平台档位、访问方式和抓取边界 |
| [CLI 参考](docs/cli.md) | 命令、参数、产物和退出码 |
| [故障排查](docs/troubleshooting.md) | 安装、路由、断链、采集和 MCP |

Agent 入口：[llms.txt](llms.txt) · [AGENTS.md](AGENTS.md) · [SKILL.md](skills/askovo/SKILL.md)。

## 仓库结构

```text
skills/askovo/
  SKILL.md                     单入口协议与判断规则
  assets/domain-packs/         五类产品研究包（不改主链）
  assets/study-template/       含 product-reasoning 的工作区模板
  references/                  研究、主链、数据与连接器协议
  templates/                   MRD/PRD/BRD 与访谈支撑模板
  scripts/askovo.py            确定性 CLI（唯一行为真值）
  scripts/sure_engine.py       SURE 支撑引擎与主链脚手架
  scripts/askovo_mcp.py        MCP 外壳
docs/                          中文产品与方法论文档
examples/sample-study/         含完整主链的离线合成样例
tests/                         CLI、主链、路由、平台、队列、MCP 测试
```

参与与发布：[贡献指南](CONTRIBUTING.md) · [安全政策](SECURITY.md) · [发布流程](RELEASING.md) · [行为准则](CODE_OF_CONDUCT.md)。如果 Askovo 帮到了你，给仓库一个 star 能帮更多人找到它——完全自愿，不设任何前提。

## License

MIT。第三方组件与数据权利边界见 [LICENSE](LICENSE) 与 [docs/connectors.md](docs/connectors.md)。

## 本地文档摄入（可选 Docling 适配器）

无需把 PDF 或 Office 文件复制进聊天。这个**本地、显式授权的提取**把文件转成 Markdown，并生成带 SHA-256 的来源旁车文件。它不证明文档内容、来源权利或任何业务结论。

```bash
# 当前 Docling 需要 Python 3.10+；Askovo 基础安装仍保持零依赖
pip install docling
askovo document ./research-report.pdf --out ./report-extracted.md
# 先把提取文本当作证据前，阅读 provenance 并确认来源权利。
askovo import ./my-study ./report-extracted.md --source-family imported
askovo audit ./my-study
```

纯 UTF-8 `.txt` / `.md` 不需要 Docling。生成的 `.provenance.json` 记录原文件哈希，并把提取标为 `unreviewed`；它不会让未获授权的公开平台抓取变得合规。见[能力进度](docs/feature-status.md)。


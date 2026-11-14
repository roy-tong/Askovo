# Askovo 文档

askovo 用同一主链服务五域产品经理、用户研究、用户运营及市场/需求/商业分析职责，也服务转型全栈、要自己挖需求定产品的研发：**场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业**。Skill 负责判断，CLI 负责确定性操作，MCP 只包装同一命令行为。

第一次来，按这个顺序读：

1. [快速开始](quickstart.md) —— 从 `do/chain` 到补证、审计和角色交付。
2. [产品与商业推理主链](product-reasoning.md) —— 七节点、推导边、商业门、反证与人工复核。
3. [市场、需求与商业分析](business-analysis.md) —— 三条分析工作流及 MRD/PRD/BRD 的关系。
4. [岗位方法论](product-methodology.md) —— 五域 PM、资深 UXR、用户运营与分析职责的方法来源。
5. [产品创新岗位操作系统](role-operating-system.md) —— 80 岗位族 × 10 生命周期 × 10 行业的职责、KPI、SOP、交接与模板。
6. [五类产品](modes.md) —— 同一主链下的配置、验证和专业门差异。
7. [研究模式](research-modes.md) —— Discover / Validate / Optimize 的入口节点、上游假设与研究契约。
8. [核心概念](concepts.md) —— 六类结论、证据形式、E0–E5 的适用范围。
9. [数据契约](data-contract.md) —— product-reasoning、study、evidence、judgments、商业节点与报告写入权。
10. [CLI 参考](cli.md) —— 命令、参数、产物和退出码。
11. [平台与连接器](connectors.md) —— 数据在哪、如何合规补证、哪些路线被阻断。
12. [研究闭环](research-loop.md) —— 缺口检测、信封授权、多轮复审与候选证据。
13. [决策复盘](cli.md#review决策复盘) —— 审计门、决策就绪、可证伪、偏差与交付物核验。
14. [SURE 引擎](sure-engine.md) —— 产品主链与研究支撑引擎的关系。
15. [故障排查](troubleshooting.md) —— 安装、断链、门禁、采集与 MCP。
16. [十二项证据检查](plan-evidence-check.md) —— 评审前过一遍：目标、因果链、判据、反证、成本、单点假设。
17. [开源集成清单](open-source-integrations.md) —— 三个产品对 Docling/Playwright/Stagehand 等组件的实际接入状态与取舍。

| 你想做什么 | 去哪 |
| --- | --- |
| 评审前检查一份计划撑不撑得住 | [十二项证据检查](plan-evidence-check.md)：一张可复制的表 + 一次真实演练 |
| 判断该用 Discover / Validate / Optimize 哪种研究模式 | `askovo mode "<需求>"`（见 [研究模式](research-modes.md)） |
| 出一份业务方案（给产品/市场问题） | `askovo deliver <study> --kind plan`（见 [CLI 参考](cli.md)） |
| 我是研发转型全栈，要自己挖需求、定产品 | [快速开始·研发转全栈](quickstart.md#研发转全栈先证据后编码) 与[全栈研发入门手册](../skills/askovo/references/fullstack-developer-playbook.md) |
| 看语料分布与判断覆盖 | `askovo deliver <study> --kind analysis` |
| 查 80 岗位职责/KPI/SOP、组队与交付模板 | [岗位操作系统](role-operating-system.md) 与 `askovo roles ...` |
| 生成岗位交付或生命周期导航 | `askovo deliver <study> --kind role --role R52` / `--kind lifecycle` |
| 让 Agent 按协议工作 | [../skills/askovo/SKILL.md](../skills/askovo/SKILL.md) |
| 编写主链或证据记录 | [../skills/askovo/references/product-reasoning.md](../skills/askovo/references/product-reasoning.md) 与 [data-contract](../skills/askovo/references/data-contract.md) |
| 生成 MRD/PRD/BRD | [整合模板](../skills/askovo/templates/integration-docs/runbook.md) |
| 用访谈补证 | [访谈模板](../skills/askovo/templates/interview-kit/runbook.md) |
| 看平台具体规则 | [../skills/askovo/references/](../skills/askovo/references/) |
| 给 Agent 做发现入口 | [../llms.txt](../llms.txt) |

## 一句话原则

> 先证明推导没有断，再看证据能支持到哪里；记录数不是用户数，主链完整不等于产品/商业成功，门禁通过不等于人工签收。

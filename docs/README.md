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
11. [平台与连接器](connectors.md) —— 数据在哪、如何合规补证、哪些路线被阻断；多平台采集手册（通道决策树 / CDP 操作 / 反自动化纪律）见 `skills/askovo/references/cdp-collection-playbook.md`；平台限制与解法的机器可读注册表见 [平台实战笔记](platform-field-notes.md)。
12. [研究闭环](research-loop.md) —— 缺口检测、信封授权、多轮复审与候选证据。
13. [一问题研究执行器](decide.md) —— 一个问题 → 一个受跟踪任务：`decide start/status/brief/cancel`、C-01 状态字段、partial 产物与记录上限。
14. [Issue 结构化](issues.md) —— 公开 Issue 导出 → 机器候选 → 人工接受：13 个候选字段、A13–A18 语义规则、选择偏差与私有内容边界。
15. [Decision Brief](decision-brief.md) —— 一页决策九节：结论/选项/证据与反证/受限结论/不做的选择/下一动作/PRD 验收/四态，以及 `stale` 门禁与数字来源。
16. [增量研究 Delta](research-delta.md) —— append-only 证据快照、新增/变更/删除来源、受影响节点与反证影响、`needs_re_review` 与降级可读。
17. [外部研究桥](external-bridge.md) —— 子进程安全边界：环境白名单、签名命令、有界输出、独立 run id、输出路径不可逃逸、URL 只是候选。
18. [决策复盘](cli.md#review决策复盘) —— 审计门、决策就绪、可证伪、偏差与交付物核验。
19. [SURE 引擎](sure-engine.md) —— 产品主链与研究支撑引擎的关系。
20. [故障排查](troubleshooting.md) —— 安装、断链、门禁、采集与 MCP。
21. [十二项证据检查](plan-evidence-check.md) —— 评审前过一遍：目标、因果链、判据、反证、成本、单点假设。
22. [开源集成清单](open-source-integrations.md) —— 三个产品对 Docling/Playwright/Stagehand 等组件的实际接入状态与取舍。
23. [CDP/OCR 候选审核](capture.md) —— 候选抓取、具名审核入证据、分析与业务交付来源回链。
24. [机器可读交付合同](delivery-contract.json) —— 定量/定性研究到做/缓做/不做业务结论、采购门与独立业务结果边界。
25. [2026-11 采集战役复盘](campaign-postmortem-20261117.md) —— 问题 → 根因 → 有效解法 → 沉淀位置（风控 / 平台通道 / 数据管线）。

| 你想做什么 | 去哪 |
| --- | --- |
| 评审前检查一份计划撑不撑得住 | [十二项证据检查](plan-evidence-check.md)：一张可复制的表 + 一次真实演练 |
| 判断该用 Discover / Validate / Optimize 哪种研究模式 | `askovo mode "<需求>"`（见 [研究模式](research-modes.md)） |
| 把一个问题变成一个受跟踪、可恢复、不越权的任务 | `askovo decide start --input task.json`（见 [一问题研究执行器](decide.md)） |
| 把一堆公开 Issue 变成可复核的用户任务/需求 | `askovo issues import/…/accept`（见 [Issue 结构化](issues.md)） |
| 把研究结论压成一页可复核的决策 Brief | `askovo brief <study>`（见 [Decision Brief](decision-brief.md)） |
| 新素材进来时只看差异、不覆盖历史 | `askovo delta sync/show`（见 [增量研究 Delta](research-delta.md)） |
| 跑一个外部研究适配器又不给进程开全权限 | `askovo external-research --command <id> --authorize`（见 [外部研究桥](external-bridge.md)） |
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
| 看一次真实采集战役踩过哪些坑、怎么修的 | [2026-11 采集战役复盘](campaign-postmortem-20261117.md) |
| 给 Agent 做发现入口 | [../llms.txt](../llms.txt) |

## 一句话原则

> 先证明推导没有断，再看证据能支持到哪里；记录数不是用户数，主链完整不等于产品/商业成功，门禁通过不等于人工签收。

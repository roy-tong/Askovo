# 五域产品、用户、市场、需求与商业分析方法论

研究日期：2026-10-30。本文用于解释 Askovo 为什么采用当前主链、状态与交付设计，而不是给所有行业规定一套僵化流程。

## 1. 研究口径

本研究覆盖五域产品经理、资深用户研究（UXR）、用户运营，以及市场研究/分析、需求研究/分析、商业分析职责。资料优先采用方法提出者、政府/标准组织、平台官方文档和一手方法供应商资料；供应商材料只用于说明方法及数据形态，不采用营销效果数字。

下文区分：

- **来源方法**：链接资料直接表达或可以贴近转述的主张；
- **Askovo 设计**：我们跨来源作出的产品模型、字段与门禁选择，不是标准条文。

核心参考包括：[Opportunity Solution Trees](https://www.producttalk.org/opportunity-solution-trees/)、[GOV.UK 用户需求](https://www.gov.uk/service-manual/user-research/start-by-learning-user-needs)、[NASA 产品实现](https://www.nasa.gov/reference/5-0-product-realization/)、[Stage-Gate 官方模型](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/)、[Mixpanel 留存](https://docs.mixpanel.com/docs/reports/retention)、[ISO 11136](https://www.iso.org/standard/50125.html)、[AMA marketing research](https://www.ama.org/the-definition-of-marketing-what-is-marketing/)、[ICC/ESOMAR 研究守则](https://iccwbo.org/news-publications/business-solutions/iccesomar-international-code-market-opinion-social-research-data-analytics/)、[IIBA/BABOK requirements](https://www.iiba.org/career-resources/a-business-analysis-professionals-foundation-for-success/babok/glossary/)、[ISO/IEC/IEEE 29148](https://www.iso.org/standard/72089.html)、[AAPOR 披露标准](https://aapor.org/standards-and-ethics/disclosure-standards/)。

## 2. 核心结论

### 2.1 主链是共同语言，不是完整产品开发宇宙

askovo 采用：

> **场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业**

它回答“为什么值得为谁、在什么情境、做什么产品”。资深岗位的实际工作还同时管理：

- 业务结果、战略与组合资源；
- 多候选方案与关键假设；
- 技术可行性、可用性、伦理与商业可行性；
- 系统需求、接口、配置基线与变更；
- 性能、功能安全、SOTIF、网络安全、法规和认证；
- 制造、供应链、服务与发布；
- 上线结果、实验因果和运营回流。

商业是主链第七个节点；合规、安全、配置基线、供应链、发布和因果实验等仍不能全部硬塞成第八、第九个业务节点。它们与主链是正交支撑层。

### 2.2 主链不是严格时间顺序

[OST](https://www.producttalk.org/opportunity-solution-trees/) 以期望结果为根，连接机会、多个方案与假设测试；[双轨开发](https://jpattonassociates.com/dual-track-development/) 将快速学习的 Discovery 与质量交付的 Development 并行；[Stage-Gate](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/) 也强调阶段内跨职能并行、反复迭代和跨职能资源决策。

因此，团队可以从业务结果、异常行为、用户请求、候选方案或一次运营干预开始，再回到主链检查缺环。展示顺序保持七节点，实际学习是循环。

### 2.3 最该审计的是推导边

资深工作不是“每个格子都有材料”，而是能解释：

- 为什么这个场景中的这类用户有这个痛点；
- 为什么痛点构成值得投入的用户需求；
- 为什么这个特性比其他候选更能改变结果；
- 为什么这些特性组成一个有边界的产品；
- 当前证据是否真的支持这些推导；
- 什么反例会改变决定。

**Askovo 设计**：节点保存 `statement/status/evidence_ids/assumptions`，incoming edge 保存 `rationale`；chain 另存替代解释、反证、人工复核、缺口和下一验证。节点有证据不等于边成立。

### 2.4 五种状态必须分开

1. **需求证据状态**：现有材料能支持需求与商业行为到哪一步；
2. **产品选择状态**：团队当前选择了哪个方案，保留多少风险；
3. **交付质量状态**：是否达到可用性、性能、合规、兼容和回滚要求；
4. **上线观察状态**：实际结果为正、无效、为负或尚不确定；
5. **因果状态**：是否有合适设计和执行支持干预导致结果。

E3 方案接受不等于 release-ready；E5 真实使用或留存不等于干预因果；`decided` 不等于 PRD 签收、商业成功或因果成立。

## 3. 多类职责的共同工作循环

| 环节 | 资深岗位实际要回答 | 共同产物 |
|---|---|---|
| 决策立项 | 要改变哪个结果？谁决定？何时？有哪些选项和错误代价？ | Decision brief、baseline/target、guardrail、非目标 |
| 场景与机会发现 | 谁在什么触发下取得什么进展？当前替代为何不够？ | 情境记录、JTBD、机会地图、反例 |
| 机会选择 | 为什么是这个机会，而不是声量最大或最近出现的请求？ | 优先级 memo、覆盖矩阵、战略与替代成本 |
| 多方案与假设测试 | 哪些候选可行？哪个危险假设最可能让方案失败？ | 方案比较、assumption map、预定阈值 |
| 市场研究与分析 | 哪个边界/细分/渠道/价格值得进入？证据和不确定性是什么？ | MRD、市场边界、规模口径、竞争与进入假设 |
| 需求研究与分析 | 用户/市场需要如何转为可验收、可追溯的产品要求？ | PRD、需求优先级、验收、追溯和变更 |
| 商业分析 | 产品如何形成收入、成本、单位经济和资源门？ | BRD、商业模型、单位经济、G0–G2 和停止条件 |
| 产品定义与交付 | 选中的能力如何形成有边界的产品？怎样验收、发布和回滚？ | 需求追溯、PRD、DoD、配置与发布计划 |
| 上线与学习 | 观察到哪种结果？有无副作用？能否声称因果？ | 队列/实验结果、决策日志、复盘与回写 |

[Stage-Gate](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/) 的 Gate 输出是 Go/Kill/Hold/Recycle、资源承诺、条件和下一计划，不是“文档完成百分比”。因此 Askovo 把结构检查与人工资源/风险决策分开。

### 3.1 三类分析与职责覆盖

| 工作流 | 主要职责 | 正式产出 | 当前项目覆盖 |
|---|---|---|---|
| 市场研究与市场分析 | 市场研究、市场分析、战略/洞察角色，PM 组织并决策 | MRD | 商业节点市场字段 + `deliver --kind mrd` |
| 需求研究与需求分析 | 需求分析、产品经理、UXR/UO 提供用户与行为证据 | PRD | need→feature→product 追溯 + 优先级/验收/变更 + `deliver --kind prd` |
| 商业分析 | 商业分析、PM、财务/战略复核 | BRD | business 节点 + `deliver --kind brd` |

- **产品经理**对全链决策、优先级、范围、资源与剩余风险负责，可用 BRD 记录商业选择；
- **用户研究**对用户需求证据、抽样、反证和语义边界负责，不拥有最终商业门；
- **用户运营**对真实行为、分群、干预和反馈回流负责，可触达用户不是全市场；
- **市场研究/分析**对市场事实、边界、细分、替代、渠道、价格和规模口径负责；
- **需求分析**对需求表达、优先级、验收、追溯和变更负责；
- **商业分析**对收入、成本、单位经济、资源门和 BRD 负责。

一个团队可以让 PM 兼任多项，但工作流与产出不能混。详细规则见[市场、需求与商业分析](business-analysis.md)。

## 4. 五域产品经理如何工作

### 4.1 软件 / SaaS

**来源方法**：[OST](https://www.producttalk.org/opportunity-solution-trees/) 要求从 product outcome 到机会、方案和假设测试；[Assumption Testing](https://www.producttalk.org/assumption-testing/) 强调优先测试关键且证据弱的假设；[Scrum Guide](https://scrumguides.org/scrum-guide.html) 以 Product Goal、排序 backlog 和满足 DoD 的 Increment 管理价值交付。

**实际工作**：

1. 将业务目标翻译成团队可影响的产品结果，而非只写“上线某功能”；
2. 通过真实工作流和近期事件重建场景、任务、替代与后果；
3. 按用户结果、替代满意度、战略与覆盖比较机会，而非按请求声量；
4. 对高风险机会生成多个候选，测试 desirability/usability/feasibility/viability/ethical 假设；
5. 将进入交付的方案拆成有顺序的目标、验收、埋点、护栏和回滚；
6. 发布后结合实验、队列、工单和访谈继续调整机会空间。

**领域门**：任务可用性、Beta 质量、A/B 实验可信度、版本兼容、队列留存。点击、报名或单次喜欢不能替代持续价值。

### 4.2 手机 / 移动 / 可穿戴

移动 PM 继承软件流程，同时把平台约束前置到场景与方案阶段。

**来源方法**：[Android Core App Quality](https://developer.android.google.cn/docs/quality-guidelines/core-app-quality?hl=en) 覆盖生命周期、导航、可访问性、稳定性、耗电、权限与政策；[Android Activity Lifecycle](https://developer.android.google.cn/guide/components/activities/activity-lifecycle?hl=en) 要求处理配置变化、进程回收和状态恢复；[Apple App Review](https://developer.apple.com/app-store/review/guidelines/) 要求崩溃/bug、审核访问和后端等准备；[Apple Phased Release](https://developer.apple.com/help/app-store-connect/update-your-app/release-a-version-update-in-phases/) 是分阶段发布机制，不是随机对照实验。

**实际工作**：

1. 定义设备形态、OS/App 版本、网络、locale、权限与前后台支持矩阵；
2. 研究切 App、锁屏、来电、旋转/折叠、多窗口、弱网、权限拒绝和进程死亡后的任务连续性；
3. 同时评估用户结果、可访问性、启动/渲染、崩溃/ANR、耗电/内存、最小权限、SDK 与商店规则；
4. 独立执行 release readiness：真实设备矩阵、后端与旧版兼容、商店材料、灰度、暂停和回滚；
5. 用版本×设备×OS×队列观察 vitals、采用、留存与售后，处理新 OS/SDK/政策变化。

**领域门**：移动质量和发布门与需求/方案接受分开。Android Vitals 还有自身采集覆盖和时间窗口，不能与自有 session 口径直接混比。

### 4.3 硬件 / IoT / 消费电子

**来源方法**：NASA 将系统设计、实现、集成、验证和确认连接，并要求需求与利益相关者期望双向追溯；[NASA 4.0](https://www.nasa.gov/reference/4-0-system-design-processes/) 与 [NASA 5.0](https://www.nasa.gov/reference/5-0-product-realization/) 区分“产品做得对”与“做对了产品”。EVT/DVT/PVT 是行业实践术语而非统一国际标准；[OpenBOM 说明](https://www.openbom.com/blog/evt-vs-dvt-vs-pvt-understanding-the-stages-of-product-development) 仅用于理解常见分工，不能据此内置固定样机数量或周期。

**实际工作**：

1. 建立 ConOps：使用者、安装者、维护者、购买者、旁观者、物理环境与异常恢复；
2. 比较 ID/CMF、架构、关键器件、成本、供应和制造路径；
3. 将期望转成带单位、阈值、容差、环境条件、接口和验证方法的系统需求；
4. 通过原理/工程样机、完整设计验证和现场 Beta 分别暴露架构、性能与真实使用问题；
5. 验证生产线、工装、测试程序、供应和批次一致性，管理偏差、工程变更与回归；
6. 按装机量、销量和使用时长分母分析 RMA、遥测和投诉。

**领域门**：每个结论绑定 HW/FW/BOM/工艺配置基线。设计验证、过程验证、现场好用和商业成立分别判断；EVT/DVT/PVT 不替代用户价值。

### 4.4 消费品 / 食品饮料 / 美妆个护 / 家居日用品

**来源方法**：[NIQ 概念测试](https://nielseniq.com/global/en/solutions/bases-idea-concept-claims-testing/) 用于早期概念筛选；[ISO 11136](https://www.iso.org/standard/50125.html) 是受控区域消费者喜欢/相对喜欢程度的方法，明确不包括自由摄取量等行为测量；[NIQ 产品测试](https://nielseniq.com/global/en/solutions/bases-product-testing/) 区分 CLT 与 in-home；[Kantar 连续购买行为](https://www.kantar.com/solutions/signal-intelligence/consumer-and-shopper-behaviour) 说明真实复购需要另一数据形态。

**实际工作**：

1. 区分购买者、使用者、家庭成员和弃用者，研究购买、准备、使用、储存、分享和处置场合；
2. 测试概念、包装和宣称的理解、相关性、差异化与申报意向；
3. 以受控 CLT/感官设计比较喜好、偏好或差异，控制盲法、顺序、携带、疲劳和品牌信息；
4. 以 HUT 观察真实准备、用量、共享、储存、摩擦与弃用；
5. 独立确认配方/工艺放大、保质期/稳定性、包材相容、法规宣称、产能和单位经济性；
6. 用首购付费队列和明确购买周期观察再次付费，处理渠道、缺货和促销混杂。

**领域门**：概念接受、受控喜好、家庭使用、真实复购、法规/质量放行不可互替。免费样品继续使用不是复购，感官喜好不是功效或安全。

### 4.5 汽车 / 智能座舱 / ADAS / 车载软件

**来源方法**：[NHTSA 视觉—手动次任务指南](https://www.federalregister.gov/documents/full_text/text/2013/04/26/2013-09883.txt) 有明确适用任务、方法和接受准则，不能扩张为所有 HMI/ADAS 的通用阈值；[Euro NCAP](https://www.euroncap.com/how-are-cars-tested-for-safety/) 区分 test track 与 on-road 评价；[AIAG APQP](https://www.aiag.org/training-and-resources/manuals/details/APQP-3) 和 [PPAP](https://www.aiag.org/training-and-resources/manuals/details/PPAP-4) 涉及供应质量、风险和生产件批准。

**实际工作**：

1. 定义车型/功能、驾驶员/乘客/交通参与者、ODD、HMI 次任务和合理可预见误用；
2. 用静态/动态诊所形成造型、空间、配置和 HMI 接受度证据；
3. 建立车辆—系统—部件需求、接口、配置与供应商风险追溯；
4. 用模拟器比较可重复场景下的任务错误、眼离路、workload 与接管，记录保真度与模拟病；
5. 用封闭场地验证真车受控动态响应，再在后期配置上评估实际道路/自然使用；
6. 独立推进功能安全、SOTIF、网络安全、法规、PPAP/SOP、OTA 发布与在场监测。

**领域门**：诊所偏好不证明动态安全；模拟器相对差异不证明真实事故率；场地零事件不证明开放道路安全；用户研究不替代 [ISO 26262](https://www.iso.org/standard/68383.html)、[ISO 21448](https://www.iso.org/standard/77490.html)、[ISO/SAE 21434](https://www.iso.org/standard/70918.html) 或 PPAP。道路高风险研究继续执行 S0 人工安全门。

## 5. 资深用户研究如何挑战产品推理

**来源方法**：[GOV.UK](https://www.gov.uk/service-manual/user-research/start-by-learning-user-needs) 要求需求基于研究证据、聚焦问题而非可能方案，并让用户故事可追溯需求；[Contextual Inquiry](https://www.nngroup.com/articles/contextual-inquiry/) 强调自然情境观察和共同解释；[Triangulation](https://www.nngroup.com/articles/triangulation-better-research-results-using-multiple-ux-methods/) 强调不同数据或视角，而非机械凑方法；[Information Power](https://pubmed.ncbi.nlm.nih.gov/26613970/) 说明定性样本充分性不是固定 N。

**资深 UXR 的责任**：

1. 把 PM 的预设改成可研究、可证伪的问题，明确误判代价；
2. 按场景与行为差异抽样，主动纳入非用户、流失者、满意替代者和边界人群；
3. 先观察真实事件与当前行为，再询问态度和方案；
4. 分开“看到/听到”与“我们的解释”，寻找负例和 rival explanations；
5. 将需求写成 solution-neutral 的结果，比较多个候选，而非替首个方案找支持；
6. 预先写成功、失败和补证阈值，保持证据、推理和决策三层可追溯；
7. 发布后检查原结论是被支持、缩窄、推翻还是替代，并回写主链。

**Askovo 设计**：PM 负责取舍与残余风险，UXR 负责研究设计、证据边界和语义挑战。`human_review` 记录复核与风险接受，但 CLI 不认证复核真实性。团队共识不会自动升级 E 等级，孤立负例也不能因不合预期而被删除。

## 6. 用户运营如何形成行为闭环

**来源方法**：[Mixpanel Retention](https://docs.mixpanel.com/docs/reports/retention) 以起始事件 A、回访事件 B、窗口和留存口径定义留存，并处理未成熟队列；[Mixpanel Cohorts](https://docs.mixpanel.com/docs/users/cohorts) 和 [Amplitude Behavioral Cohorts](https://amplitude.com/docs/en/analytics/behavioral-cohorts) 以实际行为规则定义群体；[Kohavi 等](https://exp-platform.com/large-scale/) 强调可信在线实验、OEC、guardrail 与告警；[Product Talk](https://www.producttalk.org/other-insights/) 提醒工单、分析和 feature request 只是碎片化输入，应引导进一步研究。

**资深用户运营的实际工作**：

1. 定义用户获得价值的 active event，而不是只用“打开 App”；
2. 建事件/属性、身份、时区、版本、分母、缺失和延迟合同；
3. 固定 A/B 事件、rolling/calendar、On/On-or-After 等口径，只比较成熟队列；
4. 按价值行为、频次、断点、流失/回流、版本和平台分群，保存规则版本与 as-of；
5. 从异常队列抽样，以访谈、观察、工单和评论解释原因；
6. 设计新手引导、内容、消息、流程或产品修复；需要因果时使用持续随机分配和预定 OEC/guardrail；
7. 将反馈→分群→主链→干预→release/experiment→队列结果→用户回复闭环，并回写学习。

**Askovo 设计**：商业是主链第七节点，运营是同一主链的投影与回流，不是额外节点。反馈记录数不是客群规模，行为数据的 what 不自动解释 why，前后变化不自动等于干预效果。

## 7. 对 Askovo 的落地约束

| 方法结论 | 当前实现 |
|---|---|
| 七节点是共同价值叙事 | `04-findings/product-reasoning.json` 为唯一主链机器真值 |
| 一条 chain 是一条价值线程 | 多场景、多候选用多 chain 表达，不把互斥方案混成一个节点 |
| 节点证据不等于推导成立 | 每节点有 rationale/assumptions；chain 有替代解释、反证和人工复核 |
| 需求与商业证据单独审计 | `demand-judgments.json` 保留 E1/E2 + E3 + E4+/E5 + counter + context 门 |
| 主链不能绕过证据门 | 节点证据必须是 linked judgment 登记证据的子集 |
| 产品/商业选择不等于发布或结果 | `supporting_states.delivery/outcome/causal` 独立，分别引用 release/metric/experiment |
| 领域差异在验证层，不在主链 schema | 五个 domain packs 共用七节点，分别改变方法、风险与验收 |
| 多职责共享事实源 | PM 读 memo/report，UXR 读 research-status/audit，运营读 ops/tracker，市场/需求/商业分析产出 MRD/PRD/BRD |
| 商业分析不靠财务假设代替证据 | business 节点记录市场、价格、成本、单位经济、指标与资源门 |
| 外部专业系统不重造 | PLM/QMS/法规/认证/实验平台通过稳定引用与复核状态连接 |

### 仍需人工和外部专业责任的内容

askovo 不自动完成 ISO 合规、道路安全、量产放行、法规功效、安全认证或因果证明。结构检查通过只说明配置的字段、引用和证据链自洽；产品 Go/Kill/Hold/Recycle、风险豁免和资源承诺仍由有责任的跨职能人员决定。

## 8. 最终研究原则

1. 先问要改变什么决策，再问需要多少数据。
2. 先建立主链假设，再选择最危险且证据最弱的节点或边。
3. 需求必须解法中立，特性必须有候选比较，产品必须有边界，商业必须有机会、成本和资源门。
4. 证据质量、推理 warrant 和决策充分性分别评价。
5. 用户价值、工程质量、上线结果、商业结果和因果效果分别放行。
6. 市场研究、需求研究、商业分析是过程；MRD、PRD、BRD 是对应产出，不是三套事实源。
7. 每个结论同时回答：对哪个用户场景、哪个配置、哪个价格/渠道、哪个时间窗成立。
8. 上线不是研究终点；反证、版本变化和运营学习必须能 reopen 主链。

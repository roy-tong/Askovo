# CLI 参考

`askovo` 只有一个入口。所有产品类型、方法、采集与分析能力都从同一行命令路由，不需要为软件/硬件/消费/汽车/手机分别安装。

```bash
askovo --version
askovo --help
```

## 命令总览

| 命令 | 用途 | 退出码 |
|---|---|---|
| `do "<需求>"` | **单入口**：路由 + 创建主链画布、研究计划、证据计划与工具包 | 0/2/4 |
| `route "<需求>"` | 只路由，不写文件 | 0/2 |
| `platforms "<需求>"` | 平台雷达：数据在哪、能否合规拿到、能证明什么 | 0/2 |
| `collect <study>` | 通过 design gate 后运行采集适配器/本地导出/CDP，写 raw、manifest 与 normalized | 0/1/2/3/4 |
| `research plan/authorize/run/status` | 宿主给定动作清单的逐条授权与受控执行 | 0/1/2/3/4 |
| `loop plan/authorize/run/status/report` | 缺口驱动的多轮受控采集、每轮复审、候选证据与复盘 | 0/1/2/3/4 |
| `queue init/add/run/status/retry` | SQLite 队列、worker、重试、限速、断点续跑 | 0/1/2 |
| `analyze <study>` | 归一化、去重、分布、候选主题、问题匹配 | 0/2 |
| `chain <study>` | 生成/渲染“场景→用户→痛点→需求→特性→产品→商业”推理链 | 0/2 |
| `economics <study>` | business 节点单位经济投影（算术投影，null=未知） | 0/2 |
| `psm <study> --input <csv>` | van Westendorp 价格敏感度四问分析 | 0/1/2 |
| `instruments <study>` | 生成访谈/观察/任务/感官/价格/Beta/安全工具包 | 0/2 |
| `import <study> <file>` | 导入 JSONL/CSV/文本为证据 | 0/2 |
| `codebook <study>` | 生成六类结论的编码本 | 0/2 |
| `deliver <study>` | 决策包 decision / 主链 memo / 总 report / MRD / PRD / BRD / 运营 ops / tracker / 签收 signoff | 0/2 |
| `report <study>` | 中文研究状态报告（UXR 视角）→ `06-report/research-status.md` | 0/2 |
| `signals <study>` | 从 evidence.jsonl 计算确定性语料信号 | 0/2 |
| `lexicon <study>` | 未命名体验模式：词表产出与充分性检查 | 0/1/2 |
| `init <study_dir>` | 从模板创建研究工作区（`do` 之外的支撑入口） | 0/2 |
| `methods` | 按领域与阶段列方法 | 0/2 |
| `domains` | 列五个研究包 | 0 |
| `catalog` | 列方法目录 | 0 |
| `connectors` | 列开源连接器评审决策（含 blocked 及原因） | 0/2 |
| `check <study>` | 单阶段门检查（design/evidence/decision/full） | 0/1/2 |
| `audit` | 主链、证据与逐条需求判断的统一审计 | 0/1/2 |
| `review <study>` | 决策复盘：审计门、证据、决策就绪、可证伪、偏差、交付物新鲜度 | 0/1/2 |
| `plan` | 支撑入口：平台可行性、配额与补证路线 | 0/2/3 |
| `stage <name>` | 转发到 `scripts/stages/` 数据集流水线工具 | 0/1/2 |
| `label <dir>` | 一等命令：对分析项目 raw 记录做规则打标（候选发现，非金标证据） | 0/1/2 |
| `build <dir>` | 一等命令：从 raw 记录构建主分析数据集（含反证 control 桶） | 0/1/2 |
| `doctor` | 运行时、目录、研究包、平台目录、版本自检 | 0/1 |
| `demo` | 内置样例 | 0/1/2 |

退出码：

| 码 | 含义 |
|---|---|
| 0 | 成功/门禁通过 |
| 1 | 证据或命题门禁未过（合法研究状态） |
| 2 | 用法、数据或环境错误 |
| 3 | 没有可行平台/适配器，必须报告缺口 |
| 4 | 安全/伦理门未通过，或 CDP 条款未确认，禁止进入执行 |

## do

```bash
askovo do "家用摄像头夜间告警误报，想验证样机"
askovo do "手机相机夜景和续航" --study ./phone-study
askovo do "汽车开放道路接管测试" --ack-risk
```

- 自动识别产品领域、阶段、意图与风险。
- 默认创建 `./askovo-<domain>-<stage>`；`--study` 指定路径。
- `--dry-run` 只输出路由，不写文件。
- 检测到道路试验、摄入/皮肤接触、儿童、敏感数据等风险时返回 `4`；只有负责人完成审查后加 `--ack-risk` 才生成计划。
- `--domain/--stage/--intent` 可覆盖自动识别。

## route

```bash
askovo route "SaaS 订阅留存下降" --json
askovo route "座舱语音接管" --domain automotive --stage validation
```

输出：`product_reasoning`（七节点、当前阶段焦点、主链产物），以及 domain、stage、intent、risk_flags、safety_gate、recommended_methods、alternatives、decisions、deliverables、platform_preview、next_commands。主链先展示，方法与平台是支撑层。

## chain

```bash
askovo chain ./study
```

如果缺少 `04-findings/product-reasoning.json` 则创建假设画布，随后渲染 `06-report/product-reasoning.md`。它不会从一句 query 或高频词自动编造七节点。每个节点需要 statement、incoming rationale、status、evidence_ids、assumptions；商业节点还需要市场边界、细分、价格、成本、单位经济、指标和业务门。`decided` 是产品/商业选择，不是发布、商业成功或因果证明。旧六节点文件仍可读取。完整规则见[产品推理主链](product-reasoning.md)。

## platforms

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
askovo platforms "SaaS 用户在 GitHub 和论坛上的抱怨" --domain software --claim-type need
```

输出推荐平台、适配分、访问方式、批量能力、限制、偏差，以及不可直接采集的平台与原因。`--bulk` 优先支持批量的来源。

## collect

```bash
askovo collect ./study --platform github --query "camera motion alert" --limit 100
askovo collect ./study --platform reddit --query "night alert" --limit 100
askovo collect ./study --platform reddit --query "night alert" --limit 100 --fixture export.jsonl
askovo collect ./study --platform github --query "..." --dry-run
askovo collect ./study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 --url "https://www.amazon.com/product-reviews/B0..." --ack-terms
```

- 非 dry-run 采集先执行 design gate；失败返回 `1` 和 `design_gate_failed`。平台还必须在 `scope.allowed_sources` 中，live/CDP 必须启用 adapter。
- GitHub：官方 Search API；`GITHUB_TOKEN` 可选。
- Reddit：官方 Data API；需要 `ASKOVO_REDDIT_CLIENT_ID`、`ASKOVO_REDDIT_CLIENT_SECRET`、可选 `ASKOVO_REDDIT_USER_AGENT`；registry 复核过期会返回 `review_expired`。
- `--fixture`：离线 JSONL/CSV，用于授权导出、历史数据集和测试；每行必须是 JSON object。
- 其他平台没有内置适配器时返回 `3`，并给出导入/授权导出路径。
- `blocked` 平台直接返回 `3`，不提供绕过方式。
- 每次采集写 `01-sources/manifests/<run_id>.json`，raw envelope 写 `02-data/raw/<platform>/`，归一化记录追加 `02-data/normalized.jsonl`；平台内按 ID + 文本 hash 双键去重，冲突写入 `blocked_or_dropped` 与 warnings。

### CDP（授权可见页面）

```bash
askovo collect ./study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms
```

- 需要 Chrome 以 `--remote-debugging-port=9222` 启动，且使用你本人已登录的 profile；
- 只抓当前页面可见文本；命中验证码/机器人检查立即停止；
- `--ack-terms` 是人工确认平台条款、账号授权、用途与保留；没有它返回 `4`；
- 仅 amazon/instagram/bilibili/weibo 开放；X/YouTube 只走官方 API，blocked 平台不开放；
- CDP 仅允许回环端点与默认端口 HTTP(S) 平台 URL，WebSocket 不得跳到其他主机或端口；
- 不伪造指纹、不绕验证码、不做无限翻页。

## research / loop（受控采集与研究闭环）

```bash
# 宿主 Agent 给出动作清单：逐条绑定哈希，人授权后才执行
askovo research plan ./study --actions actions.json
askovo research authorize ./study --by "researcher"
askovo research run ./study --max-steps 3 --analyze

# 缺口驱动：自动规划、信封授权、多轮执行并每轮复审
askovo loop plan ./study --max-rounds 3 --max-actions 3 --max-records 300
askovo loop authorize ./study --by "researcher"
askovo loop run ./study
askovo loop status ./study
askovo loop report ./study
```

- 两者都先过 Design gate，再走 `collect_platform`，平台策略、来源适配器与 `scope.allowed_sources` 校验完全一致；
- `research` 适合宿主 Agent 已经确定动作清单的场景：动作清单哈希变化后必须重新授权；
- `loop` 从审计缺口生成查询，授权对象是「信封」（允许平台、单条上限、轮次与记录预算），信封变化后授权失效；
- `loop` 每轮重新审计，停止原因见[研究闭环](research-loop.md)；
- `loop` 只产出候选证据（`04-findings/loop-candidates.json`），不分配证据等级、不改判断状态、不标 `validated`；
- MCP 可 `plan` / `status` / `report` / `run`，但不能授权。

## queue

```bash
askovo queue init ./study
askovo queue add ./study --platform reddit --query "night alert" --limit 100
askovo queue add ./study --platform github --query "camera alert" --limit 100 --max-attempts 3
askovo queue add ./study --platform amazon --query "night" --cdp-url http://127.0.0.1:9222 --url "..." --ack-terms
askovo queue run ./study --workers 4
askovo queue status ./study
askovo queue retry ./study
```

队列是 SQLite（`01-sources/queue.db`）：

- `jobs`：平台、查询、配额、fixture/CDP 参数、尝试次数、租约、错误；
- worker 用租约抢占，崩溃后租约过期自动回收；
- 失败按 5s/10s/20s… 退避重试，超过 `max_attempts` 标 failed；
- 按平台限速（默认 GitHub 6s、Reddit 2s、其他 5s），可用 `--min-interval` 覆盖；
- 每个 job 独立 run id、raw 文件与 manifest；`normalized.jsonl` 跨进程加锁去重；
- 单机多进程/多 worker 可用；跨机器共享 SQLite 不可靠，需要外部队列。

## analyze

```bash
askovo analyze ./study --question "夜间误报"
```

输出 `04-findings/analysis.json` 与 `analysis.md`：

- 记录数、平台/结论类型/证据形式/月份分布
- 平均文本长度与高频候选主题
- 与问题匹配的片段
- 边界声明：描述性统计，不证明总体或因果

## instruments

```bash
askovo instruments ./study
```

按所选方法生成：访谈提纲、观察表、任务脚本、概念测试、感官/HUT 协议、价格问卷、Beta 协议、现场/驾驶协议、测试矩阵、RMA 表、货架测试、无障碍检查、专家审阅、授权说明。已存在的文件不覆盖。

## import / codebook / deliver / report

```bash
askovo import ./study interviews.jsonl --source-family interview --claim-type need
askovo codebook ./study
askovo deliver ./study --kind memo
askovo report ./study
```

`deliver --kind`：

- `decision`：决策包（Decision Package），写 `06-report/decision-package.md`——机会地图/证据图/选项与权衡/决策备忘/验证清单五个决策侧视图，全部由同一条主链与需求判断投影；
- `memo`：产品/商业决策 memo；
- `report`：产品与商业推理总报告，写 `06-report/report.md`；
- `mrd`：市场研究与分析投影，写 `06-report/mrd.md`；
- `prd`：需求研究与分析后的特性、产品范围、非目标和验收，写 `06-report/prd.md`；
- `brd`：商业分析投影，包含市场、收入、成本、单位经济、指标和业务门，写 `06-report/brd.md`；
- `ops`：场景×用户分群、痛点/异议和运营回流，写 `06-report/user-ops.md`；
- `tracker`：从特性/产品验收和商业成功指标生成带 chain/node ID 的跟踪行，写 `06-report/postlaunch-tracker.csv`。

`askovo report` 是用研支撑报告，写 `06-report/research-status.md`；它不与产品/商业 `deliver --kind report` 共用文件。所有交付都从同一七节点主链渲染，不另建语义真值。决策包是决策侧汇总视图；MRD、PRD、BRD 分别对应市场研究/分析、需求研究/分析、商业分析三条工作流，不是三个平行事实库。

`check --stage design/evidence/full` 分别检查设计、证据和完整决策结构；`audit` 另输出逐条需求判断 verdict。返回 1 是合法研究状态，应修复主链/证据缺口或明确下一步，不能绕过。

## label / build / stage（数据集流水线）

```bash
askovo label ./analysis-project                 # 规则打标 → data/processed/feedback_labeled.jsonl.gz
askovo build ./analysis-project --min-quality 0.4  # 主数据集 → data/processed/feedback_primary.jsonl.gz
askovo stage audit-workbook sample --input data/processed/feedback_labeled.jsonl.gz
```

`label`/`build` 是 `scripts/stages/` 数据集工具的一等入口：`<dir>` 是分析项目目录（与研究工作区两回事），自动映射 `config/taxonomy.json`、`data/raw → data/processed` 缺省路径，显式传参优先，其余参数原样透传。分层不变：**规则打标=候选发现，证据=人工金标（audit-workbook 抽检 + gold-set）**，打标结果不自动升级为证据。`stage <name>` 仍是全量转发器；MCP 侧对应 `askovo_stage` 工具。

## economics / psm（商业节点支撑）

```bash
askovo economics ./study
askovo psm ./study --input pricing-survey.csv --currency CNY
```

`economics` 从 business 节点的 `pricing` 与 `unit_economics_inputs` 做确定性算术投影，写 `06-report/unit-economics.md`：只对**数值、单位匹配、带 source_ref** 的输入计算；“成本类”合计仅按名称匹配（cost/成本/费用）作为指示性结果；null 表示未知不是零；缺来源的数值列出缺口不进入计算。它是算术检查，不是商业证明——E4/E5 商业证据、财务评审与人工决策独立进行。

`psm` 读取四问 CSV（列名 `too_cheap/cheap/expensive/too_expensive`，也接受 太便宜/便宜/贵/太贵），剔除“太便宜≤便宜≤贵≤太贵”不成立的行，计算 PMC/OPP/IDP/PME 交点与可接受区间，写 `06-report/pricing-psm.md`。**PSM 是陈述意向，不是付费行为**：结果不能直接作为商业节点 validated 证据，竞品标价也不是自有定价证据。问卷可用 `instruments` 的价格工具包生成。

## boundary / cost / signoff（F2 边界审计 · F4 核验计量 · F3 签收页）

```bash
askovo boundary ./study --requirements req.md --output ai-prd.md
askovo cost ./study log --task "audit PRD" --minutes 25 --baseline-minutes 90
askovo cost ./study report
askovo deliver ./study --kind signoff
```

`boundary` 做**词法启发式对照**：把需求文档与 AI 产出文档各解析成可追溯条目（`文件:行号`），按归一化词集重合度配对，输出三类候选清单——**Added**（产出有、需求未讨论）、**Missing**（需求有、产出未见）、**Inflated**（有对应但体量数倍膨胀且引入大量新实词）。三条清单是**候选偏差不是错误判定**：语义判断（是否真属越界/遗漏/膨胀）由人工复核负责，阈值可调。报告写 `06-report/boundary-audit.md`。

`cost` 记录单次核验任务的人工分钟（可附同一任务的无工具基线口径），`report` 出算术汇总：任务数、总分钟、有基线任务的基线/实际比值。**比值不是效率证明**——基线是自报口径，样本量与可比性由人判断。

`deliver --kind signoff` 从主链生成干系人签收一页纸：结论摘要、每节点判断与证据等级分布、未验证假设、边界声明、空白签收栏。超证据表述仍由 `check` 拦截；本页与主链不一致时以主链为准。三者均有 MCP 对应工具（`askovo_boundary` / `askovo_cost` / `askovo_deliver kind=signoff`）。

## review（决策复盘）

```bash
askovo review ./study          # 人类可读摘要
askovo review ./study --json   # 机器可读检查项
```

写出 `05-audit/decision-review.json` 与 `.md`，按六个维度给出 `pass` / `warn` / `fail` / `info` 检查项：

- `audit`：审计失败项；
- `evidence`：逐条判断的 verdict 与阻断原因；
- `decision`：决策问题、负责人、截止时间、备选方案、最低证据清单、decided 主链、商业门；
- `falsifiability`：假设的证伪条件、`next_test`、缺口与其它解释；
- `bias`：最低记录数、单一来源、重复率、语料角色、时间窗口；
- `deliverables`：`06-report/*.md` 是否过期、是否保留边界声明。

退出码 `1` 表示存在 `fail` 项；`warn` 不阻塞但必须解释。复盘不判断业务成败，也不替代人工复核。

## 机器可读

所有命令输出 JSON 或 Markdown；错误写 stderr。适合：

```bash
askovo route "手机相机续航" --json | jq '.recommended_methods[].id'
askovo platforms "..." --json | jq '.recommended[] | {id, decision, bulk}'
```

## 环境变量

| 变量 | 用途 |
|---|---|
| `GITHUB_TOKEN` | 提高 GitHub API 限额；公开数据可不填 |
| `ASKOVO_REDDIT_CLIENT_ID` / `ASKOVO_REDDIT_CLIENT_SECRET` | Reddit 官方 Data API |
| `ASKOVO_REDDIT_USER_AGENT` | Reddit 要求的可识别 User-Agent |
| `ASKOVO_AUTHOR_SALT` | 可选研究级 HMAC 盐；未设置时 normalized 不生成作者关联 hash，不把它当匿名化 |

所有平台采集必须遵守平台条款、速率限制、数据权利与保留规则。没有合规通道时只接受授权导出/历史数据集。

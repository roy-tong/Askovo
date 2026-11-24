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
| `route "<需求>"` | 只路由，不写文件；含行业、岗位编排与研究模式 | 0/2 |
| `mode "<需求>"` | 只判断 Discover / Validate / Optimize 与入口节点、上游假设、问题与停止条件，不写文件 | 0/2 |
| `explore <study>` | 为 0→1 研究生成五层机会空间脚手架（JSON + Markdown），不产生结论 | 0/2 |
| `external-research <study> --command <id> --authorize` | 运行**已登记**的宿主适配器（白名单环境、有界输出、独立 run id），把输出保存为候选来源（不定级、不升级为证据） | 0/2 |
| `roles list/show/recommend/scaffold/template` | 80 岗位族、10 生命周期、10 行业的职责/KPI/SOP/交接/模板与项目执行包 | 0/2 |
| `platforms "<需求>"` | 平台雷达：数据在哪、能否合规拿到、能证明什么 | 0/2 |
| `collect <study>` | 通过 design gate 后运行采集适配器/本地导出/CDP，写 raw、manifest 与 normalized | 0/1/2/3/4 |
| `research plan/authorize/run/status` | 宿主给定动作清单的逐条授权与受控执行 | 0/1/2/3/4 |
| `loop plan/authorize/run/status/report/assess` | 缺口驱动的多轮受控采集、每轮复审、候选证据与复盘 | 0/1/2/3/4 |
| `decide start/status/result/brief/cancel` | 一问题研究执行器：登记任务、规划、受门禁执行、C-01 状态投影与 partial Brief | 0/2 |
| `issues import/extract/list/edit/accept/reject/status/report` | Issue → 用户任务/需求结构化：本地导出快照、机器候选、人工接受进 canonical 链 | 0/2/4 |
| `brief <study>` | Decision Brief：PRD §2.3 九节只读投影、PRD 开发验收清单、`stale` 门禁 | 0/1/2 |
| `delta sync/show/status/approve` | 增量研究 Delta：append-only 快照、新增/变更/删除、受影响节点与反证影响、`needs_re_review` | 0/1/2/4 |
| `queue init/add/run/status/retry` | SQLite 队列、worker、重试、限速、断点续跑 | 0/1/2 |
| `semantic list/review/export/validate` | 受约束语义候选的查看、具名复核与 E2 收集陈述导出 | 0/1/2 |
| `analyze <study>` | 归一化、去重、分布、候选主题、问题匹配；`--semantic` 增加受约束候选、critic 与人工复核通道 | 0/1/2 |
| `chain <study>` | 生成/渲染“场景→用户→痛点→需求→特性→产品→商业”推理链 | 0/2 |
| `economics <study>` | business 节点单位经济投影（算术投影，null=未知） | 0/2 |
| `psm <study> --input <csv>` | van Westendorp 价格敏感度四问分析 | 0/1/2 |
| `instruments <study>` | 生成访谈/观察/任务/感官/价格/Beta/安全工具包 | 0/2 |
| `import <study> <file>` | 导入 JSONL/CSV/文本为证据 | 0/2 |
| `codebook <study>` | 生成六类结论的编码本 | 0/2 |
| `deliver <study>` | 业务方案 plan / 决策包 / MRD / PRD / BRD / 运营 / 岗位 role / 生命周期 lifecycle / Web 阅读面 web 等同一主链投影 | 0/1/2 |
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

输出：`product_reasoning`（七节点、当前阶段焦点、主链产物），以及 domain、stage、intent、risk_flags、safety_gate、recommended_methods、alternatives、decisions、deliverables、platform_preview、next_commands；另含 `industry_context` 与 `role_recommendation`。行业识别受已路由基础域约束，冲突与候选会显式保留。主链先展示，岗位、方法与平台是支撑层。

## mode

```bash
askovo mode "端侧 AI 摄影创业机会"
askovo mode "验证端侧摄影 App 是否值得做，用户是否愿意付费" --json
askovo mode "为什么我们的注册转化下降" --mode optimize
```

输出：`mode`、`mode_label`、`mode_source`、`entry_node`、`entry_label`、`node_order`、`upstream_nodes`、`why_entry`、`questions`、`first_actions`、`stop_conditions`、`boundary`。默认 Markdown，`--json` 输出契约。

优先级：显式 `--mode` > 任务文本信号 > 显式 `--stage` > 关键词推断阶段 > 默认 Discover。`mode_score` 是关键词启发式分数（`calibrated=false`），不是概率。入口只决定先回答什么，不豁免任何节点的证据要求；上游未验证前只能作为假设。`route --json` 也带同一个 `research_mode` 对象。

## explore

```bash
askovo explore ./askovo-mobile-discovery
askovo explore ./askovo-mobile-discovery --force
```

Discover 模式的 `askovo do` 会自动生成该地图；`explore` 用于补建或重建。生成 `04-findings/opportunity-map.json` 与 `.md`：市场与替代、用户与任务、机会假设、方案空间、验证路径五层，每层带问题与条目 schema。条目初始为空；没有来源、状态和反证记录的条目不能进入产品方案。

## external-research

```bash
# 1) 在 01-sources/external-research.json 里登记适配器（六个必填字段 + 适配器 sha256）
# 2) 人工授权后按 id 运行
askovo external-research ./study --command my-adapter --authorize --json
askovo external-research ./study --command my-adapter --authorize \
  --max-stdout-bytes 65536            # 只能调低上限
```

- **A-06 边界**：子进程环境只含白名单变量（从白名单**构建**，不继承）；只跑注册表里 `sha256` 匹配的适配器；stdout/stderr 有硬上限，超界 `RATE_LIMITED` 失败而不是截断；每次运行有独立 `run_id`（同秒两次不覆盖）；`--output` 解析后必须落在 study 内。
- 命令通过 `ASKOVO_QUESTION` / `ASKOVO_STUDY` / `ASKOVO_MODE` / `ASKOVO_RUN_ID` 接收上下文，stdout 必须输出一个 JSON 对象，至少含 `sources: [{url, title, excerpt, claim}]`。
- 输出保存到 `04-findings/external-research/<run_id>.json`，记录为 `candidate`、`evidence_level: null`、`url_verification: not_attempted`、`review_required: true`；**不抓取也不验证链接**（A33）。
- `--authorize` 是必需的，因为命令以当前用户权限运行。**破坏性变更**：任意 `--command` 不再默认可用，迁移方式见 [外部研究桥](external-bridge.md#6-破坏性变更与迁移v11--a-06)；一次性本机工作流用 `--trusted-local`（仍必须 `--authorize`，且会记入运行记录）。

## roles

```bash
askovo roles list --lifecycle L02 --query "访谈" --json
askovo roles show R52 --industry ai_native
askovo roles recommend "AI 摄影应用概念与失败恢复" --stage concept --task design
askovo roles recommend "仓储机器人现场工序与 ROI" --task decide --scale lean
askovo roles scaffold ./study --task define --scale standard
askovo roles scaffold ./study --role R29 --role R52 --role R72
askovo roles scaffold ./study --chain PR02 --role R29 --role R52
askovo roles template R52 --deliverable R52-D01 --output agent-interaction.md
askovo deliver ./study --kind role --role R52 --chain PR02
askovo deliver ./study --kind lifecycle
```

- `list/show` 查询 80 个岗位族的职责、KPI 公式与护栏、SOP 输入/动作/输出/质量门、交付模板、交接和专业边界；`--industry` 加载十一类行业上下文，并接受行业别名（如 `ebike`、`电动自行车`）。
- `recommend` 先识别 `decide/discover/define/design/validate/launch/operate/review` 任务，再按“牵头 → 任务触发 → 能力覆盖 → 当前阶段行业角色”选最小充分团队；`--task`/`--scale` 可覆盖。输出选中岗位、暂缓岗位与原因、真实交接边、输出合同。`--base-domain` 防止行业关键词覆盖 SURE 产品域；AI 可作为硬件行业的能力覆盖层。
- 输出合同确定主交付物、最多两个支撑产出、格式、篇幅、读者、语气、章节结构、证据呈现、图表、行业优先产出和表达禁忌。软件决策通常 1–3 岗，高风险硬件/医疗验证最多 6 岗。
- `scaffold` 要求已有主链：空链拒绝、单链自动绑定、多链要求 `--chain`。原子写 `01-sources/role-workbench/`，保存任务/规模/输出合同、目录/行业哈希、角色/SOP/KPI/模板引用、真实 PRxx.node/edge 和项目状态；默认只生成本轮主交付+支撑模板，`--all-templates` 才扩展。不复制岗位定义，不修改主链/判断/证据。已有 workbench 默认拒绝覆盖，`--force` 同样拒绝；`--overwrite` 只输出差异预览不写盘，`--overwrite --confirm` 先备份为 `role-workbench.bak-YYYYmmddTHHMMSS` 再原子替换，内容一致时返回 `unchanged`。KPI baseline/target 均为 null。
- `template` 生成未填写、未复核的工作模板；七节点语义为 `editable=false`，不自动产生市场、需求、产品或商业结论。
- `deliver --kind role` 从 workplan 绑定或显式链只读生成扁平 `06-report/role-Rxx-Dyy.md`；旧研究多链必须指定 `--chain`。
- `deliver --kind lifecycle` 生成 `06-report/lifecycle-board.md`，展示十板块交接与实际工作状态。
- 详细设计见[产品创新岗位操作系统](role-operating-system.md)。

## plan

```bash
askovo plan ./new-study --goal "夜间误报与替代方案" --region overseas \
  --sample-size 100000 --platform-types forum,social
askovo plan ./existing-study --goal "补设计" --region overseas \
  --sample-size 100000 --platform-types forum,social --force
```

新目录：写入 study.json、配额、可行性、采集任务与 `01-sources/source-plan.csv`。`--sample-size` 范围为 1–100,000，表示去重、全文、时间和相关性筛选后的严格主样本上限，不是原始抓取行数；海外 forum/social 会纳入 Discord 和 Instagram 的声明式 CDP 路由，并为每个平台分配五种证据用途的整数配额。

已有工位加 `--force`：**只写提案，不改真值文件**——输出到 `01-sources/plan-proposal/`：
`plan-proposal.json`、`source-plan.proposed.csv`、`tasks.proposed.md`。`study.json`、
`source-plan.csv` 与路由模板保持不变；人工合并接受的 rows 后，重新跑
`askovo check --stage design`。非空目录没有 `study.json` 时 `--force` 也会拒绝。

## chain

```bash
askovo chain ./study
```

如果缺少 `04-findings/product-reasoning.json` 则创建假设画布，随后渲染 `06-report/product-reasoning.md`。它不会从一句 query 或高频词自动编造七节点。每个节点需要 statement、incoming rationale、status、evidence_ids、assumptions；商业节点还需要市场边界、细分、价格、成本、单位经济、指标和业务门。`decided` 是产品/商业选择，不是发布、商业成功或因果证明。旧六节点文件仍可读取。完整规则见[产品推理主链](product-reasoning.md)。

## chain-node

```bash
askovo chain-node ./study show                              # 只读：整条链的节点、状态与已绑定证据
askovo chain-node ./study show --node business --chain 2    # --chain 接受链 id 或 1-based 序号，省略取第一条
askovo chain-node ./study set --node business --status validated \
  --statement "..." --note "补到 3 份付费凭证"
askovo chain-node ./study bind-evidence --node business --evidence E-0007 --evidence E-0012
askovo chain-node ./study unbind-evidence --node business --evidence E-0007
```

`set` / `bind-evidence` / `unbind-evidence` 直接写入 `04-findings/product-reasoning.json`（原子写），并为每次真实改动追加一条 `change_log`：`base_version`（如 `chain-v3`）、`new_version`、`decision`（取 `--note`）、`previous`（改动前值）、`affected_refs`（`CHAIN.node`）与 `projection_sync: pending`，因此任何一次判断变化都能回溯到改前状态。`show` 只读，不写盘。

绑定证据只校验 ID 存在；证据是否属于该节点判断类（例如商业节点只能用商业/反证证据）仍由 `askovo check --stage full` 判定。该命令只写真值、不跑审计，输出 `audit_status: not_run`——写成功不等于通过检查；内容无变化返回 `unchanged` 且不写盘。未知链、未知节点、非法状态或未知证据 ID 走 stderr + 退出码 2。改完后重新运行 `askovo deliver`，让报告与新的 `chain-vN` 对齐。

## platforms

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
askovo platforms "SaaS 用户在 GitHub 和论坛上的抱怨" --domain software --claim-type need
askovo platforms "Kickstarter 众筹评论" --field-notes            # 平台实战笔记（限制/解法/验证等级）
askovo platforms "Discord 社区抱怨" --platform discord --field-notes  # 单平台完整表
askovo platforms "Discord 和 Kickstarter 的多平台采集" --strategies   # 多平台轮转策略（不变量/机制/验证）
askovo platforms "Discord 社区抱怨" --policies                        # CDP 运行时预算（goto/熔断/会话上限）
askovo platforms "Reddit 和 Kickstarter 的用户抱怨" --collection-policies  # 采集侧策略卡（访问方式/预算/信号/来源）
```

输出推荐平台、适配分、访问方式、批量能力、限制、偏差，以及不可直接采集的平台与原因。`--bulk` 优先支持批量的来源。

`--field-notes` 渲染 `skills/askovo/assets/platform-field-notes.json` 里的实战限制与解法（含跨平台实践）；`--platform <id>` 收窄到单个目录平台或 source type（如 `vertical_forum`），未知 id 退出码 2，已知但不在当前推荐集的平台（如 `app_store`）仍返回其笔记/策略而不是报未知；`--json` 的每个推荐条目带 `field_notes`，顶层另有 `field_notes`。笔记**不是许可**：能否采集仍由平台目录、study scope 与 Design gate 决定。

`--policies` 渲染注册表 `runtime_policies` 编译出的 CDP 运行时预算：每站点最小间隔、会话上限、超时熔断、单 cell goto 数、预算留头系数与模式互斥。`--json` 的每个 CDP 推荐条目带 `runtime_policy`，`--policies` 时顶层另有 `runtime_policies`。预算是**执行约束**（`connectors/cdp_strategy.py` 的 `SessionGuard`），不是访问许可。

`--collection-policies` 渲染注册表 `collection_policies` 编译出的采集策略卡：每平台允许的访问方式、站点间隔、会话上限、量级留头、分级的检测信号（`block`/`throttle`/`watch`）与触发动作、停止规则、社区经验条数（`observed[]` 的 high/medium/low 分布），以及每条判断的来源（`official`/`craft`/`lead` 分级 + `as_of` 日期）。`--json` 的每个推荐条目带 `collection_policy`，`--collection-policies` 时顶层另有 `collection_policies`。策略**不是许可**：访问方式必须是平台目录的子集，预算不得比运行时策略更松，经验值只能比预算更慢（更快即校验失败），目录里 blocked 的平台只出现在 `excluded` 里且没有策略卡；`askovo doctor` 校验这些不变量。口径说明见 [`references/collection-strategy.md`](../skills/askovo/references/collection-strategy.md)。

## collect

```bash
askovo collect ./study --platform github --query "camera motion alert" --limit 100
askovo collect ./study --platform reddit --query "night alert" --limit 100
askovo collect ./study --platform reddit --query "night alert" --limit 100 --fixture export.jsonl
askovo collect ./study --platform github --query "..." --dry-run
askovo collect ./study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 --url "https://www.amazon.com/product-reviews/B0..." --ack-terms
askovo collect ./study --platform instagram --query "night alert workaround" \
  --cdp-url http://127.0.0.1:9222 --url "https://www.instagram.com/p/visible/" \
  --attach-existing --ack-terms --limit 50
```

- 非 dry-run 采集先执行 design gate；失败返回 `1` 和 `design_gate_failed`。平台还必须在 `scope.allowed_sources` 中，live/CDP 必须启用 adapter。
- GitHub：官方 Search API；`GITHUB_TOKEN` 可选。
- Reddit：官方 Data API；需要 `ASKOVO_REDDIT_CLIENT_ID`、`ASKOVO_REDDIT_CLIENT_SECRET`、可选 `ASKOVO_REDDIT_USER_AGENT`；registry 复核过期不再阻断，返回结果带 `review_status: "expired"` 与降频提醒。
- YouTube：官方 Data API 优先；内置 innertube 是 `public_endpoint_limited`，不是官方配额，按 limited 路线审查。
- Hacker News：Algolia 公共 API；保留平台 ID `hackernews`、限速与技术圈层偏差说明。
- 空提取不等于空语料：`empty_unconfirmed` 不写 run；`cdp_timeout`、`blank_render`、`page_not_found`、`scope_violation`、`session_drop` 等失败状态均返回非零，不能只按进程退出码 0 判断成功。
- 官方 API 可用不等于必须走 API：x、kickstarter、github、hackernews、youtube、weibo 等平台可用 `--cdp-url` 走授权可见页路线（需 Design gate、启用 adapter、`--ack-terms` 与批准 URL）；API 路线保留在 plan 的 `routes` 中，采购要求只影响该路线，不关闭整个平台。
- `--fixture`：离线 JSONL/CSV，用于授权导出、历史数据集和测试；每行必须是 JSON object。
- 其他平台既没有内置适配器、也没有显式 `--cdp-url` 路由时返回 `3`，并给出导入/授权导出路径。
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
- `--attach-existing` 精确复用用户浏览器里已经打开的同 URL 页面，不新开标签页；找不到精确匹配即停止。显式 CDP 路由不会先被付费 API 采购门拦截，但掉登录返回 `session_drop`，必须由用户手工重登；
- Instagram 评论和 Discord 消息使用专用 DOM 提取器，保留全文、来源 URL、频道／账号、内容类型和时间；Discord/Instagram 滚动使用真实 wheel 事件；
- 仅平台目录 `cdp: true` 集合开放（当前 github/reddit/youtube/hackernews/amazon/instagram/bilibili/weibo/kickstarter/discord/x/tiktok）；官方 API 仍是优先路线，但有 API 不排除 CDP，其余 blocked 平台不开放；
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
askovo loop assess ./study --gap "claim:D02:commercial" --verdict resolved --by "researcher" --evidence R01
askovo loop map ./study --file mappings.json --by "researcher"
askovo loop advise ./study
```

- 两者都先过 Design gate，再走 `collect_platform`，平台策略、来源适配器与 `scope.allowed_sources` 校验完全一致；
- `research` 适合宿主 Agent 已经确定动作清单的场景：动作清单哈希变化后必须重新授权；
- `loop` 从审计缺口生成查询，授权对象是「信封」（允许平台、单条上限、轮次与记录预算），信封变化后授权失效；
- `loop` 每轮重新审计，缺口按 `open → collected → analyzed → resolved/unresolvable` 推进，停止原因见[研究闭环](research-loop.md)；
- `loop` 只产出候选证据（`04-findings/loop-candidates.json`）和确定性分析（`04-findings/loop-analysis/`），不分配证据等级、不改判断状态、不标 `validated`；
- `loop assess` 是关闭缺口的唯一路径：`resolved` 至少需要一条证据引用，`unresolvable` 必须写明原因；
- `loop advise` 只根据已记录映射给出只读建议，不关闭缺口、不评级；
- `loop map` 只校验映射出处（候选记录、`study.hypotheses` 中声明的假设、原文片段与立场），不做语义评级；
- MCP 可 `plan` / `status` / `report` / `run`，但不能授权，也不能 `assess` / `map`。

## decide（一问题研究执行器）

```bash
# 登记 + 规划；默认 dry-run，只写计划不读记录
askovo decide start --input task.json --study ./study
askovo decide "下一版先修哪些问题" --repo owner/repo --approved-by owner --dry-run

# 人工授权信封（唯一能解锁采集的步骤）
askovo loop authorize ./study --by "researcher"

# 恢复并推进（幂等：不重复导入、不重采已完成数据）
askovo decide start --task A-TASK-1A2B3C4D --run --workspace ./decide-workspace

# 状态 / 结果 / 取消
askovo decide status A-TASK-1A2B3C4D --workspace ./decide-workspace
askovo decide brief A-TASK-1A2B3C4D --workspace ./decide-workspace --format md
askovo decide result A-TASK-1A2B3C4D --workspace ./decide-workspace
askovo decide cancel A-TASK-1A2B3C4D --by owner --workspace ./decide-workspace

# 专家入口：A-02 显式拒绝（exit 2, UNSUPPORTED_SCOPE），A-04 交付
askovo decide review A-TASK-1A2B3C4D --by product-owner
askovo decide delta A-TASK-1A2B3C4D --since latest-accepted
```

- 输入是 `askovo.decision-task/1`（PRD §2.2）；`--question`/`--repo`/`--approved-by`/`--allowed-source`/`--fixture` 是同一文档的命令行形态，`--mode discover|validate` 映射到 `prioritize_features` / `validate_hypothesis`。
- **默认 dry-run**：`start` 只做规范化、绑定 study、写 loop plan 与 digest；`--run` 才尝试推进，而且只在人工 `loop authorize` 之后。decide 自己绝不 authorize、绝不 `loop assess`。
- 产品状态是 loop 状态的投影：`created → scoped → collecting → analyzed → review_required → brief_ready → delivered`，异常 `needs_input|blocked|interrupted|cancelled`；`delivered` 不等于 `decision_approved`。
- 每次 `status` 都返回 C-01 六字段（`next_actor`、`next_required_action`、`blocked_reason_code`、`last_updated_at`、`has_pending_external_effect`、`artifact_refs`）外加 `state`、`budget`、`gaps`。
- 拒绝走稳定的 `reason_code`（`INPUT_REQUIRED` / `AUTH_REQUIRED` / `UNSUPPORTED_SCOPE` / `POLICY_DENIED` / `ARTIFACT_PARTIAL`），stdout 是拒绝文档，退出码 2，不生成貌似成功的任务。
- 记录上限取 `authorization.max_records` 并同时写入 loop envelope；`cancel` 之后任何 `--run` 都返回 `POLICY_DENIED`，不再读取。
- MCP 对应 `askovo_decide_start` / `askovo_decide_status` / `askovo_decide_result`，复用同一编排函数；细节见[一问题研究执行器](decide.md)。

## delta（增量研究 Delta）

```bash
askovo delta sync ./study --file issues-v2.jsonl --authorized-by "research-lead"
askovo delta show ./study --format md
askovo delta status ./study
askovo delta approve ./study --by "product-owner" --approval-ref "SIGNOFF-001" --option option-A
askovo decide delta A-TASK-1A2B3C4D --workspace ./decide-workspace --since latest-accepted
```

- 按**来源 ID + 更新时间**比对两次授权导出：`added` / `changed` / `deleted`。不做内容相似度猜测。
- 每次真实变化追加一个不可变版本目录 `04-findings/deltas/vNNN-<hash>/`；旧版本逐字节保留，被删除/被编辑的记录仍可读到原文、hash 与获取权说明。
- 重复同步是 no-op：不生成新版本、`index.jsonl` 不动、`message` 写"无变化"。
- 过滤条件（`--since`/`--label`）变化时**不**推断删除（`deletion_basis: not_asserted`）。
- 同一 `source_id` 的编辑只算 `changed`；`author_id` 优先用稳定 `user.id`，登录名改名只记 `identity_drift`，不新增观测用户。
- 新反证只置 `needs_re_review`：已批准的 `DecisionSnapshot` 保持只读（`decision_record_mutated: false`），`accepted`/`current`/`differences` 明确列出差异。
- 来源不可达时 `show`/`status` 退出码 1，`stale: true` + `reason_code: STALE_SOURCE` + 上次成功时间；仍可浏览上次可用结果。
- 细节见 [增量研究 Delta](research-delta.md)。

## brief（Decision Brief 与 PRD 验收投影）

```bash
askovo brief ./study                 # 06-report/decision-brief.json + .md
askovo brief ./study --format md
askovo brief ./study --task A-TASK-1A2B3C4D --output /tmp/brief
```

- 只读投影 canonical 主链 + `demand-judgments.json` + `evidence.jsonl` + `decision_review`；写回只发生在 `06-report/`，**不新建可编辑的决策文档**。
- 九节固定：问题/边界/时间窗/负责人、结论（`recommendation`，不是自动批准）、2–5 个同维度选项、支撑证据与反证、受限结论、不做的选择及原因、下一最低成本验证动作、PRD 开发验收清单、四态独立显示。
- 验收清单字段与 PRD 原字段一致（`acceptance_conditions` / `acceptance_criteria`），每条可追溯到 `product-reasoning.json#chains/<id>/nodes/<node>`。
- 引用断裂或输入过期 → `artifact_status: stale`、`reason_code: STALE_SOURCE`、`delivery_state: blocked`、`diagnostic_only: true`，退出码 1，只写诊断草稿。
- 数字必须带单位/窗口/来源，否则不输出数值并列入 `numbers_without_provenance`；访谈人数/转化率/市场规模无来源时保持 `null`；`heuristic_score` 不是概率（`calibrated: false`）。
- `askovo decide brief` / `askovo decide result` 复用同一份 Brief；`decide delta` 仍留给 A-05。
- 细节见 [Decision Brief](decision-brief.md)。

## issues（Issue → 用户任务/需求结构化）

```bash
# 1) 快照 + 规范化（人工授权，不联网）
askovo issues import ./study --file issues.jsonl --authorized-by "research-lead"   --since 2026-08-01 --label bug

# 2) 机器候选（规则法，13 个 PRD 字段）
askovo issues extract ./study --question "下一版先修哪些解析问题"

# 3) 复核
askovo issues list ./study --claim-kind feature_request
askovo issues status ./study
askovo issues report ./study

# 4) 人工编辑 / 接受 / 拒绝（均需具名的人）
askovo issues edit ./study --candidate IC-01 --by "product-owner" --set user_role="CLI 使用者"
askovo issues accept ./study --candidate IC-01 --by "product-owner"   --context-key nested-log-parse --judgment-id D03 --evidence-level E2
askovo issues reject ./study --candidate IC-02 --by "product-owner" --reason "单一自述"
```

- 只读本地授权导出（`gh issue list --json` 形态的 JSONL/JSON）；`LIVE_CONNECTOR_ENABLED` 永久为 False，未来接真 connector 的接口位置留好但不开。
- 机器候选带 PRD 逐字要求的 13 个字段；`source_quote_span` 是 `source_text` 的精确切片，抽不到就是 `null`。
- 语义规则写在实现里：同一登录 10 条 = 1 名观测用户、评论不算用户、请求方案封顶 E1、无可复现文本 = `unverified`、来源被删留快照/hash、一条反证即 `challenged`、私有内容与白名单外字段永不落盘。
- `accept` 写一条 evidence + 一条 demand judgment + 一条 product-reasoning 链 + 追加式 `issue-acceptance.jsonl` 轨迹；幂等，且 `accepted` 不等于 `validated`。
- 退出码：0 已记录、2 语义门禁拒绝（`POLICY_DENIED`/`INPUT_REQUIRED`/`UNSUPPORTED_SCOPE`）、4 缺具名授权/复核人（`AUTH_REQUIRED`）。
- 细节见 [Issue 结构化](issues.md)。

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

规范性证据用 `text_excerpt` 存原文；没有 `text` 字段时 `analyze` 回退到 `text_excerpt`，没有 `evidence_form`/`claim_type` 时回退到 `corpus_role` 与证据等级（E0=context、E1/E2=need、E3=acceptance、E4+/E5=commercial、E4-=counter）。`deliver --kind analysis` 的漏斗优先读 `01-sources/collection-summary.json`（`raw_records` / `screened_records`），用于多波次或多工位合并的语料；缺省时回退到本工位 `02-data/raw`。

### 语义候选（`--semantic`）

```bash
askovo analyze ./study --question "夜间误报" --semantic
askovo analyze ./study --semantic --semantic-provider offline
askovo semantic list ./study
askovo semantic review ./study --candidate theme-night-alert-fatigue \
  --decision accept --reviewer alice --note "两条引文已核对"
askovo semantic export ./study --by alice --export-now
```

语义层默认关闭：没有 `ASKOVO_LLM_BASE` / `ASKOVO_LLM_MODEL`（或显式 `--semantic-provider offline`）时自动退回确定性分析。远程模型必须显式 `--allow-external`，否则退出码 2 且不发送语料；loopback 模型不需要该开关。

候选固定为 `unverified`，每条必须挂存在的 `record_id` 与原文子串 `quote`，`unknowns` 必填；模型写 `evidence_level`、`demand_claim`、`validated` 会被拒绝。写候选前先过 critic（反例、覆盖缺口、替代解释、补证清单），没有 critic 的候选拒绝复核。只有具名 `accept` 的候选能导出为 `collected_corpus_statement` 的 E2 观察；进入 `evidence.jsonl` 仍需人工语义审核。产物、环境变量与边界见[语义候选层](semantic-candidates.md)。

`--semantic` 的退出码：`0` 完成或按设计回退；`1` 语义层 partial/failed；`2` 远程未授权或参数错误。确定性 `analysis.json` / `analysis.md` 在语义层之前写出，失败不会隐藏已有分析。

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

- `plan`：业务方案（Business Plan），写 `06-report/plan.md`——业务用户默认视图：七节点渲染为"目标场景/目标用户/痛点/需求/特性/产品形态/商业与 GTM"九节业务章节，通篇业务语言；每个判断带**数据基础**（来源 · 语料量 · 时间窗）与**来自语料的声音**（用户原话或典型情况），尚无数据的判断如实标注"暂无采集数据"；证据编码与原始状态只进文末方法档案；
- `analysis`：语料分析，写 `06-report/analysis.md`——采集漏斗（原始→筛选→编码→进入判断）、来源与年份分布、语料用途、七节点覆盖、集中度与重复、反证清单，以及"这份数据能回答/不能回答什么"；新增共现候选主题、机制/转折句候选和重复/独立记录归并，全部只做确定性统计，不推人群比例、市场规模或已验证因果；
- `decision`：决策包（Decision Package），写 `06-report/decision-package.md`——机会地图/证据图/选项与权衡/决策备忘/验证清单五个决策侧视图，全部由同一条主链与需求判断投影；
- `memo`：产品/商业决策 memo；
- `report`：产品与商业推理总报告，写 `06-report/report.md`；
- `mrd`：市场研究与分析投影，写 `06-report/mrd.md`；
- `prd`：需求研究与分析后的特性、产品范围、非目标和验收，写 `06-report/prd.md`；
- `brd`：商业分析投影，包含市场、收入、成本、单位经济、指标和业务门，写 `06-report/brd.md`；
- `ops`：场景×用户分群、痛点/异议和运营回流，写 `06-report/user-ops.md`；
- `tracker`：从特性/产品验收和商业成功指标生成带 chain/node ID 的跟踪行，写 `06-report/postlaunch-tracker.csv`；
- `web`：Web 阅读面，写 `06-report/web/index.html`——同一条主链的自包含阅读页：事实/自述/推导/我的判断四类标签、数字与判断形成时间的分层展示、证据墙（原文/来源/引用环节/本地截图/原帖链接）、来源与节点分布图、可复用打法；E0–E5 与资格标记只进页尾方法档案，不新增结论。详见 [Web 阅读面](web-surface.md)。

角色交付 `role`/`lifecycle` 见上文「roles」一节，签收页 `signoff` 见下文 F3 一节；与本节合计 14 种（默认 `memo`）。

多链研究：`--kind plan` 先输出跨链比较表与逐链结论，七环节正文只展开优先级最高的一条；`--kind report` 的“产品决策”一节按链生成状态/依据强度/建议/下一步/失败线，没有 `decided` 链时明确标注为待验证建议，不再留空模板。`--kind analysis` 的漏斗支持 `01-sources/collection-summary.json` 的累计口径。

`--kind plan` 第 0 节“结论与推进建议”有门禁：只有商业环节 `validated`、绑定合格的 E4+/E5 商业证据（成交、付费或可核对的商业行为）、链带 `context_key`，且最近一次 `askovo check --stage full` 通过时才给正式结论；否则输出当前判断、缺口和下一步补证动作，不把假设写成结论。交付文档中尚未提供的字段统一用“缺口 + 影响 + 补法”说明（BRD/MRD/PRD 为“材料缺口”小节），不留占位符或空白模板。

`askovo report` 是用研支撑报告，写 `06-report/research-status.md`；它不与产品/商业 `deliver --kind report` 共用文件。所有交付都从同一七节点主链渲染，不另建语义真值。业务方案是业务用户的默认视图；决策包是决策侧汇总视图；MRD、PRD、BRD 分别对应市场研究/分析、需求研究/分析、商业分析三条工作流，不是三个平行事实库。

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

`economics` 从 business 节点的 `pricing` 与 `unit_economics_inputs` 做确定性算术投影，写 `06-report/unit-economics.md`：只对**数值、单位匹配、带 source_ref** 的输入计算；“成本类”合计仅按名称匹配（cost/成本/费用）作为指示性结果；null 表示未知不是零；缺来源的数值列出缺口不进入计算。`pricing` 可选声明 `volume` 与 `revenue`：两者都在时校验“单价×数量=收入”，只给 `volume` 时反算收入，只给 `revenue` 时反算数量，反算结果标注为计算值而非声明值。数值校验用 Decimal，容差取绝对值 0.01 与相对值 0.5% 中的较大者；声明的毛利、毛利率、ROI 与计算值不一致时**只报告，不替用户改数**，报告和 `askovo check` 的 `unit_economics` warn 会列出差异。它是算术检查，不是商业证明——E4/E5 商业证据、财务评审与人工决策独立进行。

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

## decision record / replay（版本化反证复审）

```bash
askovo decision record ./study --chain PR01 --by "产品负责人"
askovo decision record ./study --chain PR01 --by "产品负责人" --contradiction R05
askovo decision replay ./study --chain PR01 --json
```

反证 ID 必须已登记、context 相同、带 provenance 和 contradicts 映射。第二条记录触发 `deterministic_safe_hold`，重开产品与商业验证并保留前后快照；不自动编造替代建议或升级因果状态。合成端到端证明和任务模板见 [决策重放页](../website/examples/decision-replay.html)。

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
| `ASKOVO_DECIDE_HOME` | `askovo decide` 的 workspace 默认目录（未设置时用 `./askovo-decide`） |

所有平台采集必须遵守平台条款、速率限制、数据权利与保留规则。没有合规通道时只接受授权导出/历史数据集。

## 受控编辑七节点字段

`chain-node set` 除 `--statement/--rationale/--status` 外，可用 `--field` 与 `--value-json` 修改常用任务字段，不需要手工编辑内部 JSON：

```bash
askovo chain-node STUDY set --node feature \
  --field acceptance_conditions \
  --value-json '["可回退原决定", "保留反证来源"]' \
  --note "补齐验收条件"
```

字符串字段包括 `current_substitute`、`friction_cost`、`consequence`、`desired_outcome`、`measure`、`capability`、`form`、`scope`；数组字段包括 `assumptions`、`constraints`、`alternatives_considered`、`acceptance_conditions`、`non_goals`、`acceptance_criteria`。字段、JSON 语法和类型都会校验；相同值不写文件。所有变更进入链的 append-only `change_log`，仍需 `askovo check STUDY --stage full` 重新审计，编辑不等于门禁通过。


## 受控研究写入、导入纠错与撤销

普通研究操作不需要手改内部 JSON：

```bash
# 链级字段与商业节点字段
askovo chain STUDY set --field context_key --value-json '"after_sales_saas"'
askovo chain-node STUDY set --node business \
  --field pricing_hypothesis --value-json '{"seat_price":1800,"premium":0.2}'

# 研究合同、需求判断和角色工作台
askovo study STUDY set --field decision.owner --value-json '"周航"'
askovo demand-judgment STUDY create --id DJ01 --title "售后自动分派验证" \
  --user-role "售后主管" --scene "人工录单积压" --task "决定是否试点自动分派" \
  --current-substitute "人工分派" --friction "录单慢且易错" --consequence "客户等待与返工" \
  --solution "低摩擦试点" --acceptance-conditions "录单率达到70%且续费不下降" \
  --problem-evidence R01 --context-key after_sales_saas --next-test "3家客户4周试点"
askovo roles workplan-set STUDY --role R09 --owner 王珂 --timebox 下周 \
  --start 2026-11-23 --end 2026-11-29 --step R09-S01 --status in_progress

# 撤销与恢复错误证据；不删除原文，也不自动通过审计
askovo evidence STUDY retract R01 --by 赵敏 --reason "纠正误导入记录"
askovo evidence STUDY restore R01 --by 赵敏
```

`study set` 支持决策、范围、假设与停止/重启规则；`chain set` 支持链级关联、缺口和反证；商业节点支持市场、价格、成本、收入和业务门等类型化字段。需求判断只接受已登记证据 ID。`evidence set` 纠正证据形式/等级时，E3 必须同时提供有效的 `--concept-test`，不能借纠错升权。撤销后的证据不参与分析、需求判断或审计，恢复保留原文。

CSV 导入识别 `记录编号 / 内容 / 证据等级 / 来源 / 采集时间`。编号和正文均参与跨文件判重；同编号不同正文会在任何证据写入前拒绝整批，不会先写一半。重复项返回 `duplicates` 映射，采集时间不再冒充内容发生时间。

BRD 的「BRD 商业决策」区域会投影每条主链最新 DecisionRecord 的记录号、决策人、决定和下一动作；这是 canonical 的只读投影，不表示执行或业务结果已验收。

## 真实任务案例门

```bash
askovo case list
askovo case show A-HMC-RESEARCH-01
askovo case incidents --out ../ai输出/ovo-真实任务资产库/INCIDENTS.md
askovo case validate
askovo case replay A-GOLF-DISCOVERY-01 --run-root /tmp/ovo-case-runs
askovo case verify --run-root /tmp/ovo-case-verification
```

`case` 调用 `ovo-acceptance` 的共享运行时。默认注册表决定家族工作区根路径；`OVO_ACCEPTANCE_HOME` 覆盖运行时位置，`OVO_CASE_REGISTRY` 覆盖案例注册表，`OVO_CASE_ROOT` 显式覆盖证据根目录。`task_rerun` 与 `evidence_only` 分开，外部写案例只复核证据，不重新发送、付款或签核。

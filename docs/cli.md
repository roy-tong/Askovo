# CLI 参考

`sure` 只有一个入口。所有产品类型、方法、采集与分析能力都从同一行命令路由，不需要为软件/硬件/消费/汽车/手机分别安装。

```bash
sure --version
sure --help
```

## 命令总览

| 命令 | 用途 | 退出码 |
|---|---|---|
| `do "<需求>"` | **单入口**：路由 + 生成研究计划、方法选择、证据计划、工具包 | 0/2/4 |
| `route "<需求>"` | 只路由，不写文件 | 0/2 |
| `platforms "<需求>"` | 平台雷达：数据在哪、能否合规拿到、能证明什么 | 0/2 |
| `collect <study>` | 运行采集适配器/本地导出，写 manifest 与 normalized | 0/2/3 |
| `analyze <study>` | 归一化、去重、分布、候选主题、问题匹配 | 0/2 |
| `instruments <study>` | 生成访谈/观察/任务/感官/价格/Beta/安全工具包 | 0/2 |
| `import <study> <file>` | 导入 JSONL/CSV/文本为证据 | 0/2 |
| `codebook <study>` | 生成六类结论的编码本 | 0/2 |
| `deliver <study>` | memo / report / PRD 输入 / tracker | 0/2 |
| `methods` | 按领域与阶段列方法 | 0/2 |
| `domains` | 列五个研究包 | 0 |
| `catalog` | 列方法目录 | 0 |
| `audit` | 旧版需求研究门禁与逐条判断 | 0/1/2 |
| `plan` | 旧版平台可行性/配额计划 | 0/2/3 |
| `doctor` | 运行时、目录、研究包、平台目录、版本自检 | 0/1 |
| `demo` | 内置样例 | 0/1/2 |

退出码：

| 码 | 含义 |
|---|---|
| 0 | 成功/门禁通过 |
| 1 | 证据或命题门禁未过（合法研究状态） |
| 2 | 用法、数据或环境错误 |
| 3 | 没有可行平台/适配器，必须报告缺口 |
| 4 | 安全/伦理门未通过，禁止进入执行 |

## do

```bash
sure do "家用摄像头夜间告警误报，想验证样机"
sure do "手机相机夜景和续航" --study ./phone-study
sure do "汽车开放道路接管测试" --ack-risk
```

- 自动识别产品领域、阶段、意图与风险。
- 默认创建 `./sure-<domain>-<stage>`；`--study` 指定路径。
- `--dry-run` 只输出路由，不写文件。
- 检测到道路试验、摄入/皮肤接触、儿童、敏感数据等风险时返回 `4`；只有负责人完成审查后加 `--ack-risk` 才生成计划。
- `--domain/--stage/--intent` 可覆盖自动识别。

## route

```bash
sure route "SaaS 订阅留存下降" --json
sure route "座舱语音接管" --domain automotive --stage validation
```

输出：domain、stage、intent、risk_flags、safety_gate、recommended_methods、alternatives、decisions、deliverables、platform_preview、next_commands。

## platforms

```bash
sure platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
sure platforms "SaaS 用户在 GitHub 和论坛上的抱怨" --domain software --claim-type need
```

输出推荐平台、适配分、访问方式、批量能力、限制、偏差，以及不可直接采集的平台与原因。`--bulk` 优先支持批量的来源。

## collect

```bash
sure collect ./study --platform github --query "camera motion alert" --limit 100
sure collect ./study --platform reddit --query "night alert" --limit 100
sure collect ./study --platform reddit --query "night alert" --limit 100 --fixture export.jsonl
sure collect ./study --platform github --query "..." --dry-run
```

- GitHub：官方 Search API；`GITHUB_TOKEN` 可选。
- Reddit：官方 Data API；需要 `SURE_REDDIT_CLIENT_ID`、`SURE_REDDIT_CLIENT_SECRET`、可选 `SURE_REDDIT_USER_AGENT`。
- `--fixture`：离线 JSONL/CSV，用于授权导出、历史数据集和测试。
- 其他平台没有内置适配器时返回 `3`，并给出导入/授权导出路径。
- `blocked` 平台直接返回 `3`，不提供绕过方式。
- 每次采集写 `01-sources/manifests/<run_id>.json`，原始记录写 `02-data/raw/<platform>/`，归一化记录追加 `02-data/normalized.jsonl`。

## analyze

```bash
sure analyze ./study --question "夜间误报"
```

输出 `04-findings/analysis.json` 与 `analysis.md`：

- 记录数、平台/结论类型/证据形式/月份分布
- 平均文本长度与高频候选主题
- 与问题匹配的片段
- 边界声明：描述性统计，不证明总体或因果

## instruments

```bash
sure instruments ./study
```

按所选方法生成：访谈提纲、观察表、任务脚本、概念测试、感官/HUT 协议、价格问卷、Beta 协议、现场/驾驶协议、测试矩阵、RMA 表、货架测试、无障碍检查、专家审阅、授权说明。已存在的文件不覆盖。

## import / codebook / deliver

```bash
sure import ./study interviews.jsonl --source-family interview --claim-type need
sure codebook ./study
sure deliver ./study --kind memo
```

`deliver --kind`：

- `memo` 决策 memo
- `report` 研究报告
- `prd` PRD 输入
- `tracker` 上市/复测 tracker CSV

## 机器可读

所有命令输出 JSON 或 Markdown；错误写 stderr。适合：

```bash
sure route "手机相机续航" --json | jq '.recommended_methods[].id'
sure platforms "..." --json | jq '.recommended[] | {id, decision, bulk}'
```

## 环境变量

| 变量 | 用途 |
|---|---|
| `GITHUB_TOKEN` | 提高 GitHub API 限额；公开数据可不填 |
| `SURE_REDDIT_CLIENT_ID` / `SURE_REDDIT_CLIENT_SECRET` | Reddit 官方 Data API |
| `SURE_REDDIT_USER_AGENT` | Reddit 要求的可识别 User-Agent |

所有平台采集必须遵守平台条款、速率限制、数据权利与保留规则。没有合规通道时只接受授权导出/历史数据集。

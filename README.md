<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/askovo/main/assets/brand/askovo-logo-600.png" alt="askovo" width="300">
</p>

# askovo

**Ask better. Decide with evidence.**
**问得更好，决策有据。**

一个入口，路由到软件、硬件、消费品、汽车、手机五类产品研究。

askovo 是 Agent 原生的研究与交付助手：说一句业务问题，它判断产品类型、生命周期、研究意图与风险，选择方法组合，生成研究计划、访谈/试验工具包、证据台账和可签收交付物。

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-askovo-111111)](skills/askovo/SKILL.md)
[![CI](https://github.com/roy-tong/askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/askovo/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## 30 秒证明它能工作

```bash
git clone https://github.com/roy-tong/askovo.git
cd askovo
pipx install --editable .
askovo do "家用摄像头夜间告警误报，想验证样机" --dry-run
askovo demo
```

也可以直接写需求：`askovo "手机相机夜景和续航" --dry-run`（等价于 `askovo do`）。
`--dry-run` 只路由、不写文件；`demo` 跑内置合成样例。预期关键结果：`status: pass`、`supported: 1`、`overclaims: 0`；这只是结构与证据链演示，不证明真实市场需求。

## 只装一次，不再分领域安装

```bash
askovo do "SaaS 订阅留存下降，想看看用户为什么不续费"
askovo do "新口味饮料的包装和复购"
askovo do "座舱语音和 ADAS 接管体验"
askovo do "手机相机夜景和续航"
```

同一行命令会自动识别：

| 维度 | 可选 |
|---|---|
| 产品类型 | software / hardware / consumer / automotive / mobile |
| 生命周期 | discovery / concept / prototype / validation / pricing / prelaunch / postlaunch / audit |
| 意图 | route / plan / instruments / sources / collect / analyze / audit / deliver |
| 风险 | 道路试验、摄入/皮肤接触、儿童、敏感数据、生产日志、破坏性测试等 |

输出包括：推荐方法、不推荐方法、证据形式、本阶段要回答的问题、安全门、平台预判和下一步命令。

## askovo 与 SURE

**askovo 是对外产品品牌；SURE 是底层研究引擎。**

- **askovo** 负责用户看到的产品形态：一条命令、五类产品路由、平台判断、采集分析、可签收交付物。
- **SURE（Structured User Research with Evidence）** 负责研究逻辑：方法选择、证据分级、claim 边界、反幸存者偏差、安全门。
- 两者不是两套东西：`askovo` 调用 `sure_engine.py`，同一个证据模型同时服务 CLI、Skill 和 MCP。

## 四个核心能力

### 先写产品推理主链

```bash
askovo do "家用摄像头夜间告警误报，想验证样机" --study ./camera-study
askovo chain ./camera-study
```

`do` 会创建 `04-findings/product-reasoning.json`，把 **场景 → 用户 → 痛点 → 需求 → 特性 → 产品** 六个节点、推导理由、假设和证据引用显式写出来；`chain` 渲染可审阅的 Markdown。方法是支撑层，不替代产品推理；没有填完主链和 Design gate，不会启动真实采集。

### 1. 方法路由

```bash
askovo route "汽车座舱语音的接管体验怎么验证" --json
askovo methods --domain automotive --stage validation
```

不是“所有产品都做访谈”：汽车会路由到诊所/模拟器/封闭场地/道路/自然驾驶，消费品会路由到 CLT/HUT/复购，软件会路由到可用性/Beta/A-B/队列。

### 2. 平台雷达

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
```

回答“数据在哪个平台、能不能合规拿到、能证明什么”。内置 23 类平台/来源，包括 GitHub、Reddit、X、YouTube、Instagram、TikTok、Amazon、App Store、Google Play、Hacker News、Stack Overflow、Bilibili、微博、知乎、小红书、京东、淘宝、Kickstarter，以及访谈、问卷、工单、遥测、实验室报告。

平台结论分三档：`supported`、`limited`、`blocked`。Instagram/Amazon 等没有通用批量接口的，会明确要求授权导出/研究 API/历史数据集，不做未授权抓取。

### 3. 采集与分析

```bash
askovo collect ./study --platform github --query "camera motion alert" --limit 100
askovo collect ./study --platform reddit --query "night alert" --limit 100
askovo collect ./study --platform reddit --fixture export.jsonl --query "night alert"   # 离线/授权导出
askovo analyze ./study --question "夜间误报"
```

- GitHub：官方 Search API（可选 `GITHUB_TOKEN`）
- Reddit：官方 Data API（`ASKOVO_REDDIT_CLIENT_ID` / `ASKOVO_REDDIT_CLIENT_SECRET`）
- 其他平台：授权导出、历史数据集或本地 fixture 接入
- 真实采集前必须通过 `askovo check ./study --stage design`，并把平台加入 `scope.allowed_sources`；live/CDP 还需启用 adapter
- 每次采集写 raw envelope + normalized + canonical manifest：run、connector、访问/权利依据、条数、丢弃原因、限制、偏差
- 规模化按查询/时间/子版块分片，多次 run，平台内按 `record_id` 与文本 hash 双键去重；同 ID 不同内容会记录冲突
- `analyze` 做归一化、去重、平台/时间/结论类型分布、高频候选主题与问题匹配片段；**描述性统计，不证明总体或因果**

### CDP：授权可见页面

```bash
# 先启动一个带调试端口的 Chrome，并用你本人已登录的 profile
# /Applications/Google Chrome.app/Contents/MacOS/Google Chrome #   --remote-debugging-port=9222 --user-data-dir=/tmp/askovo-profile

askovo collect ./study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms
```

- 只抓当前页面**可见文本**；不绕过验证码/挑战页，不伪造指纹；
- `--ack-terms` 必须由人确认：平台条款、账号授权、数据用途与保留；
- 当前仅对 amazon、instagram、bilibili、weibo 的授权可见页面开放；X/YouTube 只走官方 API，blocked 平台仍不开放；
- CDP 仅接受回环调试端点、默认端口 HTTP(S) 平台 URL，返回的 WebSocket 也保持在同一回环端口；
- 命中挑战页立即停止，manifest 记录 `challenge`。

### 队列：并发、断点、限速

```bash
askovo queue init ./study
askovo queue add ./study --platform reddit --query "night alert" --limit 100
askovo queue add ./study --platform github --query "camera alert" --limit 100
askovo queue run ./study --workers 4
askovo queue status ./study
askovo queue retry ./study
```

SQLite 租约 + 多 worker；进程崩溃后租约过期自动回收；失败退避重试；按平台限速；每次 job 独立 manifest 与 raw。适用于单机多进程/多 worker；跨机器共享需要外部队列（未内置）。

### 4. 交付

```bash
askovo instruments ./study     # 访谈/观察/任务/感官/价格/Beta/安全协议
askovo codebook ./study        # need/acceptance/usability/performance/commercial/safety
askovo deliver ./study --kind memo
askovo deliver ./study --kind prd
```

输出决策 memo、研究报告、PRD 输入、上市/复测 tracker，并把证据 id 带进附录。

## 安装

**CLI**

```bash
git clone https://github.com/roy-tong/askovo.git
cd askovo
pipx install --editable .
askovo --version
```

或 venv：

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .
.venv/bin/askovo demo
```

> PyPI 发布后可以简化为 `pipx install askovo`；当前版本从源码安装。

**Agent Skill**

```bash
bash scripts/install-skill.sh                 # ~/.agents/skills
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

MCP 暴露 `askovo_route`、`askovo_do`、`askovo_platforms`、`askovo_collect`、`askovo_analyze`、`askovo_deliver` 等工具，与 CLI 共用同一套行为；其中 collect 默认 dry-run。用 `askovo-mcp --tools` 检查工具清单，用 MCP `tools/list` 检查运行中服务。

核心 CLI/Skill/MCP 只使用标准库。可选 Workbook XLSX 需要 `openpyxl`，Amazon HF 流式工具需要 `datasets`；它们不是核心安装依赖。

## 六类结论不能混

| 类型 | 回答 | 不能替代 |
|---|---|---|
| need | 谁在什么场景有什么未满足任务 | 功能请求、个案 |
| acceptance | 用户是否理解/接受方案 | 喜欢≠会用/会买 |
| usability | 能否完成任务、是否易学低错 | SUS/SEQ 不证明需求或付费 |
| performance | 明确条件下是否达标 | 跑分≠体验 |
| commercial | 购买、留存、复购、退换 | 口头意愿≠交易 |
| safety | 使用风险与合规缺口 | 用户试验≠认证 |

## 边界

- 不做未授权抓取：平台无合规批量通道时，只接受授权导出/合规数据集；
- 不把平台可用当样本代表总体；
- 不把记录数当用户数；
- 不把购买意愿当真实购买，不把一次喜欢当复购；
- 不把 Beta/无投诉/零事件当安全或可发布；
- 不代替实验室、法规、功能安全或医疗/食品/汽车认证；
- 高风险研究停在 S0，Agent 只能出方案，不能指导执行。

## 文档

| 文档 | 内容 |
|---|---|
| [快速开始](docs/quickstart.md) | 单入口、路由、采集、分析、交付 |
| [核心概念](docs/concepts.md) | 六类结论、证据形式、边界 |
| [五类产品](docs/modes.md) | 各产品的方法地图与门禁 |
| [CLI 参考](docs/cli.md) | 命令、参数、退出码 |
| [数据契约](docs/data-contract.md) | study/evidence/normalized/analysis |
| [平台与连接器](docs/connectors.md) | 平台档位、访问方式、抓取边界 |
| [SURE 引擎](docs/sure-engine.md) | askovo 与底层研究逻辑的分工 |
| [故障排查](docs/troubleshooting.md) | 安装、路由、采集、MCP |

Agent 入口：[llms.txt](llms.txt) · [AGENTS.md](AGENTS.md) · [SKILL.md](skills/askovo/SKILL.md)。

参与与发布：[贡献指南（含 AI 辅助政策）](CONTRIBUTING.md) · [安全政策](SECURITY.md) · [发布流程](RELEASING.md) · [行为准则](CODE_OF_CONDUCT.md)。如果 askovo 让你的研究决策更可追溯，欢迎 Star、提交合成数据复现的 Issue，或分享一个真实采用案例。

## 仓库结构

```text
assets/brand/askovo-logo.png   品牌字标
skills/askovo/                 产品 Skill 与运行时
  SKILL.md                     单入口协议与判断规则
  assets/method-catalog.json   方法目录（32 种）
  assets/domain-packs/         五类产品研究包
  assets/platform-catalog.json 平台可用性目录
  scripts/askovo.py            确定性 CLI（同一入口）
  scripts/sure_engine.py       SURE 研究引擎（路由/计划/采集/分析/交付）
  scripts/askovo_mcp.py        MCP 外壳
docs/                          人类向文档
examples/sample-study/         离线合成样例
tests/                         CLI、路由、平台、MCP 测试
```

## License

MIT。第三方组件与数据权利边界见 [LICENSE](LICENSE) 与 [docs/connectors.md](docs/connectors.md)。

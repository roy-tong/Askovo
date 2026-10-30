# 快速开始

## 环境

- Python 3.9–3.12；核心 CLI 与 MCP 无第三方依赖。
- 平台采集需要官方 API、授权导出或合规数据集，见[平台与连接器](connectors.md)。
- 不需要为五类产品安装不同 CLI/Skill。

## 安装一次

```bash
git clone https://github.com/roy-tong/askovo.git
cd askovo
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .
.venv/bin/askovo --version
```

或 `pipx install --editable .`。

先运行合成样例：

```bash
askovo demo
```

`pass` 只表示样例的结构、推理和证据引用自洽，不证明真实需求或产品成功。

## 第一步：先路由，先看主链

```bash
askovo do "家用摄像头夜间告警误报，想验证样机" --dry-run
```

输出先给出：

> 场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业

然后才是领域、生命周期、支撑方法、风险和平台预判。`dry-run` 不写文件。

## 第二步：创建工作区与推理画布

```bash
askovo do "家用摄像头夜间告警误报，想验证样机" --study ./cam-study
askovo chain ./cam-study
```

关键产物：

```text
study.json                         决策、范围、假设、门与交付受众
04-findings/product-reasoning.json 唯一主链机器真值
06-report/product-reasoning.md     主链可读投影
route.json / route.md              领域与阶段路由依据
01-sources/research-plan.md        主链优先的研究计划
01-sources/source-plan.csv         推理节点 × 证据角色 × 来源路线
01-sources/instruments/            访谈/观察/任务/Beta/授权等支撑工具
```

先填写 `product-reasoning.json`：

1. **场景**：触发、环境、任务上下文；
2. **用户**：角色、状态、决策角色；
3. **痛点**：当前替代、摩擦成本、后果；
4. **需求**：解法中立的结果、约束、衡量方式；
5. **特性**：能力、接受条件、备选方案及推导理由；
6. **产品**：形态、范围、非目标、验收及组合理由；
7. **商业**：市场边界、目标细分、付费者、竞争定位、渠道、收入/价格、成本、单位经济、市场估计、成功指标和商业门。

每个节点都写 `statement/rationale/status/assumptions`。不知道就保留 hypothesis，不要让 Agent 编造。商业数字必须有总体、时间窗、单位、公式和来源；未知保留为未知。再补全 `study.json` 的决策选项、负责人、截止日、证伪条件、样本理由和停止规则。

## 第三步：通过 Design gate，再设计补证

```bash
askovo check ./cam-study --stage design
```

Design gate 检查决策合同和主链结构。真实 fixture/API/CDP 采集与 queue run 在门前都会停止；dry-run 只用于规划。

查看支持性数据来源：

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
```

- `supported`：官方 API、第一方或合规数据集；
- `limited`：需授权、研究资格或历史数据；
- `blocked`：没有合规批量通道。

`source-plan.csv` 的 `reasoning_nodes` 要说明每条路线补哪个节点或推导。平台可用不等于样本代表总体，数据量本身不是研究目标。

如果一开始就有明确区域、样本目标和平台类型，也可用支撑入口创建一个新工作区（不要对已有非空目录重复执行）：

```bash
askovo plan ./cam-study-intake --goal "夜间误报与替代方案" \
  --region cn --sample-size 1000 --platform-types forum,video
```

`plan` 仍只是 Design 草稿，不替代主链和门禁。

## 第四步：采集或导入支撑材料

**GitHub / Reddit 官方 API**

```bash
askovo collect ./cam-study --platform github --query "camera motion alert" --limit 100
askovo collect ./cam-study --platform reddit --query "night alert" --limit 100
```

Reddit 需要 `ASKOVO_REDDIT_CLIENT_ID` / `ASKOVO_REDDIT_CLIENT_SECRET`。

**授权导出、历史数据集或访谈**

```bash
askovo collect ./cam-study --platform reddit --fixture export.jsonl --query "night alert" --limit 1000
askovo import ./cam-study interviews.jsonl --source-family interview
```

每次平台采集写 raw envelope、normalized 和 manifest；它们不是自动可用的需求证据。无适配器时返回 `3` 并保留路线缺口，不做未授权抓取。

## 第五步：分析、编码、更新判断与主链

```bash
askovo analyze ./cam-study --question "夜间误报"
askovo codebook ./cam-study
askovo signals ./cam-study
```

`analyze` 只输出描述性分布、候选词和匹配片段，不自动产生需求或 PRD。

按以下顺序更新：

1. `02-data/evidence.jsonl`：直接观察、E-level、来源和 evidence basis；
2. `04-findings/demand-judgments.json`：问题、方案接受、商业行为与反证链；
3. `04-findings/product-reasoning.json`：把已登记证据挂到相应节点，并审查 rationale、假设和替代解释。

节点证据必须是 linked demand judgment 已登记证据的子集，不能只改主链文件“补证”。

## 第六步：审计证据和推理

```bash
askovo check ./cam-study --stage full --write-report
askovo audit ./cam-study --json
```

审计同时检查：

- 原需求/方案/商业/反证和 context 门；
- 七节点是否完整，rationale 是否缺失；
- 特性是否有备选，产品是否有范围、非目标和验收；
- 商业节点是否有市场边界、细分、价格、成本、单位经济、指标和业务门；
- 引用是否越过 linked judgment；
- delivery、observed outcome、causal 是否被混写。

自动通过不等于语义真实、人工复核、发布批准或商业成功。市场规模、单位经济和支付证据仍需专业复核。

## 第七步：按分析工作流与职责交付

```bash
askovo deliver ./cam-study --kind report   # 产品/商业总报告
askovo deliver ./cam-study --kind mrd      # 市场研究与分析 → MRD
askovo deliver ./cam-study --kind prd      # 需求研究与分析 → PRD
askovo deliver ./cam-study --kind brd      # 商业分析 → BRD
askovo deliver ./cam-study --kind memo     # 产品/商业决策
askovo report ./cam-study                  # 06-report/research-status.md
askovo deliver ./cam-study --kind ops      # 06-report/user-ops.md
askovo deliver ./cam-study --kind tracker  # 行为、验收与商业指标跟踪
```

MRD/PRD/BRD 模板和访谈包见 [SKILL](../skills/askovo/SKILL.md) 的模板入口。三者是同一七节点主链的三个投影，详见[市场、需求与商业分析](business-analysis.md)。所有交付默认草稿，必须能回链主链和证据。

## 可选：CDP 与队列

**CDP，仅授权可见页面**

```bash
askovo collect ./cam-study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms
```

仅限 amazon/instagram/bilibili/weibo；X/YouTube 不用浏览器自动化。命中验证码或挑战页立即停止。

**队列**

```bash
askovo queue init ./cam-study
askovo queue add ./cam-study --platform reddit --query "night alert" --limit 100
askovo queue run ./cam-study --workers 4
askovo queue status ./cam-study
```

队列支持租约回收、退避重试、限速和断点续跑，不改变任何证据或推理门。

## 完整链路

```text
决策问题 → do/chain 建立七节点假设 → Design gate
→ 针对最弱节点选择方法与来源 → collect/import → analyze/编码
→ evidence → demand judgment → product/business reasoning
→ MRD / PRD / BRD 投影 → full audit
→ PM/研究/运营/市场/需求/商业职责交付 → 验证、发布与运营回流
```

下一步：[岗位方法论](product-methodology.md) · [五域差异](modes.md) · [数据契约](data-contract.md) · [CLI 参考](cli.md)。

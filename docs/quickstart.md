# 快速开始

## 环境

- Python 3.9+
- 核心 CLI 与 MCP 无第三方依赖
- 平台采集需要对应官方 API/授权导出，见 [平台与连接器](connectors.md)

## 安装一次

```bash
git clone https://github.com/roy-tong/askovo.git
cd askovo
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .
.venv/bin/askovo --version
```

或：

```bash
pipx install --editable .
askovo --version
```

不需要为不同产品类型安装不同 skill/CLI；同一个 `askovo` 路由五类产品。

## 第一步：路由一个需求

```bash
askovo do "家用摄像头夜间告警误报，想验证样机" --dry-run
```

输出会说明：

- 产品类型：硬件
- 阶段：需求发现/原型/验证等
- 方法：现场观察、原型任务、Beta/遥测等
- 风险：是否需要 S0
- 平台预判：Reddit、YouTube、工单、访谈等
- 下一步命令

## 第二步：生成研究计划与工具包

```bash
askovo do "家用摄像头夜间告警误报，想验证样机" --study ./cam-study
```

生成：

```text
study.json                 决策、方法、风险、证据计划
route.json / route.md      路由依据
01-sources/research-plan.md
01-sources/evidence-plan.json
01-sources/source-plan.csv
01-sources/platform-plan.json  平台适配、访问方式、限制
01-sources/instruments/    访谈/观察/任务/Beta/授权等
method-choice.json
```

补全 `study.json` 的决策、选项、截止日、假设、证伪条件、样本理由与停止规则。

## 第三步：判断数据在哪

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
```

输出平台适配分、访问方式、批量能力、限制与偏差。注意：

- `supported`：官方 API/第一方/合规数据集；
- `limited`：需授权、研究资格或历史数据；
- `blocked`：没有合规批量通道（如未经授权的 Instagram/小红书/JD/淘宝抓取）。

平台可用不等于样本代表总体。

## 第四步：采集/导入

**GitHub（官方 API）**

```bash
askovo collect ./cam-study --platform github --query "camera motion alert" --limit 100
```

**Reddit（官方 Data API）**

```bash
export ASKOVO_REDDIT_CLIENT_ID=...
export ASKOVO_REDDIT_CLIENT_SECRET=...
askovo collect ./cam-study --platform reddit --query "night alert" --limit 100
```

**授权导出/历史数据集**

```bash
askovo collect ./cam-study --platform reddit --fixture export.jsonl --query "night alert" --limit 1000
askovo import ./cam-study interviews.jsonl --source-family interview
```

**其他平台**

```bash
askovo collect ./cam-study --platform instagram --query "..." --dry-run
```

若没有内置适配器，返回 `3` 并给出授权导出/本地数据集路径；不会做未授权抓取。

每次采集写：

```text
01-sources/manifests/<run_id>.json
02-data/raw/<platform>/<run_id>.jsonl
02-data/normalized.jsonl
```

## 第五步：分析

```bash
askovo analyze ./cam-study --question "夜间误报"
```

输出 `04-findings/analysis.json` / `analysis.md`：平台/时间/结论类型分布、高频候选主题、问题匹配片段。

这是描述性分析，不证明总体比例或因果。深入编码与判断仍由 Skill/研究员完成。

## 可选：CDP 与队列

**CDP（仅授权可见页面）**

```bash
askovo collect ./cam-study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms
```

需要 Chrome 以 `--remote-debugging-port=9222` 启动，且使用本人已登录 profile。命中验证码/挑战页会停止，不绕过。

**队列（并发/断点/限速）**

```bash
askovo queue init ./cam-study
askovo queue add ./cam-study --platform reddit --query "night alert" --limit 100
askovo queue add ./cam-study --platform github --query "camera alert" --limit 100
askovo queue run ./cam-study --workers 4
askovo queue status ./cam-study
```

失败任务会退避重试；worker 崩溃后租约过期自动回收；`queue retry` 可把 failed 重新入队。

## 第六步：编码与交付

```bash
askovo codebook ./cam-study
askovo deliver ./cam-study --kind memo
askovo deliver ./cam-study --kind prd
askovo deliver ./cam-study --kind tracker
```

产物在 `06-report/`：

- `memo.md` 决策备忘
- `report.md` 研究报告
- `prd.md` PRD 输入
- `postlaunch-tracker.csv` 上市/复测跟踪

未签收前都标“草稿”；结论必须能回链到证据 id。

## 完整链路

```text
askovo do → 补 study.json → instruments → collect/import
→ analyze → codebook → deliver → 人审签收 → 上市/复测
```

## 下一步

- 五类产品方法：[modes.md](modes.md)
- 六类结论与边界：[concepts.md](concepts.md)
- 命令与退出码：[cli.md](cli.md)
- 平台访问与限制：[connectors.md](connectors.md)

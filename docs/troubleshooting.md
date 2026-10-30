# 故障排查

## 安装

### `askovo: command not found`

- 源码 checkout 中用 `pipx install --editable .`，或安装已验证的本地 wheel；随后确认 `~/.local/bin` 在 `PATH`。PyPI 尚未发布，不要直接执行 `pipx install askovo`；
- 源码安装用 `.venv/bin/askovo`，或先 `source .venv/bin/activate`；
- 不要直接 `python3 skills/askovo/scripts/askovo.py` 当作日常入口，它不暴露 `--version` 之外的包行为。

### `pip install -e .` 失败

macOS 自带 Python 3.9 的 pip 是 21.2，不支持 pyproject 的 editable 安装：

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -e .
```

若仍失败，检查 `pyproject.toml` 是否在仓库根、`VERSION` 文件是否存在。

### `askovo: runtime not found`

说明 `askovo` 找到了，但 packaged runtime 或源码 fallback 不在预期位置。普通 wheel 已包含 runtime；优先安装同一版本的已验证本地 wheel。开发 checkout 也可重新执行：

```bash
pipx install --editable /path/to/askovo
askovo doctor
```

## 版本

### 审计报告出现版本警告

```text
- 方法版本：`askovo 1.6`（⚠ study records askovo 1.6; current runtime is 2.0.1）
```

说明 study 是旧版本创建的。处理方式：

- 新研究：重新 `plan`，会自动写入当前版本；
- 旧研究：把 `study.json` 的 `method_version` 改成当前版本，并在变更记录里注明；
- 不要忽略这条警告——审计链依赖版本可追溯。

### `askovo --version` 与 `VERSION` 不一致

`doctor` 会同时显示包版本与 `VERSION` 文件版本。不一致说明安装的是旧包：

```bash
askovo doctor
python3 -m pip install --force-reinstall /path/to/askovo-2.0.1-py3-none-any.whl
```

把路径换成该版本的实际 wheel；开发 checkout 则用 `pipx install --editable .` 重装。

## 门禁

### design gate 不过

常见缺项：

- `decision` 的 `owner`、`deadline`、`options`（至少两个）、`minimum_evidence`
- `hypotheses[].statement` 与 `falsified_if`
- `scope.target_users`
- `stopping_rules` / `restart_rules`
- `source_adapters.*` 的 `data_rights_basis`、`retention_rule`、`terms_reviewed_at`
- `product-reasoning.json` 缺失，或七节点的 `statement/rationale/status` 仍是占位符
- 特性没有备选方案，或产品缺范围、非目标、验收（decided 时）
- 商业节点缺市场边界、地理范围、时间窗、细分、价格/收入假设、成本、单位经济、成功指标或业务门
- 市场规模数字缺总体、时间窗、单位、公式或来源

先运行 `askovo chain ./study` 定位主链，再按 `check` 输出的 `detail` 逐项补。不要用更多采集量代替缺失的推导，也不要用市场规模或竞品报价填补商业缺口。

### evidence gate 不过

- 记录数低于 `quality_gates.min_evidence_records`
- 缺 `required_corpus_roles` 中的角色
- 重复率超过 `max_normalized_duplicate_rate`
- 主导来源占比超过 `max_source_family_share`
- 来源族不在 `source-plan.csv` 中

按主链最弱节点补采，不要改门槛来“通过”，也不要用无关平台数据凑量。

### decision gate 不过

- `demand-judgments.json` 为空或结构缺字段
- 引用了不存在的 `record_id`
- `validated` 缺少问题链、方案链、商业链或反证
- `validated` 缺少 `context_key`，或引用证据的 `context_key` 与判断不一致；不要用不相关记录凑等级
- chain 与 judgment 的 `demand_judgment_id/context_key` 不匹配，或一个 judgment 没有 chain
- 节点引用了未在 linked judgment 登记的证据；先把证据登记到正确链条，不能只改主链文件
- `decided` 缺反证、替代解释、七节点 validated 或 linked judgment validated
- release-ready 没有 release_plan_ref、结果状态没有 metric_refs、因果结论没有 experiment_refs；E3/E5 不能替代这些独立状态

### audit 退出码 1，但 check 是 0

说明结构没问题，但有 `validated` 判断**超出证据**。看 `05-audit/audit.md` 的“判断与证据”表，把该判断降级为 `needs-validation`，或补对应链条。

这是 `audit` 比 `check` 严格的地方，也是它的价值。

## 信号与报告

### `signals` 输出全 0

`02-data/evidence.jsonl` 不存在或为空。先确认采集是否真的写入了记录。

### `report` 顶部有失败横幅

正常行为。`askovo report` 写 `06-report/research-status.md`，只有在 `check --stage full` 通过后才去掉横幅；未通过时输出的是研究状态，不是结论。产品报告由 `deliver --kind report` 写 `06-report/report.md`，两者不共用写入者。

### 报告里出现“待填写”

`study.json` 还有占位符。`plan` 只生成骨架，决策、假设、证伪条件必须人来补。

## MCP

### 客户端连不上

```bash
askovo mcp
```

应该是一个等待 stdin 的进程。若命令立即退出，先跑 `askovo doctor`。

配置示例：

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

如果客户端不支持 `askovo` 在 PATH 中，写绝对路径：

```json
{"command": "/Users/you/.local/bin/askovo", "args": ["mcp"]}
```

### `tools/list` 里没有 `askovo_audit`

说明运行的是旧版本。`askovo --version` 应为 2.0.0 或更高；用源码或对应的本地 wheel 重装，再用 `askovo-mcp --tools` 或 MCP `tools/list` 复核。

## 平台与编码

- Python 3.9–3.12；不使用 3.10+ 语法；
- Windows 原生终端对 UTF-8 输出可能需要 `chcp 65001`；
- 采集需要平台 API 资格，与 Askovo 安装无关，见 [连接器](connectors.md)；
- 所有命令不写入仓库外的路径，study 目录由你显式传入。

## 还是不通

带上三样东西提 issue：

1. `askovo --version` 与 `askovo doctor` 输出；
2. 复现命令（去掉凭据与真实数据）；
3. `05-audit/audit.json` 里相关的 `checks` 片段。

## 路由

### `needs_domain` / 退出码 2

没有识别出产品类型。加显式领域：

```bash
askovo do "..." --domain software|hardware|consumer|automotive|mobile
```

也可以先跑 `askovo domains` 看五个研究包。

### 阶段识别不符合预期

用 `--stage` 覆盖：

```bash
askovo do "..." --stage discovery|concept|prototype|validation|pricing|prelaunch|postlaunch|audit
```

典型误区：“验证某方向值不值得做”应走 discovery；“验证原型是否达到发布门槛”才是 validation。

### 退出码 4

检测到高风险研究（道路测试、摄入/皮肤接触、儿童、敏感数据、生产日志、破坏性测试等）。这不是错误，是 S0 门：

1. 由负责人完成安全/伦理审查与授权；
2. 记录审查人与限制；
3. 追加 `--ack-risk` 生成计划。

Agent 不应自行加 `--ack-risk`。

## 平台与采集

### `platforms` 推荐了不相关平台

用 `--domain` 限定；平台目录会按领域、结论类型、评论/价格信号和批量要求打分。推荐分不表示数据质量，读 `limits` 与 `bias`。

### `collect` 返回 3 / `adapter_unavailable`

该平台没有内置批量适配器。改用：

```bash
askovo collect ./study --platform amazon --fixture amazon-export.jsonl --query "..."
askovo import ./study export.csv --source-family amazon
```

或使用平台官方/授权 API；不要换成未授权抓取。

### `collect` 返回 3 / `blocked`

平台没有合规批量通道（如小红书、知乎、京东、淘宝、Kickstarter）。只能使用授权导出或人工整理。

### GitHub 403 / rate limit

设置 `GITHUB_TOKEN`，或降低 `--limit`。公共搜索 API 未认证限额很低。

### Reddit 认证失败

需要已批准的 Reddit Data API 应用：

```bash
export ASKOVO_REDDIT_CLIENT_ID=...
export ASKOVO_REDDIT_CLIENT_SECRET=...
export ASKOVO_REDDIT_USER_AGENT="askovo/2.0 by <you>"
```

### 采集成功但 `analyze` 没有数据

检查 `02-data/normalized.jsonl` 是否存在、记录是否非空；`collect` 会写该文件，`import` 写 `evidence.jsonl`，`analyze` 会合并两者。

### 采集后 `deliver` 没有证据

`deliver` 合并 `evidence.jsonl` 与 `normalized.jsonl`；若仍为 0，查看 `02-data/` 与 manifest 的 `written` 字段。

## 分析与交付

### 高频词不是结论

`analyze` 输出的是候选主题与描述性分布，不证明总体、因果或需求强度。需要编码、证据分级和人工判断。

### 交付物全是“待补”

这是模板骨架。先补 `study.json` 的决策/假设/证伪/样本理由，导入证据，再重新生成；`deliver` 不会替你做结论。

### MCP 看不到 `askovo_route` / `askovo_do`

运行 `askovo --version`，应为 2.0.0 或更高。`askovo mcp` 是等待 stdin 的 stdio server；请用 `askovo-mcp --tools` 查看清单，或让客户端调用 MCP `tools/list`。旧版本需用源码或本地 wheel 重新安装。

## CDP

### `terms_required` / 退出码 4

CDP 需要显式确认：

```bash
askovo collect ./study --platform amazon --query "..." \
  --cdp-url http://127.0.0.1:9222 --url "https://..." --ack-terms
```

`--ack-terms` 表示你已确认平台条款、账号授权、数据用途与保留。Agent 不应替用户加。

### `cdp_not_allowed`

CDP 只对 amazon、instagram、bilibili、weibo 的授权可见页面开放；X/YouTube 只走官方 API。调试端点必须是回环地址，目标必须是默认端口 HTTP(S) 平台 URL。

### CDP 连接失败

- Chrome 是否以 `--remote-debugging-port=9222` 启动；
- `curl http://127.0.0.1:9222/json/version` 是否返回浏览器信息；
- 是否使用了正确的 `--user-data-dir`（Chrome 136+ 默认 profile 会忽略调试端口）；
- 页面是否要求登录：CDP 使用你当前浏览器的登录态，但不会替你登录。

### `challenge`

页面出现验证码/机器人检查。Askovo 会停止，不绕过；改用授权导出/官方 API/历史数据集。

## 队列

### 任务一直 `retry`

`queue status` 看 `last_error`。常见原因：fixture 路径不存在、平台认证失败、CDP 连接失败。修复外部条件后 `queue retry` 再 `queue run`。

### worker 崩溃后任务卡在 `running`

租约（默认 300 秒）过期后，下一次 `queue run` 会自动回收；也可等待或 `queue retry`（只重置 failed，不重置 running）。

### 并发写坏 `normalized.jsonl`

从 1.14 起使用 cross-process lock 与锁内去重；如果仍看到重复，检查是否运行了旧版本（`askovo --version`）。

### 想跨机器跑

当前队列是单机 SQLite；跨机器共享 SQLite 不可靠。需要外部队列/对象存储适配器，未内置。

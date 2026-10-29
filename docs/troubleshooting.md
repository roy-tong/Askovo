# 故障排查

## 安装

### `sure: command not found`

- `pipx install sure-research` 后确认 `~/.local/bin` 在 `PATH`；
- 源码安装用 `.venv/bin/sure`，或先 `source .venv/bin/activate`；
- 不要直接 `python3 skills/.../sure.py` 当作日常入口，它不暴露 `--version` 之外的包行为。

### `pip install -e .` 失败

macOS 自带 Python 3.9 的 pip 是 21.2，不支持 pyproject 的 editable 安装：

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -e .
```

若仍失败，检查 `pyproject.toml` 是否在仓库根、`VERSION` 文件是否存在。

### `sure: runtime not found`

说明 `sure_research` 找到了，但仓库里的 `skills/user-demand-research/scripts/sure.py` 不在预期位置。阶段 1 的包装依赖 editable 安装；重新执行：

```bash
pipx install --editable /path/to/user-demand-research
```

## 版本

### 审计报告出现版本警告

```text
- 方法版本：`SURE 1.6`（⚠ study records SURE 1.6; current runtime is 1.12.0）
```

说明 study 是旧版本创建的。处理方式：

- 新研究：重新 `plan`，会自动写入当前版本；
- 旧研究：把 `study.json` 的 `method_version` 改成当前版本，并在变更记录里注明；
- 不要忽略这条警告——审计链依赖版本可追溯。

### `sure --version` 与 `VERSION` 不一致

`doctor` 会同时显示包版本与 `VERSION` 文件版本。不一致说明安装的是旧包：

```bash
sure doctor
pipx reinstall sure-research
```

## 门禁

### design gate 不过

常见缺项：

- `decision` 的 `owner`、`deadline`、`options`（至少两个）、`minimum_evidence`
- `hypotheses[].statement` 与 `falsified_if`
- `scope.target_users`
- `stopping_rules` / `restart_rules`
- `source_adapters.*` 的 `data_rights_basis`、`retention_rule`、`terms_reviewed_at`

按 `check` 输出的 `detail` 逐项补。

### evidence gate 不过

- 记录数低于 `quality_gates.min_evidence_records`
- 缺 `required_corpus_roles` 中的角色
- 重复率超过 `max_normalized_duplicate_rate`
- 主导来源占比超过 `max_source_family_share`
- 来源族不在 `source-plan.csv` 中

先补采，不要改门槛来“通过”。

### decision gate 不过

- `demand-judgments.json` 为空或结构缺字段
- 引用了不存在的 `record_id`
- `validated` 缺少问题链、方案链、商业链或反证

### audit 退出码 1，但 check 是 0

说明结构没问题，但有 `validated` 判断**超出证据**。看 `05-audit/audit.md` 的“判断与证据”表，把该判断降级为 `needs-validation`，或补对应链条。

这是 `audit` 比 `check` 严格的地方，也是它的价值。

## 信号与报告

### `signals` 输出全 0

`02-data/evidence.jsonl` 不存在或为空。先确认采集是否真的写入了记录。

### `report` 顶部有失败横幅

正常行为。报告只有在 `check --stage full` 通过后才会去掉横幅；未通过时它输出的是“研究状态”，不是结论。

### 报告里出现“待填写”

`study.json` 还有占位符。`plan` 只生成骨架，决策、假设、证伪条件必须人来补。

## MCP

### 客户端连不上

```bash
sure mcp
```

应该是一个等待 stdin 的进程。若命令立即退出，先跑 `sure doctor`。

配置示例：

```json
{
  "mcpServers": {
    "sure-research": {
      "command": "sure",
      "args": ["mcp"]
    }
  }
}
```

如果客户端不支持 `sure` 在 PATH 中，写绝对路径：

```json
{"command": "/Users/you/.local/bin/sure", "args": ["mcp"]}
```

### `tools/list` 里没有 `sure_audit`

说明运行的是旧版本。`sure --version` 应为 1.12.0 或更高；`pipx reinstall sure-research`。

## 平台与编码

- Python 3.9–3.12；不使用 3.10+ 语法；
- Windows 原生终端对 UTF-8 输出可能需要 `chcp 65001`；
- 采集需要平台 API 资格，与 SURE 安装无关，见 [连接器](connectors.md)；
- 所有命令不写入仓库外的路径，study 目录由你显式传入。

## 还是不通

带上三样东西提 issue：

1. `sure --version` 与 `sure doctor` 输出；
2. 复现命令（去掉凭据与真实数据）；
3. `05-audit/audit.json` 里相关的 `checks` 片段。

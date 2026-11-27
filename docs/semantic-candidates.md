# 语义候选层（受约束召回）

确定性的 `analyze` 能回答“语料里有什么”，但会漏掉同义表达、隐含机制和少数派反例。语义候选层把大模型放进一个**受约束的候选证据层**：模型可以扩大召回，但不能下结论。

## 四层结构

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| 确定性底座 | 去重、字段完整性、共现主题、机制/转折句、平台/证据等级/时间分层抽样 | 语义命名、隐含表达 |
| 语义扩展 | 按批次产出主题、机制、反例候选，每条挂 `record_id` + 原文 `quote` | 证据等级、需求判断、`validated` |
| 对抗复核 | 反例、覆盖缺口、替代解释、还缺什么证据；先复核再展示 | 证明主题为真或为假 |
| 人工裁决 | 具名 `accept/reject`；accept 后才能导出 E2 收集陈述观察 | 自动写入 `evidence.jsonl` |

## 硬约束

`04-findings/semantic-candidates.json` 使用 `askovo.semantic-candidate/1`：

```json
{
  "schema": "askovo.semantic-candidate/1",
  "generator": "askovo.semantic",
  "generator_version": "1",
  "model": "local-model-name",
  "prompt_hash": "sha256:...",
  "input_hash": "sha256:...",
  "created_at": "2026-11-24T09:00:00+00:00",
  "status": "unverified",
  "candidates": [
    {
      "candidate_id": "theme-night-alert-fatigue",
      "kind": "theme",
      "statement": "用户把夜间误报视为需要主动关闭的打扰，而不是安全提醒。",
      "evidence_refs": [
        {"record_id": "R01", "quote": "夜间误报很烦，希望先判断再起床", "platform": "reddit", "evidence_level": "E1"}
      ],
      "unknowns": ["没有用户主动说明误报率阈值", "缺少关闭推送后的复开行为"],
      "status": "unverified"
    }
  ]
}
```

校验器会拒绝：

- `record_id` 不在当前 study，或同一 id 对应多条不同平台/来源记录；
- `quote` 不是该记录正文的子串（允许空白折叠后的匹配）；
- 没有 `unknowns`；
- `status` 不是 `unverified`；
- 模型写了 `evidence_level`、`demand_claim`、`validated` 或 `product_reasoning`。

被拒绝的候选只出现在 `semantic-report.json` 的 `rejected` 里，不进入候选库。

## 命令

```bash
# 默认关闭；没有模型配置时自动退回确定性分析
askovo analyze ./study --question "夜间误报"

# 显式启用语义层（本地模型或已授权的远程模型）
askovo analyze ./study --question "夜间误报" --semantic

# 离线确定性 stub：用于测试 schema、引用校验和完整管线
askovo analyze ./study --semantic --semantic-provider offline

# 指定记录上限、批次大小与检索方式
askovo analyze ./study --semantic --semantic-max-records 120 \
  --semantic-batch-size 20 --retrieval auto
```

`analyze` 退出码：`0` 成功或按设计回退；`1` 语义层 partial/failed；`2` 远程端点未授权或参数错误。确定性 `analysis.json` / `analysis.md` 仍会先写出，语义失败不隐藏已有分析。

## 模型配置与隐私

使用标准库 `urllib` 调用 OpenAI-compatible 接口，不新增依赖：

| 变量 | 作用 |
| --- | --- |
| `ASKOVO_LLM_BASE` | 例如 `http://localhost:11434/v1` 或 `https://api.example.com/v1` |
| `ASKOVO_LLM_KEY` | 可选；本地模型通常不需要 |
| `ASKOVO_LLM_MODEL` | 模型名 |
| `ASKOVO_LLM_TIMEOUT` | 单次请求超时秒数，默认 60 |
| `ASKOVO_SEMANTIC_PROVIDER` | `offline` / `openai` / `auto` |

- 默认不把原文外发：非 loopback 端点必须显式加 `--allow-external`，否则退出码 2 且不发送任何语料。
- 远程端点必须使用 HTTPS；`http` 只允许 loopback。
- 模型与 embedding 请求不跟随重定向；必须在配置中写最终端点，避免把 Authorization 转发给另一个目标。
- 支持本地模型，语料可以不出本机。
- 请求只包含被选中的记录文本、记录 id、平台和证据等级，不含凭据和登录态。

## 检索层

`--retrieval` 控制进入批次前的候选记录选择：

- `embedding`：优先本地/私有 embedding（`ASKOVO_EMBED_BASE` / `ASKOVO_EMBED_KEY` / `ASKOVO_EMBED_MODEL`），缓存只存文本哈希与向量；
- `keyword`：词面匹配，覆盖不了同义表达；
- `auto`：有 embedding 配置且允许时用向量，否则退回关键词。

检索只负责“找出相关记录”，不生成结论。最终选样仍按主题、平台、证据等级与月份分层轮转，避免模型只看到最密集的一类声音。

## 对抗复核

每次语义运行都会先写 `04-findings/semantic-critic.json`，再允许查看或复核候选。复核内容包括：

- `counterexamples`：同主题、含转折/否定标记、可能削弱候选的记录；
- `coverage_gaps`：未覆盖的平台、证据等级、时间或人群；
- `alternative_explanations`：模型给出的替代解释（确定性层不生成）；
- `needs_more_evidence`：补证清单。

确定性扫描不会证明主题为假；它只把“没找到反例”和“没有反例”区分开。模型 critic 的反例引用同样要过 `record_id` + 原文子串校验，不合法引用会被丢弃并记录。

## 人工裁决与 E2 导出

```bash
askovo semantic list ./study
askovo semantic review ./study --candidate theme-night-alert-fatigue \
  --decision accept --reviewer alice --note "两条原始引文已核对"
askovo semantic support ./study --candidate theme-night-alert-fatigue \
  --entailment supported --context intact --generalization-risk low \
  --reviewer alice --note "引文与上下文支持该候选"
askovo semantic export ./study --by alice --export-now
```

- 没有 critic 记录的候选拒绝复核（`REVIEW_REQUIRED`）。
- 复核日志追加到 `04-findings/semantic-reviews.jsonl`，同一结论重复提交是幂等的。
- 只有最新决定为 `accept`、且 `--by` 与复核人一致的候选才能导出；复核同时绑定 candidate hash 与 critic hash，任一变化都要重新复核。导出前还必须有当前 candidate+critic 绑定的具名支持度评估，`not_assessed` 不再导出。
- `accept/reject` 只能由人在 CLI 中执行；MCP `askovo_semantic` 仅支持 `list/export/validate`，不能代填 reviewer 自签。
- 导出先生成 `01-sources/semantic-observations/<id>.json`，通过 `observation.py` 的 E2 校验；`--export-now` 再调用 `askovo observation export` 写 `01-sources/observations.jsonl`。
- 导出结果分三种状态：`exported`（至少写出一条）、`nothing_to_export`（没有待导出或被跳过的既有成功）、`blocked`（有已接受候选，但全部因支持度为 `contradicted`/`unsupported`、复核过期、critic 过期或观察校验失败被拦）。`blocked` 返回**退出码 1**，`nothing_to_export` 与幂等重复导出返回 0；批量自动化不应把“导出 0 条”当成功。
- 批次选择先按正文长度过滤：短于 `MIN_RECORD_CHARS`（24 字符）的记录（如 `yupp`、`+1`）不进入模型批次，`selection.filtered_short` 记录被过滤条数；引文本身仍允许短于该阈值。
- 进入 `02-data/evidence.jsonl` 仍需具名人工语义审核，不会自动发生。

导出的观察使用 `source_kind: collected_corpus_statement` 与 `basis: collected_statement_quote`。这里的 E2 含义是**这句原话确实出现在语料中**，不是“主题已被验证”，也不证明总体比例、需求强度或方案接受。

## 产物

| 文件 | 内容 |
| --- | --- |
| `04-findings/semantic-candidates.json` | 完整候选文档（含 schema、模型、哈希、引用） |
| `04-findings/semantic-candidates.jsonl` | 每行一个候选，便于逐条复核 |
| `04-findings/semantic-critic.json` | 每个候选的反例、覆盖缺口、替代解释与补证清单 |
| `04-findings/semantic-candidates.md` | 供人阅读的候选 + critic 页面 |
| `04-findings/semantic-report.json` | 批次、选样、拒绝原因、重命名、模型/隐私状态 |
| `04-findings/semantic-reviews.jsonl` | append-only 具名复核日志 |
| `01-sources/semantic-observations/` | 通过复核后生成的观察文档，等待 `observation export` |

## 边界

- 语义候选不是 `product-reasoning.json`、`demand-judgments.json` 或 `evidence.jsonl` 的替代品。
- 模型不写七节点链、不写证据等级、不标记 `validated`；这些仍由确定性代码、具名审核和责任人决定。
- 候选数量、平台覆盖或“模型也这么说”都不证明总体比例、因果、市场规模、上线结果或商业成功。
- 离线 stub 只验证管线契约，不代表真实模型召回质量。

# 三种模式

SURE 的深度是选项，不是门槛。先判断你手上有什么，再选模式。

## 快速选择

| 你手上有什么 | 模式 | 第一条命令 | 首值时间 |
| --- | --- | --- | --- |
| 已有一批材料，想知道能否支持某个决定 | Quick Audit | `sure audit <study>` | 10 分钟 |
| 还没有材料，想设计一个能过审的研究 | Design | `sure plan <study> …` | 1 小时 |
| 要跑完整研究，产出报告与商业文档 | Full Study | `sure plan` → 采集 → `sure report` | 1–2 周 |
| 前沿体验，用户还叫不出名字 | Unnamed Experience | `sure plan --mode unnamed-experience` | 2–3 小时 |

## Quick Audit

**适合**：产品经理、研究员、投资人手上已有访谈、评论、工单，需要回答“这些能不能支持我要做的决定”。

**输入**：一个按 [数据契约](data-contract.md) 整理的 study 目录。

```bash
sure audit ./study
sure audit ./study --claim "用户愿意付费"
```

**输出**：

- `05-audit/audit.json`：门禁结果、信号、每条判断的 `verdict`
- `05-audit/audit.md`：一页结论

**判断的三种结果**：

| verdict | 含义 | 下一步 |
| --- | --- | --- |
| `supported` | 声称 `validated`，且三条链 + 反证齐全 | 可以引用，但仍要读边界 |
| `exceeds_evidence` | 声称 `validated`，但缺链或反证 | 降级为 `needs-validation`，或补证 |
| `open` | `hypothesis` / `needs-validation`，尚未声称结论 | 按 `next_test` 补证 |

**停止规则**：出现 `exceeds_evidence` 时，不要把它写进对外结论；先降级或补证。

## Design

**适合**：研究还没开始，需要先证明这个研究做得成。

```bash
sure plan ./study \
  --goal "…" --region overseas --sample-size 100000 \
  --platform-types forum,social,video
```

**输出**：

- 决策问题、范围、假设与证伪条件（需补全）
- 平台可行性、配额、连接器 revision、准入前提
- 采集任务清单与路线模板

补全设计契约后：

```bash
sure check ./study --stage design
```

**停止规则**：design gate 不过，不开始采集。不要用“先采了再说”绕过。

## Full Study

**适合**：需要可交付的研究结论，可能要写 BRD/MRD/PRD。

```text
plan → design gate → 采集（写 manifest）→ evidence gate
     → signals → demand-judgments → decision gate → report
```

| 阶段 | 命令 | 通过条件 |
| --- | --- | --- |
| 设计 | `check --stage design` | 决策、假设、证伪、来源计划、adapter 审查字段齐 |
| 证据 | `check --stage evidence` | 记录数、角色覆盖、重复率、来源集中度达标 |
| 决策 | `check --stage decision` | 判断结构完整、引用可追溯、`validated` 有链 |
| 全量 | `audit` | 以上全过，且无 `exceeds_evidence` |

**产出**：

- `04-findings/signals.json`：确定性语料信号
- `04-findings/demand-judgments.json`：判断台账
- `06-report/report.md`：研究状态报告
- `05-audit/audit.md`：审计结论

报告未通过全量检查时，顶部会保留失败横幅，结论只能停留在“研究状态”。

## Unnamed Experience

**适合**：前沿产品，用户还没有稳定词汇（例如一种尚未被命名的体感体验）。

```bash
sure plan ./study --mode unnamed-experience \
  --goal "一种尚未被产品化的体感体验" --region cn \
  --sample-size 50000 --platform-types forum,social
```

它会先做 grounding：边缘语言、替代行为考古、心理物理维度、跨域文献锚点，产出词表与研究范围，再设计关键词路线。

```bash
sure lexicon ./study --min-per-term 20
```

退出码 `1` 表示存量语料不足，是采集指令，不是错误。

## 停止规则（所有模式）

1. **采集前**：design gate 未过，不采集。
2. **跨来源合并前**：来源角色、时间窗、语言不一致时，先说明，不直接合并。
3. **下结论前**：出现 `exceeds_evidence`，先降级或补证。
4. **遇到阻断平台**：不换登录态、商业接口、内部接口或浏览器自动化；记录缺口。
5. **证据不足时**：输出研究状态与修复计划，不输出自信的市场结论。

## 交付物对照

| 模式 | 最小交付 | 可选交付 |
| --- | --- | --- |
| Quick Audit | `audit.md` | 补证清单 |
| Design | `study.json` + `feasibility.json` + `tasks.md` | 研究方案一页纸 |
| Full Study | `report.md` + `signals.json` + `audit.md` | BRD/MRD/PRD |
| Unnamed | `lexicon.csv` + `experience-space.csv` | 命名候选与验证计划 |

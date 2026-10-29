# SURE

**让每一条需求判断都带证据等级、覆盖缺口和证伪条件。**

SURE（Structured User Research with Evidence）把访谈、评论、论坛、工单和行为记录整理成可审计的需求判断，并明确一批材料**能支持什么、还不能支持什么**。

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-user--demand--research-111111)](skills/user-demand-research/SKILL.md)
[![CI](https://github.com/roy-tong/user-demand-research/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/user-demand-research/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Version](https://img.shields.io/badge/version-1.12.0-orange)

## 30 秒证明它能工作

不联网、不采集、不调用模型，跑内置合成样例：

```bash
git clone https://github.com/roy-tong/user-demand-research.git
cd user-demand-research
pipx install --editable .
sure demo
```

预期输出：

```text
SURE 审计：synthetic-mobile-pet-check — pass
- 记录 7 条；重复率 0.0%；主导来源 42.9%
- 判断 1 条：可支持 1、超出证据 0、未定 0
```

没有 pipx 也可以直接跑：

```bash
python3 skills/user-demand-research/scripts/sure.py demo
```

`demo` 只证明本地运行时、门禁和输出格式可用；它不证明样例里的需求真实存在。

## 先选入口

| 你手上有什么 | 用哪个 | 你会得到 |
| --- | --- | --- |
| 一批访谈、评论、工单，想知道能不能支持某个决定 | `sure audit <study>` | 每条判断的可支持等级、缺口、最便宜的补证 |
| 还没开始，想知道这个研究做不做得成 | `sure plan <study> --goal …` | 平台可行性、配额、合规前提、采集任务 |
| 要跑完整研究 | `plan → 采集 → signals → report` | 研究状态报告 + 证据台账 |
| 让 Agent 自己按协议做 | 安装 Skill | 模式选择、停止规则、输出契约 |
| MCP 客户端 | `sure mcp` | 同一组确定性工具 |

## 两个核心命令

### 审计现有材料

```bash
sure audit ./study
sure audit ./study --claim "用户愿意为远程协作付费"   # 只看一条判断
```

输出 `05-audit/audit.md` 与 `audit.json`：

```text
# SURE 审计结论
- 结论：**不可支持（或超出证据）**
- 判断 D01：声称 validated，最高证据 E2 —— 缺商业链（需要 E4+/E5）、缺反证
- 下一步：把 D01 降级为 needs-validation，或补 3 个预购页转化
```

退出码：`0` 通过，`1` 门禁未过或存在超出证据的判断，`2` 用法错误。

### 规划一个新研究

```bash
sure plan ./study \
  --goal "AI 眼镜在海外社媒的用户不满与替代方案" \
  --region overseas --sample-size 100000 --platform-types forum,social,video
```

得到平台配额、连接器 revision、每条路线的准入前提和采集任务清单。若没有可行平台，返回 `3` 并说明缺口，不会换成登录态或商业接口。

## 安装

**CLI（当前版本从源码安装）**

```bash
pipx install --editable ./user-demand-research
sure --version
```

或使用 venv：

```bash
python3 -m venv .venv && .venv/bin/pip install -U pip
.venv/bin/pip install -e .
.venv/bin/sure demo
```

> PyPI 包发布后可以简化为 `pipx install sure-research`；当前版本尚未上传。

**Agent Skill**

```bash
# 从仓库安装（固定位置）
bash scripts/install-skill.sh                 # 默认 ~/.agents/skills
bash scripts/install-skill.sh ~/.codex/skills
```

若本机有 skills CLI 且该仓库已被索引，也可以用 `npx skills add roy-tong/user-demand-research --skill user-demand-research -g`。

**MCP**

```bash
sure mcp
```

配置里只需要这一行，不再写绝对路径。工具：`sure_audit`、`sure_plan`、`sure_init`、`sure_check`、`sure_signals`、`sure_lexicon`、`sure_report`、`sure_connectors`、`sure_platform_map`。

## 它解决什么问题

AI 让“生成研究”变便宜，变贵的是**判断证据够不够**。

| 常见工具 | 它们解决 | SURE 不跟它们抢 |
| --- | --- | --- |
| 访谈整理 / 洞察看板 | 标签、聚类、协作 | 不做分析 UI |
| 通用大模型 | 快速摘要与结论 | 不替你下结论 |
| 采集工具 | 把数据拿回来 | 不做大规模采集，只审连接器合规 |
| **SURE** | **这批材料能支持到哪一级** | 审计层，夹在采集与决策之间 |

### 证据等级（E0–E5）

| 等级 | 材料中直接出现 | 允许的判断 |
| --- | --- | --- |
| E0 | 活动、角色或场景背景 | 这个场景出现在材料中 |
| E1 | 未满足任务、目标或困难 | 问题被明确表达 |
| E2 | 当前做法、绕行、失败或切换成本 | 已观察到替代方案及摩擦 |
| E3 | 对研究方案的明确接受或偏好 | 方案在给定条件下被接受 |
| E4+ | 价格锚点、购买或付费表达 | 出现直接商业意图 |
| E4− | 拒绝、取消、退货或放弃 | 出现直接负面商业行为 |
| E5 | 付费持有、部署、持续使用、复购 | 出现已实现的行为证据 |

只有同一角色、场景和任务同时连接问题链 `E1/E2`、方案链 `E3` 与商业/行为链 `E4+/E5`，判断才能标为 `validated`；`E4−` 与反证必须保留。

## 边界

- 不绕过登录、付费墙、验证码、robots、403/429；
- 不用商业接口、商家 API、登录态替代被阻断的开源连接器；
- 不把代码许可证当平台访问许可或数据使用许可；
- 不把记录数写成用户数，不把检索地区写成常住地；
- 不用便利样本推断总体比例、市场规模或份额；
- 证据不足时输出研究状态与修复计划，不输出自信的市场结论。

完整边界与禁止推断见 [docs/concepts.md](docs/concepts.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [快速开始](docs/quickstart.md) | 安装、demo、audit、plan、完整研究 |
| [核心概念](docs/concepts.md) | E0–E5、证据角色、判断结构、边界 |
| [三种模式](docs/modes.md) | Quick Audit / Design / Full Study 怎么选 |
| [CLI 参考](docs/cli.md) | 命令、参数、退出码、JSON 输出 |
| [数据契约](docs/data-contract.md) | study.json、evidence.jsonl、目录结构 |
| [连接器](docs/connectors.md) | 四门审查、可用平台、被阻断路线 |
| [故障排查](docs/troubleshooting.md) | 安装、版本、门禁、MCP 常见问题 |

Agent 入口：[llms.txt](llms.txt)（发现索引）、[AGENTS.md](AGENTS.md)（仓库约定）、[SKILL.md](skills/user-demand-research/SKILL.md)（判断协议）。

## 仓库结构

```text
skills/user-demand-research/   Skill（判断）+ references（协议）+ assets（模板/注册表）
  scripts/sure.py              确定性 CLI（audit/plan/check/signals/report/…）
  scripts/sure_mcp.py          MCP stdio 服务器
  scripts/connectors/          第一方采集/清洗工具箱
  scripts/stages/              第一方打标/建库/审计工具箱
examples/sample-study/         离线合成样例
docs/                          人类向文档
tests/                         CLI 与 MCP 测试
```

## License

MIT。第三方组件与数据权利边界见 [LICENSE](LICENSE) 与 [docs/connectors.md](docs/connectors.md)。

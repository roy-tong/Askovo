# 快速开始

## 环境

- Python 3.9+
- 无需第三方依赖（核心 CLI 与 MCP 都是标准库）
- 平台采集需要对应 API 的访问资格，见 [连接器](connectors.md)

## 安装

### CLI

当前版本从源码安装（PyPI 包尚未发布）：

```bash
git clone https://github.com/roy-tong/user-demand-research.git
cd user-demand-research
pipx install --editable .
sure --version
```

或使用 venv：

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip setuptools wheel
.venv/bin/pip install -e .
.venv/bin/sure demo
```

> macOS 自带 Python 3.9 的 pip 是 21.2，直接 `pip install -e .` 会失败；先升级 pip。

### Agent Skill

```bash
bash scripts/install-skill.sh                 # 默认 ~/.agents/skills
bash scripts/install-skill.sh ~/.codex/skills
```

### MCP

```bash
sure mcp
```

客户端配置：

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

## 第一步：跑 demo

```bash
sure demo
```

它复制内置合成样例到临时目录，跑完整审计。预期：

```text
SURE 审计：synthetic-mobile-pet-check — pass
- 记录 7 条；重复率 0.0%；主导来源 42.9%
- 判断 1 条：可支持 1、超出证据 0、未定 0
```

不联网、不采集、不调用模型。它只证明运行时可用，不证明样例里的需求真实存在。

## 第二步：审计现有材料

前提：材料已经按 [数据契约](data-contract.md) 整理成 study 目录。

```bash
sure audit ./my-study
```

输出：

```text
05-audit/audit.json   机器可读：checks、signals、每条 claim 的 verdict
05-audit/audit.md     一页结论：能支持什么、缺什么、下一步
```

只看一条：

```bash
sure audit ./my-study --claim "付费意愿"
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 门禁通过，且没有超出证据的判断 |
| 1 | 门禁未过，或存在 `validated` 但证据不足的判断 |
| 2 | 用法错误（目录、参数、claim 不匹配） |

## 第三步：规划一个新研究

```bash
sure plan ./my-study \
  --goal "AI 眼镜在海外社媒的用户不满与替代方案" \
  --region overseas \
  --sample-size 100000 \
  --platform-types forum,social,video
```

产出：

- `study.json`：决策、范围、假设、质量门槛、连接器配置
- `01-sources/feasibility.json`：每个平台的可行性、配额、准入前提
- `01-sources/tasks.md`：采集任务清单
- `01-sources/*-routes.csv`：平台路线模板

若没有任何可用平台，退出码 `3`，并列出缺口。不要换成登录态或商业接口。

## 完整研究

```text
plan → 补全 design 契约 → check --stage design
     → 采集并写 manifest → check --stage evidence
     → signals → 写 demand-judgments → check --stage decision
     → report
```

每一步的产物与门槛见 [数据契约](data-contract.md) 和 [三种模式](modes.md)。

## 下一步

- 不知道选哪种用法：[三种模式](modes.md)
- 看不懂门禁报错：[故障排查](troubleshooting.md)
- 要让 Agent 跑：[SKILL.md](../skills/user-demand-research/SKILL.md)

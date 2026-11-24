<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/Askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><a href="README.md">English</a> | <b>简体中文</b></p>

# Askovo

**好产品，先从真实证据开始。**

Askovo 帮产品团队汇集用户与市场证据、检验需求假设，再决定做什么、不做什么。它在现有 Agent 工作流上补上研究执行、来源追踪、反证和需求验证记录。

[官网](https://roy-tong.github.io/Askovo/) · [反证重放](https://roy-tong.github.io/Askovo/examples/decision-replay.html) · [快速开始](docs/quickstart.md) · [产品推理方法](docs/product-reasoning.md)

[![CI](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## 通用 Agent 会推理，Askovo 把真实证据带进研究

一份漂亮的研究答案，价值取决于背后的材料。Askovo 帮团队走出已有上下文，继续获得和检验新证据：

- **采集真实材料**：汇集社区反馈、访谈材料、竞品记录和授权导出，保留来源与采集历史。
- **检验需求假设**：区分概念反馈、原型反馈、付费意愿表达和真实行为；模拟用户不能成为需求证据。
- **比较支持与反证**：把原文引用、替代解释和覆盖缺口放在候选方向旁边。
- **推进并复审决定**：形成 Decision Brief 和下一验证，新证据到来时继续复审同一个决定。

| 通用 Agent | Askovo |
| --- | --- |
| 帮助设计研究、分析已有材料、起草建议 | 增加采集、证据血缘、需求验证记录和决定状态 |
| 能根据当前上下文生成合理答案 | 让支持、反例和未知项跟着受影响的主张走 |
| 能为不同读者改写报告 | 从同一条研究链投影 Decision Brief、业务方案、MRD、PRD 和 BRD |

## 你可以做出什么

| 交付物 | 帮团队完成什么 |
|---|---|
| Decision Brief | 对齐建议、支持依据、反例和下一动作 |
| 业务方案 | 串起目标场景、用户需求、产品形态和走向市场的路径 |
| 需求研究报告 | 先读业务结论、需求变化、产品/商业影响和下一步；证据与技术细节放入附录 |
| 决策包 | 比较机会、选项、代价和最值得先做的验证 |
| MRD / PRD / BRD | 给市场、需求与商业读者各自适用的工作视图 |
| 决策重放 | 回看新证据如何改变早先的建议 |

所有交付物来自同一条推理链：**场景 → 用户 → 痛点 → 需求 → 特性 → 产品 → 商业**。不同读者看到不同视图，不需要再对几版结论。

## 不再手改研究数据

研究合同、链级字段、商业节点、需求判断和角色工作台都有正式写接口。CSV 导入识别 `记录编号 / 内容 / 证据等级 / 来源 / 采集时间`；同一正文不会重复计数，同编号不同正文会在写入前拒绝整批。

```bash
askovo chain STUDY set --field context_key --value-json '"after_sales_saas"'
askovo study STUDY set --field decision.owner --value-json '"周航"'
askovo evidence STUDY retract R01 --by "赵敏" --reason "纠正误导入记录"
askovo evidence STUDY restore R01 --by "赵敏"
askovo case list
```

撤销保留原文，但不再参与分析、需求判断或审计；恢复同样保留原文。E3 纠错必须提供有效概念测试。BRD 会投影最新 DecisionRecord，不代表执行或商业验收已完成。详见 [CLI 参考](docs/cli.md)。

所有外部平台通过 `.askovo/account-quotas.json` 持久记录账号身份、等级和可选的 `collect` 日上限。直接采集、轮转和队列跨进程、跨对话共用这份策略；发帖额度不会冒充采集额度，未知等级和限额保持未知。详见 [平台与连接器](docs/connectors.md)。

## 运行产品推理样例

```bash
pipx install askovo
askovo demo
askovo do "要不要为小团队重做新手引导？" --domain software --dry-run
```

离线合成样例展示了 Askovo 如何组织研究、关联证据，并把一个问题变成可讨论的产品判断。[看一条反证如何改变决定](https://roy-tong.github.io/Askovo/examples/decision-replay.html)。

## 为真实研究执行而设计

1. **定义决定**：从有投入代价的选择开始，而不是泛泛地做一份调研。
2. **采集与导入**：使用社区反馈、访谈材料、竞品记录、授权导出，以及概念或原型反馈。
3. **带着来源分析**：定量与语义分析都要回到原始材料和反例。
4. **验证并决定**：区分口头兴趣、付费意愿和真实行为；负责人确定下一步，并随证据变化复审。

可以直接使用 CLI，也可以把 Askovo 作为 Agent Skill 接入工作流，或通过 MCP 调用同一套行为。采集、分析、访谈和证据分级为产品判断服务，不代替判断。

```bash
# 安装 Agent Skill
bash scripts/install-skill.sh

# CLI 与 MCP 共用同一引擎
askovo decision --help
askovo mcp
```

## 继续探索

- [快速开始](docs/quickstart.md)
- [产品与商业推理](docs/product-reasoning.md)
- [Decision Brief](docs/decision-brief.md)
- [岗位与行业方法](docs/product-methodology.md)
- [平台与连接器](docs/connectors.md)
- [CLI 参考](docs/cli.md)
- [Agent Skill](skills/askovo/SKILL.md) · [llms.txt](llms.txt) · [AGENTS.md](AGENTS.md)

Askovo 以 MIT 开源。通过[任务页](https://roy-tong.github.io/Askovo/first-look.html)带来一个产品决定，或在 [GitHub](https://github.com/roy-tong/Askovo/issues) 提交可复现问题。

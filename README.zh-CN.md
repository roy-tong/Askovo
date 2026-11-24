<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/Askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><a href="README.md">English</a> | <b>简体中文</b></p>

# Askovo

**让好产品，从定量推演中长出来**

Askovo 为产品定义和决策做充分的定量研究，自动采集并分析用户与市场数据，再把场景、用户、痛点和需求逐步推演为合理的产品定义判断。它让团队看清为什么做、为谁做、做什么，让数据驱动的产品判断成为每个团队的日常。

[官网](https://roy-tong.github.io/Askovo/) · [反证重放](https://roy-tong.github.io/Askovo/examples/decision-replay.html) · [快速开始](docs/quickstart.md) · [产品推理方法](docs/product-reasoning.md)

[![CI](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## 从一堆材料和争论，到一个有依据的产品定义

产品讨论很容易变成职位、音量或报告厚度的比赛。Askovo 用自动采集、定量分析和逐层推演，把研究直接连接到产品定义：

- **看见机会**：把场景、用户、痛点和需求连起来，不从一条功能请求直接跳到方案。
- **比较选项**：把支持证据、反例和取舍放在候选方向旁边。
- **推进决定**：形成 Decision Brief、业务方案和具体的验证清单。
- **持续学习**：新材料到来时复审同一个决定，看清建议为什么改变。
- **模型扩大召回，但不替你做结论**：可选 `analyze --semantic` 的每条候选都挂原文引用和未知项，先过反例复核，再由具名人工决定是否进入证据路径；MCP 不能代替人工 accept/reject。

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

## 运行产品推理样例

```bash
pipx install askovo
askovo demo
askovo do "要不要为小团队重做新手引导？" --domain software --dry-run
```

离线合成样例展示了 Askovo 如何组织研究、关联证据，并把一个问题变成可讨论的产品判断。[看一条反证如何改变决定](https://roy-tong.github.io/Askovo/examples/decision-replay.html)。

## 为真实产品工作而设计

1. **定义决定**：从有投入代价的选择开始，而不是泛泛地做一份调研。
2. **带上已有材料**：文档、访谈、授权导出和社区讨论都能进入研究。
3. **找到最弱一环**：先补最可能改变决定的证据。
4. **选择并复审**：负责人确定下一步，新材料继续推动同一个决定。

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

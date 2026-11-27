<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/Askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><a href="README.md">English</a> | <b>简体中文</b></p>

# Askovo

**发现那些你原本不知道的真实需求。**

Askovo 是一项 AI Native 研究服务，面向需要做产品决定的团队。带来一个产品想法、一项待验证假设或一个已上线产品。你的 Agent 可以借助 Askovo 找到真实用户与市场证据、检验需求，并在证据变化时重新复审决定。

[OVO 统一官网](https://roy-tong.github.io/ovo/) · [决定重放](https://roy-tong.github.io/Askovo/examples/decision-replay.html) · [快速开始](docs/quickstart.md) · [当前能力](docs/feature-status.md)

[![CI](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## 通用 Agent 能设计研究，Askovo 带回真实证据

当模型已经拥有足够上下文，生成一个看似合理的答案并不昂贵。真正昂贵的是找到不同意见的用户、人们已经在用的替代方案、与产品宣讲相矛盾的行为，以及那个应该改变研发顺序的结果。

Askovo 为你正在使用的 Agent 提供一套研究服务：来源追踪、反证、验证记录和可持续复审的决定状态。

### 三种研究服务

| 服务 | 最小输入 | 业务交付 |
| --- | --- | --- |
| **Opportunity Research** | 一个行业、技术或产品想法 | 真实用户问题、现有替代方案、反证，以及有实证基础的机会判断 |
| **Demand Validation** | 一项需求假设或产品概念 | 参与者筛选、本地实验契约、概念/原型观察和明确的验证结果 |
| **Product Intelligence** | 一个已上线产品 | 持续研究 Watch、增量证据，以及不断变化的用户、竞品和需求图景 |

第一项服务创造第一次惊喜：**“我发现了原本不知道的重要问题。”** 第二项帮助真实决定，第三项让决定随证据持续更新。

## 目标不是生成更好看的报告

一个好的首次结果，会改变团队接下来做什么：

- **发现未知。** 真实用户讨论和替代方案，让原始 brief 里没有的问题浮出来。
- **检验假设。** 概念、原型、日记和价格敏感记录，始终与真实支付和市场普遍性分开。
- **改变或维持决定。** Decision Brief 把支持、反例和未知项放在建议旁边。
- **再次复审。** 新证据触发有边界的复审，而不是悄悄改写旧结论。

一个真实研究项目分析了 **8 个社区、24 个月内的 109,429 条去重评论**。它把产品顺序从“先做专用硬件”改为“先验证软件和导出”。这是便利样本，不是用户数，也不是市场份额估算。[查看研究方法](docs/product-reasoning.md)。

## 让 Agent 自由组合能力，而不是再学一套工作流

由宿主 Agent 决定研究路径，Askovo 提供可组合能力和保护研究质量的约束：

1. **定义有投入代价的决定。** 从真实产品选择开始，而不是泛泛地“做一份研究”。
2. **取得缺失材料。** 采集公开内容，或导入已授权的客户反馈、访谈和产品记录。
3. **主动寻找反证。** 让每个候选方向都保留原文、替代解释和覆盖缺口。
4. **证据不足时继续验证。** 按需使用参与者筛选和本地实验运行时；公开招募和部署需要单独授权的外部服务。
5. **交付并复审。** 生成 Decision Brief，记录负责人的选择，在新证据到来时重新打开决定。

CLI、Agent Skill 和 MCP 共用同一研究引擎。既可以使用高阶决定入口，也可以把采集、分析、实验和证据导出作为原子能力自由组合。

## 运行离线样例

```bash
# 稳定版
<!--OVO:askovo-stable-->pipx install askovo==2.25.2
askovo demo<!--/OVO:askovo-stable-->
# 预发行验收版
<!--OVO:askovo-preview-->pipx install askovo==2.25.2
askovo demo<!--/OVO:askovo-preview-->
askovo do "要不要为小团队重做新手引导？" --domain software --dry-run
```

这个合成样例展示一项研究如何变成可复核的产品判断。[看看一条反证如何改变决定](https://roy-tong.github.io/Askovo/examples/decision-replay.html)。

处理一项完整决定任务：

```bash
askovo decide start --input task.json
askovo decide status TASK_ID
askovo decide brief TASK_ID --format md
```

外部采集需要来源授权。候选生成与人工语义复核保持分离，模拟用户永远不会成为需求证据。

## 已经证明什么，下一步验证什么

- **当前可用：** 研究采集与导入、证据溯源、反证复核、Decision Brief、参与者筛选、本地问卷/落地页/原型/日记实验、研究 Watch 和 Proof 导出。
- **下一步验证：** 真实参与者招募、公网实验托管、更多产品事件数据源，以及由宿主 Agent 主导的持续研究。
- **仍待用户证明：** 外部用户独立完成首次任务、同一负责人进行第二次决定复审，以及持续的外部采用。

实现边界见[功能状态](docs/feature-status.md)。本地实验或结构检查通过，不代表已经完成招募、需求证明或产品验收。

## 继续了解

- [快速开始](docs/quickstart.md)
- [需求验证指南](https://roy-tong.github.io/Askovo/guides/need-validation.html)
- [产品与商业推理](docs/product-reasoning.md)
- [Decision Brief](docs/decision-brief.md)
- [平台与连接器](docs/connectors.md)
- [CLI 参考](docs/cli.md)
- [Agent Skill](skills/askovo/SKILL.md) · [llms.txt](llms.txt) · [AGENTS.md](AGENTS.md)

Askovo 以 MIT 协议开源。通过[任务页](https://roy-tong.github.io/Askovo/first-look.html)带来一项有投入代价的产品决定，或在 [GitHub](https://github.com/roy-tong/Askovo/issues) 提交可复现的问题。

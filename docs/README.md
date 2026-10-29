# SURE 文档

SURE 有三层：**判断**（Skill）、**确定性操作**（CLI）、**集成**（MCP）。同一套证据模型，三种使用方式。

第一次来，按这个顺序读：

1. [快速开始](quickstart.md) —— 装好，跑 demo，审计一个 study。
2. [核心概念](concepts.md) —— E0–E5、证据角色、什么算 `validated`。
3. [三种模式](modes.md) —— 你该用 Quick Audit、Design 还是 Full Study。
4. [CLI 参考](cli.md) —— 命令、参数、退出码。
5. [数据契约](data-contract.md) —— study.json 与 evidence.jsonl 长什么样。
6. [连接器](connectors.md) —— 哪些平台能用，为什么有些被阻断。
7. [故障排查](troubleshooting.md) —— 装不上、门禁不过、MCP 连不上。

| 你想做什么 | 去哪 |
| --- | --- |
| 让 Agent 按协议跑研究 | [../skills/user-demand-research/SKILL.md](../skills/user-demand-research/SKILL.md) |
| 看某个平台的具体规则 | [../skills/user-demand-research/references/](../skills/user-demand-research/references/) |
| 给 Agent 做发现入口 | [../llms.txt](../llms.txt) |

## 一句话原则

> 记录数不是用户数；便利样本不能推断总体；门禁通过不等于结论为真。

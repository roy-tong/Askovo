# SURE 引擎

**askovo 是对外产品；SURE 是底层研究引擎。**

## SURE 是什么

SURE = **Structured User Research with Evidence**。

它不是一个独立安装的产品，也不是第二个 CLI。它是 `askovo` 背后的研究逻辑层：

- 判断产品领域、生命周期阶段、研究意图与风险；
- 从 32 个方法中选出“能回答当前问题、且证据形式匹配”的方法；
- 定义六类结论（need / acceptance / usability / performance / commercial / safety）各自能证明什么、不能证明什么；
- 约束证据形式、证据等级、反幸存者偏差、停止规则与安全门；
- 决定“记录数不是用户数”“便利样本不能推断总体”等边界。

## askovo 是什么

askovo 是用户看到的产品层：

- 一条命令 `askovo "<需求>"`；
- CLI、Skill、MCP 三个入口共用同一套行为；
- 平台雷达、采集、分析、队列、CDP、交付物；
- 把 SURE 的研究判断变成产品经理/用户研究员可以直接使用的交付。

## 代码位置

```text
skills/askovo/scripts/sure_engine.py   # SURE 研究引擎
skills/askovo/scripts/askovo.py        # askovo CLI 入口
skills/askovo/scripts/askovo_mcp.py    # askovo MCP 外壳
```

不要为 SURE 单独安装、单独起服务或 fork 一套协议。`askovo` 的 CLI/Skill/MCP 都调用同一个 `sure_engine.py`；这样研究判断不会在三个入口之间漂移。

## 一句话

> **askovo 负责“让研究可用”，SURE 负责“让研究可信”。**

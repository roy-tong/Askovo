# 开源集成清单（复核：2026-11-01）

这里记录「采用成熟组件」的实际决策与状态，避免把「规划过」当成「已集成」，也避免为了清单数字去 fork 大型项目。

原则：**能作为可选依赖或外部服务使用，就不 fork；不能验证的集成不写进能力清单。** 核心 CLI/Skill/MCP 仍然只用标准库。

## 当前状态

| 组件 | 规划用途 | 状态 | 形态 | 说明 |
| --- | --- | --- | --- | --- |
| Docling | 本地 PDF/Office 文档解析 | 已接入（可选） | 可选依赖 | `askovo document` / `askovo_document` 输出 Markdown 与 SHA-256 来源哈希；未安装时明确报错，不降级成猜测 |
| invoice2data | 供应商发票字段提取 | 已接入（可选） | 可选依赖 | `verovo invoice-intake` 产出未复核草稿；不自动入账、不推断税/退款/FX |
| Playwright | 浏览器操作 | 已使用（Growovo） | 既有依赖 | Growovo 通过 CDP 连接真实 Chrome；不接管登录、不保存凭据 |
| Stagehand | 语义 UI 恢复 | 未集成；保留接口 | 外部 provider | Growovo `workflow` 的 locator 阶梯支持语义定位；视觉恢复需要操作者提供 provider，否则以 `visual_unavailable` 停止 |
| Midscene | 视觉操作恢复 | 未集成；保留接口 | 外部 provider | 同上；不内置视觉模型，不猜点击坐标 |
| Open Deep Research | 自主深度研究循环 | 未集成 | — | Askovo 用确定性缺口检测 + 信封授权实现编排；语义判断仍由人或宿主 Agent 完成 |
| Crawl4AI / Scrapy | 高质量/规模化网页采集 | 未集成 | — | 现有 github/reddit 适配器与授权导出已覆盖当前场景；新增采集需要独立评审 |
| LangGraph | 多阶段编排 | 未集成 | — | 编排状态在 `research_loop.py` 中以显式状态机实现，避免引入运行时依赖 |
| DuckDB | 本地复杂分析 | 未集成 | — | 当前分析在标准库内完成；数据量证明需要时再评估 |
| OpenLIT | Agent 观测接入 | 未集成 | — | Verovo 已有自有 trace/usage 适配；通用观测接入未形成端到端闭环 |
| Prefect | 持续任务与调度 | 未集成 | — | Growovo 用持久化排期 + 显式 tick 实现，可由 cron/launchd 调用；不引入调度服务 |

## 本轮新增的集成边界

- **Askovo**：研究闭环只复用现有连接器与授权导出，不新增采集框架；Docling 仍是唯一文档适配器。
- **Growovo**：`core/locators.py` 定义视觉 provider 回调接口，Stagehand/Midscene 可作为外部实现接入；仓库不内置、不冒充已集成。
- **Verovo**：period intake 复用 invoice2data 草稿；不做 FX/税务推断，不引入 DuckDB 或外部数据仓库。

## 何时才 fork

只有当上游组件无法以依赖/服务方式满足本仓库的安全边界（例如必须改写授权、审计或数据保留逻辑）时才考虑 fork；届时需要：固定 commit、记录许可证与来源、补集成测试、在 feature-status 中单独标注。当前没有这类需求。

## 复核方式

```bash
# 可选适配器缺失时的行为
askovo document missing.pdf --out out.md          # 明确报错，不产出假内容
verovo invoice-intake --file invoice.pdf --json x.json   # 未安装 invoice2data 时报错

# 语义恢复与视觉边界
python3 mkt.py workflow replay <id> --cdp-url http://127.0.0.1:9222   # dry-run 解析定位器
```

集成状态以 `docs/feature-status.md` 与各仓库 README 为准；本文件只解释取舍，不替代能力声明。

# 连接器

SURE 只把**可审计、可修改的 GitHub 开源项目**纳入连接器清单。不接商业调研 SaaS，不把商家后台 API 当第三方市场研究方案。

## 四门审查

选一个连接器要依次通过四道检查：

| # | 检查 | 问题 | 不通过的后果 |
| --- | --- | --- | --- |
| 1 | 代码许可 | 能否修改、分发、商用？ | 不能作为第一方工具 |
| 2 | 平台准入 | 采集方式是否被平台允许？ | 路线阻断 |
| 3 | 数据权利 | 数据能否按研究目的保存、使用？ | 只能历史/受限使用 |
| 4 | 研究资格 | 输出能否支撑判断、能否审计？ | 不能作为证据来源 |

**MIT 只回答第一题。** 代码许可证不等于平台访问许可，也不等于数据使用许可。

## 当前清单

截至 2026-08-27：

| 平台 | 开源项目 | 状态 | 使用边界 |
| --- | --- | --- | --- |
| Reddit | [PRAW](https://github.com/praw-dev/praw) | `supported` | 只走获准的 Reddit Data API；现有应用需完成 2026-09-30 登记，新申请走审批；复核用途、速率、保留与删除 |
| X | [Tweepy](https://github.com/tweepy/tweepy) | `supported` | 只走官方 X API；API 层级必须覆盖检索窗口与规模 |
| YouTube | [Google API Python Client](https://github.com/googleapis/google-api-python-client) | `supported` | 只走 YouTube Data API；记录配额、刷新与删除规则 |
| Amazon | [AmazonReviews2023](https://github.com/hyp1231/AmazonReviews2023) | `historical_only` | 只能研究截至 2023-09 的历史评论；代码许可与数据使用权分开复核 |

## 被阻断的路线（保留为负面审查）

- X：`snscrape`、`twikit`
- YouTube：免 API 的评论/字幕抓取器
- 京东：陈旧评论爬虫
- 淘宝/天猫：依赖扫码登录的 Playwright 爬虫
- Kickstarter：由爬虫生成且已停止更新的数据仓库

保留它们的原因：避免其他 Agent 再次搜索后误判为可用方案。

目前没有可作为默认能力的 Amazon 实时评论、京东、淘宝/天猫、Kickstarter 第三方开源连接器。CLI 会让这些路线保持失败或阻断状态，**不会悄悄换成商业服务、卖家接口、登录态、内部接口或浏览器自动化**。

## 查看清单

```bash
sure connectors
sure connectors --platform x --include-blocked
```

输出是 JSON，包含每个连接器的 `decision`、`license`、`reviewed_revision`、`access_basis`、`limits` 与 `prerequisites`。

## 采集清单（manifest）

每次采集都要在 `01-sources/manifests/` 写一份清单，至少包含：

- `collection_run_id`
- `connector_id` 与固定 `connector_revision`
- `connector_license`
- `access_basis`
- `data_rights_basis` 与 `retention_rule`
- 检索路线 / 查询
- `requested` / `reached` / `written` 数量
- 配额、警告、停止原因

平台证据还要保留 `collection_run_id`、`connector_id`、`connector_revision`，`check` 会核对它们与 `study.json` 是否一致。

## 政策观察

Reddit 的 2026 公共 Data API 过渡会改变研究访问方式：现有应用要在 2026-09-30 前登记，新自助访问关闭，长期方向是 Devvit。注册表里给这条记录加了 `recheck_by`，到期需要重新审查。

## 为什么不做“更多平台”

平台数量不是护城河，**可审计的准入判断**才是。一个被正确阻断的平台，比一个能跑但违反条款的采集器更有产品价值。

详细规则见：

- [开源连接器审查](../skills/user-demand-research/references/open-source-connectors.md)
- [连接器输出合同](../skills/user-demand-research/references/connector-contract.md)
- 平台细则：[Reddit](../skills/user-demand-research/references/reddit-research.md) · [X](../skills/user-demand-research/references/x-research.md) · [YouTube](../skills/user-demand-research/references/youtube-research.md) · [Amazon](../skills/user-demand-research/references/amazon-research.md) · [京东](../skills/user-demand-research/references/jd-research.md) · [淘宝](../skills/user-demand-research/references/taobao-research.md) · [Kickstarter](../skills/user-demand-research/references/kickstarter-research.md)

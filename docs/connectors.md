# 平台与连接器

askovo 先判断**数据在哪个平台、能不能合规拿到、拿到后能证明什么**，再谈采集。

## 平台雷达

```bash
askovo platforms "家用摄像头夜间告警的用户抱怨" --domain hardware --bulk
```

内置 23 类平台/来源：GitHub、Reddit、X、YouTube、Instagram、TikTok、Amazon、App Store、Google Play、Hacker News、Stack Overflow、Bilibili、微博、知乎、小红书、京东、淘宝、Kickstarter，以及访谈、问卷、工单、遥测、实验室报告。

每个平台记录：

| 字段 | 含义 |
|---|---|
| `access_modes` | official_api / authorized_export / historical_dataset / first_party / research_api / licensed_provider |
| `auth` | none / token / oauth / partner / consent |
| `bulk` | yes / limited / no |
| `decision` | supported / limited / blocked |
| `limits` / `bias` | 已知限制与选择偏差 |
| `adapter` | 是否有内置适配器 |

**三档含义**：

- `supported`：有官方 API、第一方数据或合规历史数据集；
- `limited`：需要授权、研究资格、合作方或历史数据，批量能力有限；
- `blocked`：没有合规批量通道；askovo 只接受授权导出或人工整理，不做未授权抓取。

### 当前内置采集适配器

| 平台 | 通道 | 环境变量 |
|---|---|---|
| GitHub | 官方 Search API | `GITHUB_TOKEN`（可选，提高限额） |
| Reddit | 官方 Data API | `ASKOVO_REDDIT_CLIENT_ID` / `ASKOVO_REDDIT_CLIENT_SECRET` / `ASKOVO_REDDIT_USER_AGENT` |
| 本地 fixture/授权导出 | JSONL/CSV | — |

其他平台（Instagram、Amazon、X、TikTok、App Store 等）当前没有内置批量适配器，`collect` 会返回 `3` 并给出导入/授权导出路径。原因不是“技术做不到”，而是没有合规的通用批量接口。

### 特殊平台说明

- **Instagram**：没有通用公开内容批量 API；只接受授权创作者/企业导出或符合资格的研究 API；不做抓取。
- **Amazon**：官方评论/商品接口按合作伙伴/卖家权限开放；优先 Amazon Reviews 2023 历史数据集或授权导出。
- **X / TikTok / LinkedIn**：官方 API 有付费层级、研究资格或合作方限制。
- **小红书 / 知乎 / 京东 / 淘宝 / Kickstarter**：当前标记为 blocked；只接受授权导出，不提供绕过方式。

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
askovo connectors
askovo connectors --platform x --include-blocked
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

- [开源连接器审查](../skills/askovo/references/open-source-connectors.md)
- [连接器输出合同](../skills/askovo/references/connector-contract.md)
- 平台细则：[Reddit](../skills/askovo/references/reddit-research.md) · [X](../skills/askovo/references/x-research.md) · [YouTube](../skills/askovo/references/youtube-research.md) · [Amazon](../skills/askovo/references/amazon-research.md) · [京东](../skills/askovo/references/jd-research.md) · [淘宝](../skills/askovo/references/taobao-research.md) · [Kickstarter](../skills/askovo/references/kickstarter-research.md)

## 规模化采集

“大量”不等于一次请求拉全量。生产上按查询、时间窗、子版块/仓库/频道分片，多次运行，靠 `record_id` 与文本 hash 跨 run 去重：

- GitHub Search 单查询最多约 1,000 条；按 `created:` 日期、repo、label 分片。
- Reddit listing 单次约 1,000 条；按 subreddit、时间窗、关键词分片。
- 每次分片独立写 manifest，记录查询、配额、时间窗、达到上限与停止原因。
- 跨 run 的重复记录在 `normalized.jsonl` 按 `record_id` 去重。
- 先小样 pilot，估算有效产出、重复率与边际新主题，再放量；不要用“条数”替代代表性。

当前 CLI 是单进程、配额受限的采集器；大规模并行需要外部 worker/队列，askovo 负责计划、manifest、去重与证据口径，不把并发伪装成研究质量。

## CDP 受限传输层

对于没有通用批量 API、但你可以用本人浏览器合法查看的页面，提供 CDP（Chrome DevTools Protocol）传输：

```bash
askovo collect ./study --platform amazon --query "night alert" \
  --cdp-url http://127.0.0.1:9222 \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms
```

边界：

- 只抓当前页面**可见文本**，不读取登录凭据、不导出 Cookie；
- 命中验证码/机器人检查立即 `challenge` 停止，不绕过；
- 不伪造指纹、不用代理池、不做无限翻页；
- `--ack-terms` 必须由人确认平台条款、账号授权、数据用途与保留；
- 当前开放：amazon、instagram、x、youtube、bilibili、weibo；blocked 平台（小红书/知乎/京东/淘宝/Kickstarter）仍不开放；
- 平台条款可能仍然禁止自动化采集；askovo 只提供技术通道和留痕，不替用户承担合规判断。

适配器与传输是两回事：GitHub/Reddit 走官方 API；Amazon/Instagram 等优先授权导出/历史数据集，CDP 是受限兜底；本地 fixture 永远可用（授权导出）。

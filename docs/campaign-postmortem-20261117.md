# 2026-11 高尔夫采集战役复盘（问题 → 策略）

这份文档是一次真实会话（约 1,150 条消息、
≈32.3 万条清洗后语料）的复盘记录。它回答三个问题：**当时撞到了什么、根因是什么、
最后哪条做法真正有效**，以及这条经验现在沉淀在注册表/手册的哪个位置。

机器可读的版本是 [`../skills/askovo/assets/platform-field-notes.json`](../skills/askovo/assets/platform-field-notes.json)；
操作手册是 [`../skills/askovo/references/cdp-collection-playbook.md`](../skills/askovo/references/cdp-collection-playbook.md)。
本文只做战役级索引，**不产生第二套规则**：条目内容以注册表和手册为准。

> 实战笔记不是许可。能否采集仍由平台目录、study scope、Design gate、人工 ack 与获批
> URL 决定；挑战页只被动等待或人工完成，身份/代理永不轮换，会员墙不绕过。

## 一、风控与会话

| 现场问题 | 根因 | 有效解法 | 沉淀位置 |
|---|---|---|---|
| Discord 一天内四次掉登录态 | 三次都紧跟在一次 timeout/abort 之后继续驱动；第四次在最后一次操作约 40 分钟后、期间零浏览器接触，来自延迟执法或长时间挂起的会话 | 超时=熔断：≥15 分钟不碰平台、不诊断、不重试；一 cell 一次 goto、预算 ≤60%、禁 `reload()`；邀请页与频道采集分段；会话 30–40 分钟后主动登出 | 笔记 `discord-session-drop-anti-automation`；运行时 `runtime_policies.discord`；策略 `session-health-cooldown`、`cell-budget-headroom` |
| 掉线前还在“快速导航但没超时”的对照时段从未掉线 | 触发因子不是单纯快，而是“超时撕裂输入流后继续操作” | 把超时当停止信号，先落盘再退出；不把重试当恢复 | 手册反自动化复盘；`SessionGuard` |
| Discord 论坛频道每次选择器结果不同 | 页面视图/滚动状态不稳；侧栏 h3 与卡片 h3 混在一起 | 用 `[role=button]` 卡片容器、跳过 `#channels` 侧栏；正文在 `div[class*="messageContent"]` | 笔记 `discord-forum-card-list` |
| 论坛频道采到 0 条但页面有内容 | GRAB 脚本抛错被静默吞掉 | 先 dump 一张卡片原始 HTML、隔离脚本错误，再判断页面是否为空 | 笔记 `generic-silent-extractor-failure` |
| 盲扫频道效率低、高价值 help/竞品频道靠后 | 频道名只在侧栏 DOM 中，规则/欢迎/空频道消耗 cell | 侧栏快照一次拿真名（`--list-channels`），按名字排序后点名采；空房间记为“空”，不是抓取失败 | 笔记 `discord-channel-name-targeting` |
| 加入 4 万人服务器后看不到历史 | 会员验证墙：加入 ≠ 可读；服务器技术上私有 | 记录 `membership_gated`（服务器 id、人数、门槛类型），换开放社区或授权导出；不尝试角色/机器人/冒充 | 笔记 `discord-membership-gated-history`；策略 `join-is-not-access`（runtime，`detect_membership_gate`） |
| 官方邀请链接失效、邀请页弹回 | 邀请会腐烂；官方社区可能是 Facebook 群 | 从自己的语料 grep `discord.gg/`，按频次与语境验证；接受后确认侧栏出现该服务器 | 笔记 `discord-invite-rot` |
| X/IG 单页加载慢，2 帖/格必超时 | 慢页面把 cell 预算吃满 | 慢页面严格 1 页/cell；2 帖/cell 只在每帖独立落盘时使用；超时的 cell 轮转而不是原地重试 | 策略 `cell-budget-headroom`；手册数据管线节 |

## 二、平台通道

| 现场问题 | 根因 | 有效解法 | 沉淀位置 |
|---|---|---|---|
| Discord 内部 API 调不通 | 自动化沙箱没有 localStorage，内部接口不可用 | 走 DOM + 用户手工登录会话；接受较慢路径 | 笔记 `discord-internal-api-sandboxed` |
| `scrollTop=0` 后历史不加载 | 程序化赋值不产生输入事件流 | CDP `Input.dispatchMouseEvent` 真实滚轮，滚前先 `mouseMoved` | 笔记 `discord-programmatic-scroll-ignored`；`wheel_scroll` |
| Discord tab 绑定失效、URL 模式对不上 | 重定向/邀请页切换后 URL 变化 | 每次重新列 tab、按稳定 id 重绑；导航→校验→采集放同一 cell | 笔记 `generic-tab-binding-rot`；`rebind_tab` |
| IG 主页采两帖就超时，队列不动 | 主页是最慢的表面 | 用 `/explore/search/keyword/?q=` 建队列（每查询 3–8 帖），1–2 帖/cell 且每帖独立落盘；主页只做发现 | 笔记 `instagram-keyword-page-over-profile` |
| 同一查询韩语几十帖、日英只有几帖 | 不是“语言薄”，是“词不好”；`ゴルフスイング` 同语言 42 帖 | 先换更好的词，再判断 locale 缺口；按 term × locale 建队列，标签 URL 只作后备 | 笔记 `instagram-locale-keyword-grid`；策略 `multilingual-routing` |
| IG 评论选择器找不到 | 评论行是无 class 的 DIV | 从 `time` 向上爬祖先链（第 5 层），不要按 class 找 | 笔记 `instagram-comment-ancestor-chain` |
| Reel 页 caption 为空 | 帖子页选择器不适用于 reel | 用 `og:description` 兜底并剥掉尾部 likes 片段 | 笔记 `instagram-reel-caption-fallback` |
| X 搜索无限滚动停住 | 没有真实输入事件 | 真实滚轮 + `since:/until:` 季度窗；一页/cell；回复串密度低，降为穿插任务 | 笔记 `x-search-infinite-scroll-stall`、`x-reply-thread-density`；策略 `windowed-search` |
| X 时间窗思路在别的平台不成立 | 各平台时间检索能力不同 | X 支持 since/until；Discord 靠频道历史滚动；YouTube 无原生时间窗（按主题分层+近似时间）；IG 无公开时间检索 | 策略 `windowed-search`；手册平台怪癖 |
| yt-dlp 被 PO token 拦截 | 播放器侧检测 | 改走 innertube `search`/`next`/continuation，免登录；评论在 `commentEntityPayload` | 笔记 `youtube-ytdlp-po-token-block`、`youtube-comment-entity-payload` |
| YouTube 相对时间无法精确 | 返回 “10 months ago” | 解析为近似 UTC 并标 `date_precision=approximate` | 笔记 `youtube-relative-timestamps` |
| Kickstarter 直连 403、评论需 JS | Cloudflare + JS 渲染 | CDP 可见页、被动等 Cloudflare 自动清除、循环 load-more、按 `&reply=` 区分回复 | 笔记 `kickstarter-*` 三条 |
| GolfWRX 403、MyGolfSpy 空白 | Cloudflare 拦脚本；MyGolfSpy/Invision 在 IAB 里渲染空白 | GolfWRX 走 CDP vB5 并升级为已验证；MyGolfSpy 记为不支持的栈，换同垂类 | 笔记 `vertical-forum-cloudflare`、`vertical-forum-iab-blank-render` |
| vB5 版块列表混入别的版块帖 | 侧栏 “latest posts” 链接被当成版块线程 | 只从主内容容器取链接，按 canonical href 去重并打 section id | 笔记 `vertical-forum-sidebar-crosslinks` |
| App Store RSS 拉不到评论 | Apple 已下线该 RSS；XML 变体也一样 | 不规划 RSS；剩余通道是浏览器可见页的 in-page comments API，先验证再承诺量 | 笔记 `app-store-rss-retired` |
| PullPush 也限流 | 商用墙；双归档通道同时堵死 | 不把 PullPush 当备份；保留单 arctic 客户端+退避，把量转到浏览器可见论坛 | 笔记 `reddit-pullpush-commercial-wall`；策略 `backup-channel-pivot` |
| 归档同一 IP 两个客户端互相拖死 | 双客户端放大 422、共享配额 | 一 provider 一 writer；ps 杀重复进程；把配额让给高产 lane | 笔记 `reddit-archive-client-contention`；策略 `single-writer-quota` |

## 三、数据管线与运行纪律

| 现场问题 | 根因 | 有效解法 | 沉淀位置 |
|---|---|---|---|
| 画像作者数骤降、字段全空 | `clean_merge` 位置参数错位，`author_hash` 被丢 | 按字段名转换；保留一条 golden 原始记录并断言身份/时间/URL 字段存活；0% 非空率先当 bug | 笔记 `generic-normalized-field-loss`；策略 `field-preservation` |
| Amazon 评论 0/16,226 有日期 | 初次扫描没带 timestamp；后续把有效的 Unix 毫秒当字符串切年份 | 时间戳按数值解析，不切字符串；先核对原始 dump 的字段类型 | 手册数据管线节；`field-preservation` |
| 器材目标“缺口”有一大块是假的 | Rapsodo/FlightScope 5,863 条不在任何 goal bucket | 原始→去重→清洗→分类逐文件对账；某来源贡献 0 就是覆盖缺口 | 策略 `classification-coverage`；`goal-counter-dedupe` |
| 修复版清洗“没生效” | 旧 clean4 还在写同一个 `master.jsonl`，覆盖了 clean5 | 单写者规则同样适用于派生输出；确认旧进程死掉、用受管单实例、不留 nohup 残留 | 笔记 `generic-single-writer-state`；策略 `single-writer-quota` |
| 后台任务看起来启动了却不对 | `cmd & tail …` 把 `cd` 也后台化，日志/状态路径错 | 绝对路径 + `ps` 验证；一条命令一个受管后台作业 | 手册爬虫工程规则 |
| 浏览器流水线“变慢” | 浏览器 lane 由 agent 回合驱动，回合结束就停；后台归档仍在跑 | 不把浏览器 lane 当常驻吞吐；按回合恢复流水线；比较速率时区分 lane 类型 | 手册并行 lane 节 |
| 目标验收数字来回跳 | 名义、去重、清洗、分类四种口径混用 | 同时公布四种计数；验收只用清洗后分类总数 | 策略 `goal-counter-dedupe`、`classification-coverage` |

## 四、经验怎么继续进入产品

1. 新限制/解法先补 `platform-field-notes.json`（一条限制一条笔记，`artifact`/`helper` 必须可解析）；
2. 能写成不变量、且跨平台复用的，进入 `strategies` 并声明 `enforcement: runtime | operator`；
3. runtime 策略必须绑定可解析的守卫（`askovo doctor` 的 `cdp-runtime-policies` 会拦）；
4. 数字型预算（间隔、会话上限、超时冷却、goto 上限、留头系数）进入 `runtime_policies`，由
   `connectors/cdp_strategy.py` 执行，不在脚本里再写一份；
5. 只属于一次战役的数据结论（价格带、竞品情绪）留在研究项目，不进产品规则。

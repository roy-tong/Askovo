# 平台实战笔记（限制与解法）

多平台采集战役（2026-11，≈110k 条）反复撞到同一批平台限制，而每条限制最后都找到了能走通的通道。这份经验现在是一个**机器可读的注册表**：
[`../skills/askovo/assets/platform-field-notes.json`](../skills/askovo/assets/platform-field-notes.json)。

规划、`askovo doctor`、平台雷达和各类投影都读同一份数据，经验不会漂到目录旁边的一份散文文档里。

**实战笔记不是许可。** 能否采集仍由平台目录（`access_modes` / `decision` / `cdp` / `bulk`）、study 的 `scope.allowed_sources`、adapter 开关、Design gate、人工 `--ack-terms` 与批准的可见页面共同决定。笔记只记录「现场发生了什么、哪条通道走通了」，**不会**把 blocked 路线变成可采集，也不授权任何挑战页绕过或凭据捷径。

## 注册表字段

| 字段 | 必填 | 含义 |
|---|---|---|
| `id` | 是 | 稳定笔记 id（`<平台>-<限制>`），全局唯一 |
| `platform` | 是 | 平台目录 id、声明的 `source_types` 键，或 `*`（跨平台实践） |
| `channel` | 是 | 笔记对应的通道（`arctic_shift_archive_api` / `cdp_visible_page` / `cdp_user_session` / `multi_channel` …） |
| `restriction` | 是 | 一句话说清平台限制 |
| `symptom` | 是 | 命中时操作者看到什么 |
| `detector` | 否 | 如何确认是这条限制而不是脚本 bug |
| `solution` | 是 | 现场验证过的解法（有界、被动、如实停） |
| `artifact` | 是 | 实现该解法的仓库相对路径 |
| `helper` | 否 | 编码该机制的 `skills/askovo/scripts/` 下 `module.attr` |
| `verification` | 是 | `{status, date, evidence}`；status 取自验证等级，evidence 必须是真跑过的东西 |
| `cdp` | 是 | 是否 CDP 通道；对目录平台必须与目录的 `cdp` 一致 |

## 验证等级

| 等级 | 含义 |
|---|---|
| `verified` | 现场端到端跑通且跑到了量 |
| `partially_verified` | 通道可用、提取已开始，但这一轮没跑完 |
| `login_verified` | 登录/会话可用，采集尚未开始 |
| `channel_verified` | 页面能在该通道渲染，采集尚未执行 |

没有对应运行记录就不要升级等级。X / Instagram / TikTok 的方法目前就是「部分验证 / 仅登录验证」，**故意不写采集器**，这是诚实标注而不是缺口掩盖。

## 引擎怎么用

```bash
# 雷达推荐平台的已知坑
askovo platforms "Discord 社区和 Kickstarter 众筹评论里的用户抱怨" --field-notes

# 单平台完整表（目录平台或 source type，如 vertical_forum）
askovo platforms "Kickstarter 众筹评论" --platform kickstarter --field-notes

# 机器可读：每个推荐条目带 field_notes，顶层另有 field_notes
askovo platforms "Kickstarter 众筹评论" --json

# 注册表一致性门（必填字段、产物路径、helper 引用、cdp ⇔ 目录）
askovo doctor
```

`platform_fit` 会把推荐平台的笔记（含跨平台实践）挂到每个条目上；`platform_markdown` 渲染「已知平台限制与解法」段；`askovo doctor` 在产物路径腐烂、helper 引用失效或 `cdp` 与目录矛盾时直接失败。

## 运行时守卫

注册表指向的代码就是可复用能力本身：

| 助手 | 实现 |
|---|---|
| `connectors.common.classify_backoff` | 429/403 按重置头等待、422「slow down」指数重试、永久状态硬停 |
| `connectors.common.single_writer_state` | state 文件独占 pid 锁（活进程阻断、僵尸锁回收） |
| `connectors.common.parse_relative_time` | 「10 months ago」「3小时前」「2일 전」「5 分前」→ 近似 UTC + `date_precision` |
| `connectors.common.atomic_write_json` | 每轮同目录临时文件落盘（未落盘的一轮就是丢掉的一轮） |
| `connectors.cdp_runtime.wait_for_challenge_clear` | 被动轮询挑战页；需要交互即硬停 |
| `connectors.cdp_runtime.wheel_scroll` | 先 mouseMoved 再真实 `Input.dispatchMouseEvent` 滚轮 |
| `connectors.cdp_runtime.rebind_tab` | 每次重新列 tab、按稳定 id 重绑（URL 模式会腐烂） |
| `connectors.cdp_runtime.bounded_load_more` | 有界批量点击展开，直到列表不再增长 |
| `connectors.cdp_runtime.run_lanes` | 并行通道、失败隔离、单站点单 tab |
| `connectors.rotation.RotationScheduler` | 多平台轮转：每站点最小间隔、分类冷却、会话门、日配额与断点续跑 |
| `connectors.cdp_strategy.SessionGuard` | 单平台会话守卫：一 cell 一次 goto、超时熔断、会话限时、模式互斥、会话日志 |
| `connectors.cdp_strategy.classify_page` | 挑战页 / 404 / 空渲染 / 正常内容四态判定，capture、collect 与采集器共用 |
| `connectors.cdp_strategy.effective_budget` | 按策略的留头系数折算 cell 预算 |
| `connectors.cdp_strategy.classify_failure` | 超时→熔断、挑战/掉线→人工、其余→停止 |

离线自检：`python3 skills/askovo/scripts/connectors/cdp_runtime.py --selftest`、
`python3 skills/askovo/scripts/connectors/cdp_strategy.py --selftest`。

## 多平台轮转策略

限制是「单平台」的，而最值钱的经验往往是「怎么组合平台让**每个站点感知到的频率都不升高**」。这些策略放在同一注册表的 `strategies` 段，每条都带显式 `invariant`（不能破的约束）和强制它的运行时助手：

| 策略 | 平台 | 不变量 | 机制 | 验证 |
|---|---|---|---|---|
| **Platform rotation (one round per platform, then switch)** (`platform-rotation`) | * | Per-site request cadence never rises. Total throughput comes from overlapping different sites, never from hammering one. | Run one round per platform, then switch. Each site only sees its own tab's sequential requests, so its observed interval stays flat while another site's render wait is overlapped (field: Instagram ×1 ∥ GolfWRX ×2 per cell). | verified（2026-11-17） |
| **One tab per site (the frequency invariant)** (`per-site-frequency-invariant`) | * | A site must never see two tabs' worth of requests. Two tabs on one site double its rate — that is risk-control pressure, not parallelism. | Assign each lane a distinct site; the lane runner rejects duplicate site keys. Spend the scarce logged-in browser across different sites, not within one. | verified（2026-11-17） |
| **One writer per provider or output, hand quota to the higher-yield lane** (`single-writer-quota`) | reddit | One client per provider, state file and derived output. A duplicate client multiplies 422 storms; a duplicate cleaning job silently overwrites the better output. | ps → kill duplicates → resume the survivor from its state file → only then judge provider load. Pause the low-yield lane to hand the quota to the high-yield one (field: golf-main paused so equipment keywords got the whole archive quota). The same discipline applies to local cleaning/merge jobs: one managed instance, no nohup residue, and never start a fixed version while the old one is still writing. | verified（2026-11-17） |
| **Pivot channels, never identities** (`backup-channel-pivot`) | reddit, vertical_forum | No account, proxy, key or identity rotation: a blocked channel is recorded as a gap and the run switches to another authorized channel. | PullPush commercial wall → stop planning it as a backup; keep a single arctic client with backoff, and move volume to a browser-visible forum channel in the same vertical (GolfWRX). | verified（2026-11-17） |
| **Windowed search (time buckets instead of deep pagination)** (`windowed-search`) | x | No scroll past the stall and no request-rate ramp: history is rebuilt by time windows, deduped by post id across windows. | Drive the logged-in search page with since:/until: half-year windows; collect each window with real wheel events; dedupe by status id and keep the window tag for traceability (field: 7 windows back to 2023, ~25–30 mentions each). Time-window sampling is platform-specific: X supports since/until, Discord exposes channel history by scrolling, YouTube has no native time window (layer queries by topic and keep approximate timestamps), and Instagram has no public time search (per-post only). | verified（2026-11-17） |
| **Session health, cooldown, human re-login** (`session-health-cooldown`) | discord, x, instagram, tiktok | A dropped session is re-authenticated by the human, never by the agent; the platform cools down before any retry, and other platforms keep working meanwhile. An idle-open session is not a standing channel. | Detect the drop → put the platform in cooldown (default 30 min) → human re-login → re-verify → resume. Rotate to another platform while one cools down; never rapid re-auth. Time-box the stretch and log out deliberately; on Instagram the cost of a mistake is account-level (24–72 h action block), so the conservative cadence is the price, not a tuning parameter. | verified（2026-11-17） |
| **Batch auto-relay (no idle quota gap)** (`batch-auto-relay`) | reddit, youtube | The next batch starts when the current process exits; state files checkpoint every batch; goal counting stays nominal + deduped so a relay never inflates the target. | Queue batches, chain them on process exit, keep one state file per route, and recompute the goal counter across files after each batch. | verified（2026-11-17） |
| **Multilingual query routes (word choice before locale conclusions)** (`multilingual-routing`) | youtube, x, instagram | Locale coverage is measured per query route. Word choice dominates language: a thin query is not a thin locale, and an English-biased corpus is never inferred from one term's yield. | Issue the same scene/equipment queries in each target language, tag routes per locale (yt-equip-kr / yt-equip-jp), and report yield per locale. Before recording a locale gap, retry with a better term: generic Japanese returned ~3 posts while ゴルフスイング returned 42 — the same language, a different word. | verified（2026-11-17） |
| **Blank-render triage (200 + empty body is not a challenge)** (`blank-render-triage`) | vertical_forum | 200 + empty innerText = unsupported stack; never 'fix' it with more automation or a different identity. | Probe body innerText length and title; if both are empty after a render wait, mark the stack unsupported and pivot to another forum in the same vertical (GolfWRX vBulletin5 rendered; MyGolfSpy/Invision stayed blank). | channel_verified（2026-11-17） |
| **Cell budget headroom** (`cell-budget-headroom`) | * | A timeout must never tear an input event stream mid-dispatch — that signature reads as automation. | Leave ~30% headroom on every cell budget, prefer collecting less, and persist after each round; a torn cell is a stop signal, not a retry signal. On slow surfaces (X search, IG profile) run one page per cell; two posts per cell only when each post persists independently; rotate a timed-out cell instead of retrying it in place. | verified（2026-11-17） |
| **Nominal vs deduped goal counting** (`goal-counter-dedupe`) | * | Acceptance uses the deduped count; nominal counts stay visible only as a running estimate. | Recompute the counter across all output files after each batch: nominal per file, deduped total by record id, and per-route/locale breakdown so a thin route cannot hide behind a fat one. Reconcile raw → deduped → cleaned → classified totals and per-bucket shares; an unclassified source family is a coverage gap, not zero. | verified（2026-11-17） |
| **Join is not access (membership walls are recorded gaps)** (`join-is-not-access`) | discord | A joinable room whose history is gated is a recorded gap. The agent never attempts verification roles, bots, impersonation or member-status farming to unlock it. | After joining, probe one high-value channel for history. If the pane is empty or shows a verification gate, record membership_gated with the server id, member count and gate type, then pivot to an open community or an authorized export. Joining is a read attempt, not a permission. | verified（2026-11-17） |
| **Classified totals reconcile with raw files** (`classification-coverage`) | * | Every raw file maps into a bucket; an unclassified file is a coverage gap, not zero. Acceptance uses the cleaned, classified total. | Recompute raw rows → deduped → cleaned → bucket shares per file; flag any source family contributing 0 and any bucket that moves after a classifier fix. Publish nominal, deduped and cleaned counts together so a missing family cannot hide behind a fat bucket. | verified（2026-11-17） |
| **Normalization preserves identity, time and URL** (`field-preservation`) | * | A normalized record keeps the fields downstream analysis joins on. A 0% non-empty rate on identity/time/url is a pipeline bug, not a source gap. | Convert by named field, keep one golden raw record and assert its key fields survive, and print non-empty rates per critical field before any analysis. `askovo analyze` now publishes `field_completeness` and `zero_rate_fields`; a 0% rate is a pipeline bug until proven otherwise. Re-run the analysis after the fix; never patch the derived result. | verified（2026-11-17） |

引擎面：

```bash
askovo platforms "<需求>" --strategies   # 推荐平台的轮转策略
askovo platforms "<需求>" --json         # 计划和每个条目都带 strategies[]
```

`platform_fit` 把适用策略（含跨平台实践）挂到计划与每个推荐条目；`askovo doctor` 做策略段门禁（必填字段、平台 id、产物、helper 引用、验证等级）。调度器本身可 import：`connectors/rotation.py`（`RotationScheduler`、`--selftest`、`--plan`）。

策略仍是**经验不是许可**：轮转降低的是每个站点观察到的频率，不绕过平台限制、挑战页或登录墙，身份/代理永不轮换。

## 运行时策略（可执行的那部分）

每条策略现在声明 `enforcement: runtime | operator`。`runtime` 的编译成注册表 `runtime_policies` 里按平台给出的预算；`operator` 的（时间窗搜索、批次接力、多语言路由、换通道、去重计数、分类覆盖、字段保真）是规划决策，循环无法强制。注册表同时把每条 runtime 策略绑到执行它的守卫上，数据和代码无法悄悄漂移：

```bash
askovo platforms "<需求>" --policies       # 每个平台实际执行的预算
askovo platforms "<需求>" --json           # 每个 CDP 条目带 runtime_policy
askovo doctor                              # cdp-runtime-policies 门禁
```

| 预算 | 默认 | 现场来源 |
|---|---|---|
| `cadence_seconds` | 3（Discord 20） | 每站点最小间隔 |
| `session_minutes` | 60（Discord 40、X 45） | 登录态会话限时，到点人工登出 |
| `timeout_cooldown_minutes` | 15 | 超时=熔断，不诊断、不重试 |
| `session_cooldown_minutes` | 30 | 掉线后等人工重登 |
| `max_gotos_per_cell` | 1 | 导航→校验→采集同一 cell；`reload()` 禁止 |
| `budget_fraction` | 0.7（登录态平台 0.6） | cell 预算留头；撕裂的输入流是停止信号 |
| `exclusive_modes` | 按平台 | 邀请加入与频道抓取不共用一段会话 |

`connectors/rotation.py` 对注册表声明过的平台也读同一份预算（显式参数优先），纯归档路线保留原有现场表。`connectors/cdp_strategy.py` 执行这张表；`capture page`、`collect --cdp` 与两个 CDP 采集器都 import 它：空渲染（`blank_render`）不写候选、超时（`cdp_timeout`）返回冷却时间而不重试、掉线只由人工重登；同一层用 `detect_membership_gate` 识别会员验证墙，**加入 ≠ 可读**，记为覆盖缺口而不是绕过。策略约束的是「怎么碰」，**不授权访问**。

## 战役复盘

一次完整采集战役（约 1,150 轮、≈32.3 万条清洗后语料）的问题、根因、有效解法与沉淀位置，见
[2026-11 采集战役复盘](campaign-postmortem-20261117.md)。本文只做索引，不产生第二套规则。

## 平台索引

平台、笔记数与主要产物见英文方法文档
[`../skills/askovo/references/platform-field-notes.md`](../skills/askovo/references/platform-field-notes.md)，
它是同一注册表的渲染结果，不产生第二份结论。

## 覆盖边界

只记录这场战役实际跑过的通道。目录里既有的 CDP 条目（amazon / bilibili / weibo）早于本战役，**没有**对应笔记；「没有笔记」既不代表通道可用，也不代表不可用——需要时先补一次真跑，再添笔记。

## 怎么加一条笔记

1. 先真跑一次——笔记必须来自实际运行，不能是推测；
2. 一条限制一条笔记；通用的工程纪律放 `*` 笔记；
3. `artifact` 写仓库相对路径、`helper` 写编码该机制的函数（两者都会被校验）；
4. `cdp` 必须与平台目录一致，不一致 `askovo doctor` 会失败；
5. `verification.status`/`evidence` 如实记录，没跑完就写部分验证；
6. 更新 `generated_at`，然后跑 `askovo doctor` 与全量测试。

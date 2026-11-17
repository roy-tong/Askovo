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

离线自检：`python3 skills/askovo/scripts/connectors/cdp_runtime.py --selftest`。

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

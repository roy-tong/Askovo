# connectors/ — 从研究项目收编的采集与清洗工具箱

本目录是一组**第一方**（本仓库自己的 MIT 许可证下）采集/清洗脚本，从多个已完成需求研究项目里收编，做项目无关化后集中维护。它们和 [`assets/open-source-connectors.json`](../../assets/open-source-connectors.json) 里登记的**第三方开源连接器**是两层东西：注册表回答"哪些外部项目允许作为采集机制"，本目录提供"研究项目里反复长出来的自用工具"。

约束：仅标准库（`collect_amazon_reviews_2023.py` 除外，见下），兼容 Python 3.9–3.12；所有平台文本按不可信数据处理。

## 目录一览

| 文件 | 收编自 | 一句话 |
| --- | --- | --- |
| `collect_legacy_reddit.py` | 脑机接口调研（两代实现合并） | 社区×月×子窗口的 legacy 公开归档采集：分片、退避、断点续采 |
| `common.py` | Tiiny 用户研究 + 高尔夫调研（运行时守卫） | 共享助手：schema 规范化、质量分、匿名化哈希、JSONL IO；运行时守卫 `classify_backoff` / `single_writer_state` / `parse_relative_time` / `atomic_write_json` |
| `cdp_runtime.py` | 高尔夫智能设备调研（CDP 方法，2026-11） | CDP 操作助手：被动挑战等待、真实滚轮事件、tab 重绑、有界 load-more、并行通道（含 `--selftest` 离线自检） |
| `rotation.py` | 高尔夫智能设备调研（多平台轮转，2026-11） | 多平台轮转调度器：每站点最小间隔、429/422 分类冷却、会话门（人工重登）、日配额、断点续跑；`--plan`/`--selftest` |
| `cdp_strategy.py` | 高尔夫智能设备调研（2026-11-17 四次 Discord 掉线复盘） | CDP 运行时策略：注册表 `runtime_policies` → `RuntimePolicy`/`SessionGuard`；一 cell 一次 goto、`reload()` 禁止、超时熔断、会话限时、模式互斥、页面四态判定、会话日志（`--selftest`/`--policy`） |
| `collect_arctic_reddit.py` | Tiiny 用户研究 | 同一归档端点的游标分页采集器（按时间窗倒序翻页到穷尽） |
| `collect_arctic_windows.py` | 高尔夫智能设备调研（deep_pull.py，2026-11） | Arctic Shift 显式窗口回填：窗口内 `after` 游标深翻页 + 每窗 cap + state 断点（≈3,900 窗实战验证） |
| `collect_youtube_innertube.py` | 高尔夫智能设备调研（expand-2026-11/youtube_pull.py） | YouTube innertube 免登录评论采集：search→next→continuation，兼容 2024+ commentEntityPayload；`created_at` 为相对时间近似（`date_precision=approximate`） |
| `collect_cdp_kickstarter.py` | 高尔夫智能设备调研（CDP 方法，2026-11） | Kickstarter 评论/更新帖 CDP 可见页采集：被动等 Cloudflare 自动清除、循环点"load more"展开、DOM 提取（见下文 CDP 采集器节） |
| `collect_cdp_discord.py` | 高尔夫智能设备调研（CDP 方法，2026-11） | Discord 频道/论坛消息 CDP 登录态采集：真实滚轮事件触发懒加载、慢速节奏、每轮持久化（见下文 CDP 采集器节） |
| `collect_hn.py` | Tiiny 用户研究（≈AI眼镜/泛具身，字节级相同） | Hacker News 公开 API 采集（Algolia 端点），2026-10 补收编 |
| `collect_pullpush_reddit.py` | Tiiny 用户研究（≈AI眼镜/泛具身，字节级相同） | PullPush Reddit 备用源采集器，2026-10 补收编 |
| `collect_amazon_reviews_2023.py` | Tiiny 用户研究 | HF 流式两遍法采集 Amazon Reviews 2023（元数据建 ASIN 白名单 → 评论过滤） |
| `amazon_reviews_2023_manifest.py` | Tiiny 用户研究 | HF tree API 拉数据集文件清单（路径/大小/oid），供下载前规划 |
| `range_download.py` | 脑机接口调研 | 并发 Range 分片下载器，可断点续传，适合 GB 级公开数据文件 |
| `clean_screen_corpus.py` | 脑机接口调研（三个脚本的模式抽取） | collect→screen→clean 通用阶段：PII 打码、去重、信封写出、state 断点、审计输出 |

源脚本最初**均未改动**地留在各自项目内；2026-10 清理时，`collect_arctic_reddit.py`/`collect_hn.py`/`collect_pullpush_reddit.py` 在项目侧的重复副本已删除（各项目 scripts/ 留有迁移指针），本目录是唯一上游。

---

## 1. `collect_legacy_reddit.py` — 合并了两代实现

### 来源与两代差异

| 代际 | 来源 | 特征 |
| --- | --- | --- |
| 第一代（pilot） | `projects/脑机接口调研/02-需求发现研究/scripts/collect_legacy_reddit_archive.py` | 每社区每月 1 次封顶请求；月份区间由 `--start/--end` 推导（`months()` 生成器）；无退避 |
| 第二代（deep） | 同目录 `collect_legacy_reddit_deep.py` | 每月切 `--windows` 个子窗口（修复 92% 样本落在每月最后 48 小时的月末偏差）；`--shard-idx/--shard-total` 路由分片并行；429/403 按 `X-RateLimit-Reset` 退避；**但年份区间硬编码 `range(2023, 2027)`，`--start` 形同虚设**；404 只拉黑单个月窗口（不存在的社区会对之后每个月窗都重复 404） |
| 第二代改进版 | `projects/脑机接口调研/04-场景语料验证/scripts/collect_legacy_reddit_deep.py` | 两处修复：① 404 抛 `_RouteNotFound`，整条路由写入 `route_id:*` 拉黑并立即持久化；② `--start` 真正生效（早于它的月份被跳过） |
| **本收编版** | 以上三者 | 以第二代 deep 为基座，合并两个改进，再把月份区间改回由 `--start/--end` 推导（替代硬编码年份，这是项目无关化的必要改动） |

### 合并进来的改进清单

1. **404 整路由拉黑**（来自 04-场景语料验证）：不存在的社区只付出一次 404，`route_id:*` 写入 state 并立即落盘，续跑也跳过。
2. **`--start` 过滤生效**（来自 04-场景语料验证）：月份序列从 `--start`/`--end` 推导，早于 `--start` 的整月跳过。
3. **state 统一用集合维护、落盘写排序数组**：消除原版 `state["blocked"]` 重复追加的小瑕疵（功能等价的清理）。

`--windows 1` 退化为第一代 pilot 行为（每月单请求）。

### 项目无关化改动

- `USER_AGENT`：原两代分别硬编码 `CodexConsumerBCIResearch/1.0` 与 `SportsWellnessSceneCorpus/1.0` → 改为必填 `--user-agent`（每个研究必须声明自己的身份）。
- `SALT`：原硬编码研究目录名（`02-需求发现研究` / `04-场景语料验证`）→ 可选 `--salt`；不提供时 `author_hash` 为 null（需要跨分片关联作者的研究必须传研究稳定的 salt）。
- `--start`/`--end`：原带项目默认值 → 改为必填。
- `--run-id`：原默认值是具体项目的 run 名 → 缺省时生成 UTC 时间戳 id；正式采集建议显式传入并写入 manifest。
- 路由 CSV：`route_id`/`subreddit`/`per_month_cap` 必需；`scene_cluster`/`corpus_role` 变为可选透传（存在才写入 `scene_seed`/`candidate_corpus_role`）。
- 新增可选 `--endpoint`（缺省 Arctic Shift 公开端点）与 `--connector-id`（写入信封，便于和 manifest 对账）。

### 用法

```bash
# 路由 CSV（utf-8-sig，兼容 Excel）：
#   route_id,corpus_role,scene_cluster,subreddit,per_month_cap
#   sw-sport-01,open_scene,S01,simracing,100
python3 collect_legacy_reddit.py \
  --routes routes.csv \
  --out 02-data/raw/legacy-reddit-run01.jsonl \
  --state 02-data/raw/legacy-reddit-run01.state.json \
  --start 2024-09-01 --end 2026-08-31 \
  --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
  --salt "my-stable-study-salt" \
  --run-id legacy-reddit-20260921-01 \
  --windows 4 --shard-idx 0 --shard-total 2
```

注意事项：

- **续跑时保持 `--windows` 不变**。state 键含窗口序号（`route:month:wN`），中途改窗口数会生成新键、旧子窗口被重采。
- 31 天月份按 `windows=4` 会切出 5 个子窗口（7+7+7+7+2 的余数窗）——与源实现一致，属预期行为。
- 429/403 先按重置头礼貌等待退避（默认预算 600s），预算耗尽**硬停**，绝不换身份绕过。

---

## 2. `common.py` + `collect_arctic_reddit.py` — schema/质量分最成熟的一族

### 来源

`projects/Tiiny用户研究/scripts/common.py` 与 `collect_arctic_reddit.py`。这一族的信封 schema 和质量打分（`quality_flags`/`quality_score`）是所有被收编家族里最成熟的，全部保留。

### 项目无关化改动（common.py）

| 原（Tiiny） | 收编版 |
| --- | --- |
| `ROOT`/`CONFIG_PATH`/`load_config()` 绑定项目内 `config/queries.json` | `load_json_config(path)` 显式传路径 |
| `USER_AGENT = "CodexTiinyUserResearch/0.1"` | `configure(user_agent=...)` 由采集器 CLI 传入 |
| `AUTHOR_SALT = "tiiny-public-feedback-v1"` | `configure(author_salt=...)`；未配置时不加盐（用户名本身是公开句柄，跨 run 关联需研究稳定 salt） |
| `PRIMARY_AFTER_UTC = 1704067200`（Tiiny 的主窗口 2024-01-01） | `configure(primary_after_utc=...)`；未配置时不打 `outside_primary_window` 标、`primary_sample_eligible` 恒真 |
| `TOPIC_TERMS`/`topic_relevance_score`/`infer_sample_bucket` | **删除**：本地 LLM 话题词表是 Tiiny 的领域词典，不是可复用规则 |

### 项目无关化改动（collect_arctic_reddit.py）

- 订阅列表与时间窗来自 `--config` JSON 或 `--subreddits` 参数（原从项目 `config/queries.json` 读）。
- `sample_bucket` 字段随词表一起删除；`source_role` 由 `--source-role` 传入（原硬编码 `"motivation"`）。
- 输出路径显式 `--out`（原相对项目根）。
- 新增可选 `--run-id` 写入 `collection_run_id`、`source_tier` 标注与 legacy 归档层一致。

### 与 `collect_legacy_reddit.py` 的分工

- `collect_legacy_reddit.py`：**显式路由 × 月份子窗口**，配合路由 CSV 做配额式覆盖（每窗有 `per_month_cap`）。
- `collect_arctic_reddit.py`：**时间窗内游标倒序翻页**（`before = min(created)-1`），把订阅区翻到穷尽或达到 `--max-records`，适合"这个小社区我全要"。

### 用法

```bash
python3 collect_arctic_reddit.py \
  --subreddits "SomeSub,AnotherSub" --after-utc 1704067200 \
  --max-records 5000 \
  --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
  --author-salt my-stable-salt \
  --run-id arctic-run-20260921-01 \
  --out 02-data/raw/arctic_comments.jsonl
```

### Hacker News / PullPush 显式配置

`collect_hn.py` 与 `collect_pullpush_reddit.py` 不再读取隐藏的项目配置，也不包含项目专用的 `infer_sample_bucket`。两者都要求 `--config` 与研究级 `--user-agent`，可选 `--author-salt` / `--primary-after-utc`：

```bash
cat > hn_cfg.json <<'JSON'
{"queries": ["camera motion alert"], "after_utc": 1704067200}
JSON
python3 collect_hn.py --config hn_cfg.json \
  --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
  --out 02-data/raw/hn_comments.jsonl

cat > pullpush_cfg.json <<'JSON'
{"queries": ["night alert"], "subreddits": ["smarthome"], "after_utc": 1704067200}
JSON
python3 collect_pullpush_reddit.py --config pullpush_cfg.json \
  --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
  --out 02-data/raw/pullpush_comments.jsonl
```

HN 使用 Algolia 公开 API；PullPush 是第三方 Reddit 归档，启用前仍需单独复核访问依据、数据权利、时效与删除边界。

---

## 3. Amazon Reviews 2023：两种获取方式

注册表已有 [`amazon-reviews-2023`](../../assets/open-source-connectors.json)（`historical_only`，截至 2023-09 的 McAuley-Lab 数据集）。这里收编的是两个获取器，不改变注册表对数据集本身的边界判断。

### `range_download.py`（整文件下载，来自脑机项目）

`projects/脑机接口调研/02-需求发现研究/scripts/range_download.py` **原样收编**（该脚本本就与项目无关），只加了可选 `--user-agent`。分片并行（`--parts`，默认 12）、每片落 `<output>.parts/NNN.part`、重跑跳过已完成分片、合并后校验总大小再原子改名。

```bash
# 先拿清单看文件大小：
python3 amazon_reviews_2023_manifest.py --out manifest.json
# 再按大小分片下载（例：5 GB 文件，24 片）：
python3 range_download.py \
  --url "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_category/xxx.jsonl.gz" \
  --output 02-data/raw/xxx.jsonl.gz \
  --size 5368709120 --parts 24 \
  --user-agent "MyStudyResearch/1.0"
```

### `collect_amazon_reviews_2023.py`（HF 流式过滤，来自 Tiiny）

`projects/Tiiny用户研究/scripts/collect_amazon_reviews_2023.py`。两遍法（元数据关键词 → ASIN 白名单 → 评论关键词过滤），全流式不落全量。数据集 id/类目/关键词从 `--config` JSON 传入；`--author-salt` 透传匿名化。安全边界：`trust_remote_code=False`，`dataset_revision` 必须是已审查的完整 40 位 HuggingFace commit SHA，元数据与评论两遍使用同一 revision；缺 ID 记录用规范化正文的 SHA-256 生成稳定 ID。**可选非标准库依赖：`pip install datasets`，核心 CLI 不需要它。**

```bash
cat > amazon_cfg.json <<'JSON'
{
  "dataset": "McAuley-Lab/Amazon-Reviews-2023",
  "dataset_revision": "0123456789abcdef0123456789abcdef01234567",
  "categories": ["Toys_and_Games", "Sports_and_Outdoors"],
  "product_keywords": ["eeg", "neurofeedback", "sleep headband"],
  "review_keywords": ["sleep", "focus", "training"]
}
JSON
python3 collect_amazon_reviews_2023.py --config amazon_cfg.json \
  --max-records 50000 --out 02-data/raw/amazon_filtered.jsonl
```

示例 SHA 仅展示格式，不是已审查版本；必须替换为你实际审查并锁定的数据集 commit。整文件下载也应把 `/resolve/main/` 换成 `/resolve/<reviewed-commit>/`，并用 manifest 的文件 `oid`/哈希复核。

### `amazon_reviews_2023_manifest.py`

原 Tiiny 版只针对固定数据集；收编版参数化了 `--dataset-id`（任意 HF 数据集 id）与 `--prefix` 过滤，并把 `dataset_id` 写进每行清单。通用价值：记录精确 `oid`（文件版本指纹），事后可证明当时消费的是哪个版本的文件。

---

## 4. `clean_screen_corpus.py` — collect→screen→clean 通用阶段

### 来源与抽取的模式

从脑机项目三个脚本抽取同一骨架：

| 源脚本 | 贡献的模式 |
| --- | --- |
| `02-需求发现研究/scripts/clean_amazon_health_history.py` | PII 打码（email/url/phone）；无 review_id 数据集的**稳定派生 id**（`asin|timestamp|text_hash` 的 sha256，不保留 user_id）；id 去重 → 文本哈希去重；audit JSON（counts/rejected/policy）；gz 输入 |
| `02-需求发现研究/scripts/clean_legacy_reddit_archive.py` | 追加 `u/`/`@` 句柄打码；"discovery-only、非证据表"的定位声明 |
| `02-需求发现研究/scripts/clean_legacy_reddit_candidates.py` | 保守多标签词表筛选；`screening_status=discovery_candidate_not_evidence`；标签计数审计 |

收编时新增（源脚本没有、但骨架需要）：**state.json 断点**（按输入行号续跑；跳过行只重算哈希进去重集合、不重复写出，所以跨断点边界的重复仍会被抓住；输出以追加模式续写）和可选 **gz 输出**。

### 用法

```bash
# 不筛选，纯清洗（Amazon Health 历史评论模式）：
python3 clean_screen_corpus.py \
  --input 02-data/raw/health.jsonl.gz --output 02-data/views/health-clean.jsonl \
  --audit 05-audit/health-clean-audit.json --state 02-data/raw/health-clean.state.json \
  --run-id amazon-health-clean-v1 --platform amazon_reviews_2023 \
  --source-family published_historical_dataset \
  --text-fields title,text --id-fields review_id --id-parts parent_asin,timestamp \
  --keep-fields rating,verified_purchase --channel-field category \
  --created-at-field timestamp --min-length 20 --redact email,url,phone

# 加词表筛选（Reddit 场景发现模式）：
python3 clean_screen_corpus.py \
  --input 02-data/raw/legacy-reddit-run01.jsonl \
  --output 02-data/views/reddit-candidates.jsonl \
  --audit 05-audit/reddit-screen-audit.json \
  --state 02-data/raw/reddit-screen.state.json \
  --run-id reddit-screen-v1 --platform reddit \
  --source-family legacy_reddit_archive \
  --text-fields text --id-fields source_record_id \
  --min-length 40 --redact email,url,phone,user \
  --lexicon scenes.json --screening-method scene_lexicon_v1
```

`scenes.json` 格式：`{"social_connection": ["\\b(social anx|make friends?)\\b"], ...}`（值为正则数组，多标签，命中任一即保留该标签）。

### 字段映射

- `--text-fields`：拼接为清洗文本（默认 `title,text`）。
- `--id-fields`：优先使用的稳定 id 字段链（默认 `review_id,id,source_record_id`）。
- `--id-parts`：全部 id 字段缺失时，用这些字段 + 文本哈希派生稳定 id。
- `--keep-fields`：透传进信封的原始字段（如 `rating`、`route_id`）。
- 信封固定字段：`collection_run_id`、`source_platform/family/record_id[/channel]`、`text`、`normalized_text_hash`、`source_tier`、`primary_sample_eligible=false`、`dataset_role`；筛选时另有 `screen_labels`/`screening_method`/`screening_status`。

---

## 4a. Arctic Shift 窗口回填（`collect_arctic_windows.py`）

与 `collect_arctic_reddit.py` 的分工：后者在**单个时间窗内**游标倒序翻到穷尽（"这个小社区我全要"）；本器走**显式窗口计划**（多社区 × 多月 × 每窗 cap），适合历史回填与配额式覆盖。窗口内用 `after=oldest-1` 游标深翻页（可超 100 条/请求上限），`fields` 裁剪响应；429/403 按 `X-RateLimit-Reset` 礼貌退避、422（归档侧"slow down"）指数重试，预算耗尽返回 None 如实停窗；state 断点（`completed/counts/errors`）+ 已写文件重建 seen，流式追加可中断续跑。

```bash
# windows.json: [{"sub":"golf","windows":[{"after":"2021-11-01","before":"2021-11-05","cap":100}],"max_per_window":80}, ...]
python3 collect_arctic_windows.py --config windows.json \
  --out 02-data/raw/backfill.jsonl --state 02-data/raw/backfill.state.json \
  --user-agent "MyStudyResearch/1.0 (+contact@example.com)" \
  --author-salt my-stable-salt --run-id backfill-20261117-01
```

**空窗诚实性**：某社区某历史窗口返回 0 通常是真的没数据（社区当年还没起来），不是脚本 bug——烧长计划前先交互验证一个窗。信封含 `route_id=deep:<sub>` 与 `source_query=window:<sub>:<ts>` 溯源。

---

## 4b. CDP 采集器（`collect_cdp_*.py`）

这一族与 HTTP 采集器不同：页面数据只在真浏览器渲染后存在（Cloudflare 拦直连、评论区 JS 渲染、SPA 懒加载），因此经 Chrome DevTools Protocol 驱动**用户自己可见的页面**。方法来自高尔夫调研 2026-11 的实战验证，完整通道决策树与坑清单见 [`../../references/cdp-collection-playbook.md`](../../references/cdp-collection-playbook.md)。

**复用引擎实现**：CDP 客户端（WebSocket 帧、回环校验、防重定向建页）importlib 复用 `../sure_engine.py` 的 `_WebSocket`/`CDPClient`/`cdp_new_page`——工具箱不复制传输层实现，引擎的安全语义免费继承。

**边界（与 capture/collect --cdp 同一套口径）**：

- **不做挑战绕过**：Kickstarter 的 Cloudflare 只等待被动自动清除（`--challenge-wait` 超时即硬停，提示人工完成后重跑）；永不解题、不伪造指纹。
- **登录会话仅用户手工操作**：Discord 由用户自己登录浏览器，采集器只开授权可见频道；不代输凭据、不读存储凭据、不导 cookie。
- **策略在运行时执行**：两个采集器都 import `cdp_strategy.py`，预算来自注册表 `runtime_policies`（不在脚本里各写一份）：一 cell 一次 goto、`reload()` 禁止、会话限时（Discord 40 分钟）、超时熔断（15 分钟）、模式互斥（messages/forum/invite、comments/posts）。**任何超时/中断都按熔断处理**（2026-11-17 四次 Discord 掉线：三次都在 timeout/abort 后继续驱动；同样快但无超时的导航从未掉线）。
- **先落盘再停**：超时/掉线/空渲染/404 时先持久化已采到的最好结果，再以退出码 2 停止；会话日志写到 `<out>.session.json`（`askovo.cdp-session/1`），下一次运行能看见上次试过什么。空渲染（200 + 空标题 + 空正文）不是挑战页、也不是空语料，直接换同垂类信源。
- **有界 + 慢速**：`--max-clicks`/`--max-rounds` 封顶；Discord 默认 2.5s/轮滚动 + 滚前模拟鼠标移动——高频导航与非人类匀速滚动会累积风险（实战教训，详见 playbook 的修正协议）。
- **每轮持久化**：展开/滚动每轮原子写盘（实战教训：未落盘的一轮就是丢掉的一轮）。
- **原始 JSON 落盘**：产物是平台保真快照（Kickstarter `{project,n,comments}`、Discord `{guild,server,channels,forums}`），转语料信封走 `clean_screen_corpus.py`（Kickstarter：`--text-fields text --id-fields 无，用派生`；Discord：`--text-fields text --id-fields id`）。
- **收编 ≠ 放行**（见第 6 节）：能否对某平台使用该通道由 `assets/platform-catalog.json` 的 `cdp: true` 与 study 的 scope/adapter 审查决定，工具存在不构成路线批准。

```bash
# Kickstarter 评论区（免登录；等 Cloudflare 被动清除 + load-more 展开）
python3 collect_cdp_kickstarter.py --cdp-url http://127.0.0.1:9222 \
  --url "https://www.kickstarter.com/projects/<creator>/<slug>/comments" \
  --out 02-data/raw/ks-<slug>.json
# Kickstarter 更新帖（逐帖慢速导航 8s）
python3 collect_cdp_kickstarter.py ... --mode posts --url ".../projects/<creator>/<slug>/posts"
# 先列频道名（不采集、不写空快照），再点名采高价值频道
python3 collect_cdp_discord.py --list-channels \
  --url "https://discord.com/channels/<guild>/<channel>"
# Discord 文字频道（用户已登录；一次一个频道，多频道慢速轮转）
python3 collect_cdp_discord.py --cdp-url http://127.0.0.1:9222 \
  --url "https://discord.com/channels/<guild>/<channel>" --server "Server Name" \
  --out 02-data/raw/discord-<server>.json
# Discord 论坛频道（feature-requests / bug-reports 帖子卡片）
python3 collect_cdp_discord.py ... --mode forum --url "https://discord.com/channels/<guild>/<forum>"
```

---

## 4c. 运行时守卫（`common.py` / `cdp_runtime.py`）

采集脚本最容易重复发明的不是抓取逻辑，而是**失败处理**。这两组助手把高尔夫战役里反复验证过的规则收敛成可导入的代码，新增采集器直接复用，不再各写一份：

| 助手 | 规则 | 现场来源 |
|---|---|---|
| `common.classify_backoff(status, headers, attempt)` | 429/403 优先按 `X-RateLimit-Reset`/`Retry-After` 等待；422「slow down」指数重试；400/401/404/410/451 硬停并记录缺失路线；5xx 指数重试 | Arctic Shift 窗口回填 |
| `common.single_writer_state(path)` | state 文件独占 pid 锁：活进程阻断（先 `ps` 确认再杀），僵尸锁回收 | golf-main 双进程互拖 |
| `common.parse_relative_time(text)` | 英/中/韩/日相对时间 → 近似 UTC，固定 `date_precision=approximate`；绝对日期与「2024年11月」这类不猜 | YouTube 相对时间 |
| `common.atomic_write_json(path, payload)` | 同目录临时文件落盘再替换；每轮/每 burst 持久化 | 掉会话前的最后一条 |
| `cdp_runtime.wait_for_challenge_clear(probe)` | 被动轮询挑战页：`clear` 继续、`challenge` 等、其它状态（需交互）立即硬停 | Kickstarter Cloudflare |
| `cdp_runtime.wheel_scroll(send)` | 先 `mouseMoved` 再 `Input.dispatchMouseEvent` 滚轮；程序化 `scrollTop` 不触发懒加载 | Discord 历史加载 |
| `cdp_runtime.rebind_tab(list_tabs, pattern)` | 每次重新列 tab、按稳定 id 重绑；URL 模式会腐烂 | 重连后的 tab 失效 |
| `cdp_runtime.bounded_load_more(click, count)` | 有界 burst 点击，直到行数不再增长/按钮消失，封顶总点击 | Kickstarter「load more」 |
| `cdp_runtime.run_lanes(lanes, site_of=…)` | 并行通道、失败隔离、单站点单 tab 守卫（同一站点两个 tab = 双倍频率） | 双标签流水线 |
| `cdp_strategy.policy_for(platform)` | 从注册表 `runtime_policies` 取该平台的运行时预算（间隔、会话上限、冷却、goto 上限、留头系数、互斥模式） | 四次 Discord 掉线复盘 |
| `cdp_strategy.SessionGuard` | 一 cell 一次 goto、`reload()` 禁止、超时熔断、会话限时、模式互斥、持久化会话日志 | Discord：timeout-then-continue 是掉线签名 |
| `cdp_strategy.classify_page` | 挑战页 / 404 / 空渲染 / 正常内容四态判定，capture、collect 与采集器共用 | MyGolfSpy 空渲染、Kickstarter 404 |
| `cdp_strategy.classify_failure` | 超时→熔断冷却、挑战/掉线→人工、其余→停止（保留已采结果） | 采集器停止协议 |

```bash
# 离线自检（无浏览器、无网络）
python3 cdp_runtime.py --selftest
python3 cdp_strategy.py --selftest
python3 cdp_strategy.py --policy discord   # 打印该平台实际执行的预算
```

边界与采集器一致：不绕过挑战页、不代输凭据、所有循环有界、每轮落盘。这些助手只编码**机制**；能否对某平台使用某通道仍由平台目录 + study scope 决定（见第 6 节）。平台限制与解法的机器可读版本见 [`../../references/platform-field-notes.md`](../../references/platform-field-notes.md)。

---

## 4d. 多平台轮转策略（`rotation.py`）

轮转不是并行技巧，而是**频率论证**：每个站点只能观测到自己的请求流，所以在站点之间交替会把每个站点观察到的频率压回来，而总吞吐不降（页面渲染等待重叠时反而上升）。

`RotationScheduler` 把不变量写成代码，采集器/调度器直接复用：

| 不变量 | 强制方式 |
|---|---|
| 每站点最小间隔 | `acquire()` 在 cadence 未到前抛 `PlatformCooling`；`wait=True` 才等待 |
| 单站点单 tab | `RotationScheduler` 拒绝重复平台；`cdp_runtime.run_lanes` 拒绝重复站点 |
| 分类冷却 | `record_error()` 走 `common.classify_backoff`：429/403 按重置头、422 指数退避、永久状态转人工 |
| 会话健康 | `record_session_drop()` 门禁平台；`record_human_relogin()` 由人工重登后恢复 |
| 日配额 | `daily_cap` 到顶后冷却到下一个 UTC 日 |
| 断点续跑 | `save()`/`load()` 序列化轮转状态，重启不会重打热平台 |

```bash
python3 rotation.py --plan discord,reddit,youtube   # 一轮的公平顺序
python3 rotation.py --selftest                      # 离线自检
```

CDP 平台的间隔与会话要求直接读注册表 `runtime_policies`（调用参数显式覆盖仍优先），Reddit/YouTube 的 API／归档路线保留下面这份现场表；它们也可按平台目录选择 CDP 可见页路线——调度器和采集器不会再对「同一个站点能多快碰」各说一套。

边界：轮转只降低每站点频率，不绕过平台限制、挑战页或登录墙；身份/代理永不轮换。策略与验证状态的机器可读版本见 [`../../references/platform-field-notes.md`](../../references/platform-field-notes.md#cross-platform-strategies)；每平台执行预算见 `cdp_strategy.py` 与 `askovo platforms "<需求>" --policies`。

---

## 5. 纪律与边界（全部脚本继承自源项目）

- **不登录、不轮换身份、不绕过限制**：429/403 走礼貌退避（等待重置头），预算耗尽硬停并留下部分计数；404 整路由拉黑。**唯一例外是 4b 节的 CDP 采集器**：登录由用户在浏览器里手工完成，采集器只消费用户已可见的页面，且永不绕过挑战页。
- **有界采集**：`per_month_cap`/`--target-records`/`--max-records` 封顶；`--full` 显式声明才放开。
- **层分离**：legacy 公开归档数据一律标 `source_tier=legacy_nonofficial_public_archive`、`primary_sample_eligible=false`，不与官方 API 数据混层；清洗产物是 discovery/screening 语料，**不是证据表**，进入证据需上下文编码。
- **隐私最小化**：作者/用户 id 只留加盐哈希；PII 类字符串打码；无 id 数据集用派生 id 而不保留 `user_id`。
- **可审计**：state.json 断点 + audit JSON（输入/写出/各类拒绝计数与 policy 声明）；正式运行请配合 `01-sources/manifests/` 的 manifest 模板记录 run 信息。

## 6. 为什么没有登记进 open-source-connectors.json

评估过，**schema 与语义都不合适，故只写本 README**：

1. 注册表条目以外部 GitHub 项目为对象：`upstream_repo` + 精确 `reviewed_revision`（commit 哈希）+ 其许可证与访问依据审查。本目录是第一方脚本，没有可 pin 的外部 revision（本仓库自身未 commit 前也没有哈希可言）。
2. `askovo.py` 的连接器校验会把 `supported`/`historical_only` 条目自动启用进 plan。其中 legacy Reddit 归档端点属于**非官方访问路径**，是否允许作为默认路线是四道审查要回答的政策问题——收编工具不等于通过审查，不应借登记悄悄放行。
3. Amazon Reviews 2023 数据集已有注册表条目（`amazon-reviews-2023`），收编的获取器只是同一 `historical_only` 数据集的另一种取数方式，另立条目会重复。

若未来要放开 legacy 归档路线，正确路径是：按 `references/open-source-connectors.md` 的四道审查评审该端点，pin 其上游 revision 与访问依据，再更新注册表与 `reviewed_at`（并按 AGENTS.md 加 CHANGELOG 行）——而不是从工具箱反向登记。

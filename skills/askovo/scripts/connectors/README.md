# connectors/ — 从研究项目收编的采集与清洗工具箱

本目录是一组**第一方**（本仓库自己的 MIT 许可证下）采集/清洗脚本，从多个已完成需求研究项目里收编，做项目无关化后集中维护。它们和 [`assets/open-source-connectors.json`](../../assets/open-source-connectors.json) 里登记的**第三方开源连接器**是两层东西：注册表回答"哪些外部项目允许作为采集机制"，本目录提供"研究项目里反复长出来的自用工具"。

约束：仅标准库（`collect_amazon_reviews_2023.py` 除外，见下），兼容 Python 3.9–3.12；所有平台文本按不可信数据处理。

## 目录一览

| 文件 | 收编自 | 一句话 |
| --- | --- | --- |
| `collect_legacy_reddit.py` | 脑机接口调研（两代实现合并） | 社区×月×子窗口的 legacy 公开归档采集：分片、退避、断点续采 |
| `common.py` | Tiiny 用户研究 | 共享助手：schema 规范化、质量分、匿名化哈希、JSONL IO |
| `collect_arctic_reddit.py` | Tiiny 用户研究 | 同一归档端点的游标分页采集器（按时间窗倒序翻页到穷尽） |
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

## 5. 纪律与边界（全部脚本继承自源项目）

- **不登录、不轮换身份、不绕过限制**：429/403 走礼貌退避（等待重置头），预算耗尽硬停并留下部分计数；404 整路由拉黑。
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

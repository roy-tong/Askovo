# stages/ — 从研究项目收编的打标 / 数据集构建 / 人工审计工具箱

本目录是**第一方**阶段（stage）工具，从四个已完成需求研究项目（Tiiny用户研究、AI眼镜用户研究、泛具身用户研究、灵泷视界/用户研究）的 `scripts/` 里收编，做项目无关化后集中维护。与 [`connectors/`](../connectors/README.md) 的分工：connectors 负责**采集与清洗**（collect → screen → clean），本目录负责**采集之后**的分析数据流水线（import → label → build → extract → export → 人工审计）。

约束：仅标准库、兼容 Python 3.9–3.12；**唯一例外是 `audit_workbook.py` 的 xlsx 读写需要 `pip install openpyxl`**（其 CSV 出入口不依赖任何第三方库）。所有平台文本按不可信数据处理。

## 目录一览

| 文件 | 收编自 | 一句话 |
| --- | --- | --- |
| `common.py` | 灵泷视界 common.py 为底，合并 AI眼镜 / Tiiny(=泛具身) 改进 | 共享助手：JSONL(gz) IO、文本清洗、质量分、CJK 感知词边界匹配、`Taxonomy` 配置类 |
| `import_feedback_export.py` | AI眼镜 ≡ 灵泷视界（两份字节级相同） | 外部反馈导出（CSV/JSON/JSONL）→ raw 记录契约：别名映射、日期归一、派生 id、匿名化 |
| `label_feedback.py` | 灵泷/AI眼镜 结构为底 + Tiiny 规则表思路 | 规则打标：按 taxonomy 维度多标签 + summary.json 计数 |
| `build_primary_dataset.py` | AI眼镜 版为底 + Tiiny 骨架 | 主数据集：去重、质量/相关性过滤、对照桶、月度逆频权重 |
| `build_month_balanced_dataset.py` | 灵泷视界 版为底 | 月平衡分析视图：月/平台×月/来源族×月 三层封顶的种子下采样 |
| `extract_candidate_signals.py` | 灵泷 文本清洗 + 泛具身 排序法 | 开放词表信号：代码噪声剥离、CJK n-gram、按线程/平台/月支持度排序 + 判别性过滤 |
| `export_metadata_detail.py` | 灵泷视界 版为底 | 数据集 → 元数据明细 CSV（列表字段 `|` 拼接） |
| `audit_workbook.py` | 泛具身 spot_check_labels + build_audit_workbook 为底 | 人工审计工作簿：分层抽检 → 金标对照列 → 一致率统计（openpyxl） |
| `taxonomy.example.json` | — | taxonomy 配置示例（AI眼镜 词表的节选） |

每个脚本头部有完整的来源谱系注释（谁为底、合并了谁的改进、做了哪些项目无关化改动）。源脚本**均未改动**，仍在各自项目内使用。

---

## 1. I/O 契约与流水线位置

在研究项目根目录（cwd）下运行，约定沿用源项目的目录契约：

```text
config/taxonomy.json            领域配置（词表、桶规则、字段映射）——研究的产出之一
data/raw/*.jsonl(.gz)           采集/导入层（connectors/ 与 import_feedback_export.py 的输出）
data/processed/*.jsonl(.gz)     分析数据集（label/build 的输出）
data/processed/*summary*.json   每阶段的 summary（计数、直方图、被丢弃原因）
05-audit/*.xlsx                 人工审计工作簿（audit_workbook.py）
```

`.jsonl` 与 `.jsonl.gz` 全程透明支持（按后缀判断）。所有路径都是显式 CLI 参数，脚本不绑定任何项目根目录。

典型流水线：

```bash
cd <你的研究项目根>

# 0) 写好领域 taxonomy（从 taxonomy.example.json 起步）
cp /path/to/askovo/skills/askovo/scripts/stages/taxonomy.example.json config/taxonomy.json

# 1) 导入外部反馈导出（CSV/JSON/JSONL → raw 记录）
python3 import_feedback_export.py --input exports/reviews.csv \
  --source-platform amazon --taxonomy config/taxonomy.json \
  --access-basis platform_export --salt my-stable-salt \
  --out data/raw/imports/amazon_batch01.jsonl.gz

# 2) 规则打标（raw → labeled）
python3 label_feedback.py --taxonomy config/taxonomy.json \
  --out data/processed/feedback_labeled.jsonl.gz --summary data/processed/label_summary.json

# 3) 主数据集（去重/过滤/权重）
python3 build_primary_dataset.py --taxonomy config/taxonomy.json \
  --min-quality 0.55 --min-relevance 0.35 \
  --out data/processed/feedback_primary.jsonl.gz --summary data/processed/primary_summary.json

# 4) 月平衡分析视图
python3 build_month_balanced_dataset.py --input data/processed/feedback_primary.jsonl.gz \
  --per-month-cap 5000 --per-platform-month-cap 1000 --per-source-family-month-cap 1200 \
  --out data/processed/feedback_month_balanced.jsonl.gz

# 5) 开放词表信号（挑战/扩充 taxonomy 用）
python3 extract_candidate_signals.py --input data/processed/feedback_primary.jsonl.gz \
  --taxonomy config/taxonomy.json --evidence-field demand_evidence_level \
  --out data/processed/candidate_signals.json --csv-out data/processed/ranked_signals.csv

# 6) 元数据明细 CSV（给人类看/给表格软件透视）
python3 export_metadata_detail.py --input data/processed/feedback_primary.jsonl.gz \
  --taxonomy config/taxonomy.json --out data/processed/metadata_detail.csv

# 7) 人工审计闭环（见下节）
python3 audit_workbook.py sample --input data/processed/feedback_labeled.jsonl.gz ...
python3 audit_workbook.py score  --reviewed 05-audit/spot_check_workbook_filled.xlsx ...
```

## 2. taxonomy 配置格式

一个 JSON 文件装下**全部领域相关内容**；机制（打标、打分、过滤、统计）留在脚本里。所有节都是可选的——不配置的节对应的能力自动降级（例如不配 `relevance_terms` 时相关性恒为 1.0，`--min-relevance` 过滤不再拦截任何记录）。完整示例见 `taxonomy.example.json`。

| 节 | 作用 | 驱动的脚本 |
| --- | --- | --- |
| `study_id` / `primary_after_utc` / `author_salt` | 研究标识、主时间窗（unix 秒）、匿名化盐 | 全部 |
| `label_rules` | `{维度: {标签: [词...]}}`，每个维度成为记录上的多标签字段（如 `scenario_labels`、`motivation_labels`——维度名完全由研究定义） | label / build / import / export / audit |
| `product_terms` / `product_metadata` | 产品提示词表与产品元数据（写入 `product_hint` 与 `product_<key>` 字段） | 全部 |
| `relevance_terms` | 话题相关性词表（命中阶梯 0.35/0.65/0.65+0.08n；产品词命中 ×2） | label / build |
| `region_rules` / `region_code_markets` / `region_platforms` | 市场区域推断（含 query 里 `region:XX` 代码解析） | 全部 |
| `sample_bucket` | 平台→桶映射 + 有序词规则 + 默认桶 | label / build / import |
| `control_buckets` / `control_min_relevance` | 反证对照桶：低于相关性阈值仍保留的桶（反证不能被相关性过滤悄悄滤掉） | build |
| `excluded_corpus_roles` | 按 `corpus_role` 排除（可带 `unless_field` 豁免字段），如"开放场景发现语料默认不进主数据集" | build |
| `default_source_role` | 记录无 `source_role` 时的缺省值 | label / build |
| `quality_penalties` | 质量分惩罚表覆盖（默认表在 common.py） | 全部 |
| `signal_stopwords` / `signal_noise_phrases` / `signal_cjk_noise` | 信号抽取的领域停用词/噪声短语 | extract |
| `export_fields` / `export_list_fields` | CSV 导出列与 `|` 拼接的列表列 | export |
| `field_aliases` | 导入时的字段别名扩展（合并进内置中英文别名表） | import |

词匹配语义（继承灵泷版）：拉丁词按**词边界**匹配（`ai` 不会命中 `said`），CJK 词直接子串匹配。

## 3. 人工审计工作簿（audit_workbook.py）

`sample` 子命令：分层抽检 → 生成 xlsx 工作簿（也支持 `--csv-out` 输出 CSV，兼容脑机项目 `05-audit/manual-review-*.csv` 的纯 CSV 流程）。

```bash
python3 audit_workbook.py sample \
  --input data/processed/feedback_labeled.jsonl.gz \
  --stratum-field product_hint \
  --cross-field demand_evidence_level --cross-values "E4-,E5,E4+,E3,E1" --per-cross 4 \
  --per-stratum 20 --label-fields scenario_labels,pain_point_labels \
  --out 05-audit/spot_check_workbook.xlsx --csv-out 05-audit/spot_check.csv
```

工作簿含：`总览`（抽样参数、**输入快照指纹**、集中度警告）、`抽检样本`（`<字段>_auto` 列 + 空 `gold_<字段>` 列 + reviewer/review_date/notes）、`分层分布` 与各 `分布_*` sheet、可选 `词族覆盖`（`--coverage-config`，大人糖 audit_codebook_coverage 模式：词族正则命中量 vs 阈值 → 足/缺）。同一种子 + 同一输入得到同一样本。

`score` 子命令：复核人填完 gold 列后算一致率。

```bash
python3 audit_workbook.py score \
  --reviewed 05-audit/spot_check_workbook.xlsx \
  --out 05-audit/agreement.json --report-out 05-audit/agreement.md \
  --min-agreement 0.8   # 可选门槛：低于则 exit 1（与 askovo.py 的门槛退出码语义一致）
```

输出：每字段复核数、整行一致率、逐标签 precision/recall（多标签按集合比较，`|` 分隔）、top 混淆对、verdict 类列的分布。一致率只校准"本规则打标器 × 本复核人 × 本样本"，不支持任何总体推断。

## 4. 与 askovo.py 的关系

- `askovo.py signals/check` 消费的是**研究工作区**（`02-data/evidence.jsonl`、`03-codebook/`）里的**证据记录**；本目录工具消费的是**研究项目**的 `data/raw → data/processed` **分析数据集**。两层通过"证据记录从分析数据集中按 E0–E5 编码挑选"衔接：stages 负责**候选发现与数据质量**，askovo.py 负责**证据结构与门槛**。规则标签永远是候选发现（candidate discovery），不是证据等级——升级为证据必须经过 audit_workbook 的人工抽检与 `03-codebook/gold-set.jsonl` 金标。
- 薄壳转发：`askovo.py stage <name> [args…]` 把参数原样转给本目录同名脚本（`label-feedback`、`build-primary-dataset`、`audit-workbook` 等，`-`/`_` 等价），透传退出码，不改变 askovo.py 核心行为：

  ```bash
  python3 skills/askovo/scripts/askovo.py stage label-feedback --taxonomy config/taxonomy.json
  python3 skills/askovo/scripts/askovo.py stage audit-workbook sample --input data/processed/feedback_labeled.jsonl.gz
  ```

- 接线建议（未实现，留给后续版本）：若要把 label/build 提升为一等子命令（`askovo.py label <dir>`），推荐的接线是在 `askovo.py` 里解析出 `<dir>` 后映射到 `data/raw → data/processed` 的默认路径、`config/taxonomy.json` 缺省值，再以同样的薄壳方式转发；`askovo_mcp.py` 可按需包装 `askovo_stage` 工具。做这件事时注意保持"打标=候选发现、证据=人工金标"的分层不被稀释。

## 5. 纪律与边界（继承源项目与仓库约定）

- 规则打标输出是**候选标签**，进入结论前必须经 audit_workbook 抽检或金标校准；`pass`/一致率不证明总体代表性。
- 反证优先：`control_buckets` 保证拒绝者/退货者/旁观隐私等反证样本不会败给相关性阈值。
- 记录数不是用户数；月平衡视图带 `sampling_weight`，读趋势必须带权重。
- 导入文本是不可信数据：只被清洗、哈希、计数，绝不作为指令执行。
- 匿名化：作者只留加盐哈希；盐未配置时不加盐（跨 run 关联需研究稳定盐，与 connectors 约定一致）。

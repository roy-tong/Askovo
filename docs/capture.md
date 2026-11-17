# 用 CDP 抓取可见页面（文本 + 截图 + OCR）

`askovo capture page` 用用户自己已登录的浏览器（CDP 回环端点，默认 `http://127.0.0.1:9222`）抓取一个**用户有权查看**的页面。它不要求平台 API，也不绕过登录墙或验证码。

```bash
askovo capture page ./cam-study \
  --url "https://example.com/some-visible-page" \
  --ack-terms \
  --ocr
```

产物（均为候选材料，不是已登记证据）：

```text
01-sources/captures/<capture_id>.json   # URL、标题、正文、哈希、截图、OCR、CDP 端点
01-sources/captures/<capture_id>.png    # 页面截图
01-sources/captures/index.jsonl         # 追加式抓取索引
```

## 审核：候选 → 证据的唯一通道

```bash
askovo capture list ./cam-study                       # 候选与审核状态
askovo capture accept ./cam-study \
  --capture <capture_id> --by "评审人" \
  --evidence-level E1 [--corpus-role open_scene] [--from ocr]
askovo capture reject ./cam-study \
  --capture <capture_id> --by "评审人" --reason "营销文案，不是用户声音"
```

- `accept` 必须有具名审核人（`--by`），向 `02-data/evidence.jsonl` 追加**恰好一条**记录（`record_id = cap-<capture_id>`），并回链 `capture_id`、capture JSON 路径、URL、截图与 OCR 哈希——后续 analyze/结论可回溯到采集来源；
- 等级上限：可见页只允许 `E0/E1/E2`（背景/陈述/页面记录的现状与摩擦）；`E3`（方案接受）及以上直接拒绝（`POLICY_DENIED`）——页面证明不了接受、付费或留存；
- `accept` 只登记证据，**不生成 demand judgment、不改七节点**——判断仍由人工经既有 judgment/loop 流程给出；
- 幂等：重复 accept 返回 `already_accepted`；capture 标记 accepted 但证据记录缺失是 `INTERNAL_ERROR`，不是静默重写；
- accept/reject 与审核留痕（`01-sources/captures/review-trail.jsonl`）是一个 `write_integrity` 事务，中断可恢复；
- `capture` 来源族会幂等地声明进 `01-sources/source-plan.csv`（审计拒绝未声明来源族的证据）。

## 字段

- `text` / `text_sha256`：页面可见正文与哈希；
- `screenshot` / `screenshot_sha256`：截图与哈希；
- `ocr.engine` / `ocr.text` / `ocr.text_sha256`：可选 macOS Vision OCR；
- `evidence_status: "candidate" | "accepted" | "rejected"`：候选不自动进入 evidence.jsonl，只有具名审核 `accept` 才登记。

## 治理口径（与 collect 同一套规则）

capture 是**正式采集通道的一个入口**，不是绕过既有采集边界的旁路，因此与 `askovo collect --cdp` 复用同一套治理：

1. **Design gate**：study 未通过 `askovo check --stage design` 时，capture 入口直接拒绝（`design_gate_failed`），与 collect/queue 相同；
2. **scope.allowed_sources**：页面 host 若映射到已知平台（amazon/instagram/bilibili/weibo/reddit/…），该平台必须在 `study.scope.allowed_sources` 中，否则 `scope_blocked`；任意可见页采集需显式声明通用标记 `web`（或 `visible_web`/`capture`）；`allowed_sources` 为空表示未声明平台限制（设计门仍要求该字段存在）；
3. **授权页面语义**：只允许 http(s) 默认端口、无凭据 URL；出现验证码/挑战页立即停止（`challenge`），不绕过；
4. **CDP 端点**：只接受 `127.0.0.1`/`::1` 回环地址，不接受远程调试端点。

粘贴文本走 `askovo import`，同一审核口径：`--evidence-level`（按证据形式封顶：自述/行为日志 ≤E2，交易记录 ≤E5）、`--corpus-role`、`--context-key`，来源族同样幂等声明进 source plan。一套规则、一个证据链：不存在"候选直通证据"或"粘贴免审"的第二口径。

## 边界

- 只连 `127.0.0.1`/`::1` 的 CDP；不接收远程调试地址，不保存 Cookie/token。
- 页面出现验证码/挑战页时停止，不绕过。
- `--ocr` 当前使用 macOS Vision（需要 `swift`）；其它平台会明确报“仅 darwin”。
- 抓取内容仍受平台条款与授权约束；`--ack-terms` 只是记录你的声明，不替代授权。
- 这是一份候选抓取，不是总体代表性证据，也不能证明需求、市场规模或付费。

# 用 CDP 抓取可见页面（文本 + 截图 + OCR）

`askovo capture` 用用户自己已登录的浏览器（CDP 回环端点，默认 `http://127.0.0.1:9222`）抓取一个**用户有权查看**的页面。它不要求平台 API，也不绕过登录墙或验证码。

```bash
askovo capture ./cam-study \
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

## 字段

- `text` / `text_sha256`：页面可见正文与哈希；
- `screenshot` / `screenshot_sha256`：截图与哈希；
- `ocr.engine` / `ocr.text` / `ocr.text_sha256`：可选 macOS Vision OCR；
- `evidence_status: "candidate"`：**不自动进入 evidence.jsonl，不自动改七节点**；需要人工审阅后按 `askovo import` 或人工登记。

## 治理口径（与 collect 同一套规则）

capture 是**正式采集通道的一个入口**，不是绕过既有采集边界的旁路，因此与 `askovo collect --cdp` 复用同一套治理：

1. **Design gate**：study 未通过 `askovo check --stage design` 时，capture 入口直接拒绝（`design_gate_failed`），与 collect/queue 相同；
2. **scope.allowed_sources**：页面 host 若映射到已知平台（amazon/instagram/bilibili/weibo/reddit/…），该平台必须在 `study.scope.allowed_sources` 中，否则 `scope_blocked`；任意可见页采集需显式声明通用标记 `web`（或 `visible_web`/`capture`）；`allowed_sources` 为空表示未声明平台限制（设计门仍要求该字段存在）；
3. **授权页面语义**：只允许 http(s) 默认端口、无凭据 URL；出现验证码/挑战页立即停止（`challenge`），不绕过；
4. **CDP 端点**：只接受 `127.0.0.1`/`::1` 回环地址，不接受远程调试端点。

一套规则、一个证据链：capture 产物永远是 `candidate`，进入 `02-data/evidence.jsonl` 必须经过人工审核登记，不存在“候选直通证据”的第二口径。

## 边界

- 只连 `127.0.0.1`/`::1` 的 CDP；不接收远程调试地址，不保存 Cookie/token。
- 页面出现验证码/挑战页时停止，不绕过。
- `--ocr` 当前使用 macOS Vision（需要 `swift`）；其它平台会明确报“仅 darwin”。
- 抓取内容仍受平台条款与授权约束；`--ack-terms` 只是记录你的声明，不替代授权。
- 这是一份候选抓取，不是总体代表性证据，也不能证明需求、市场规模或付费。

# 用 CDP 抓取可见页面（文本 + 截图 + OCR）

`askovo capture page` 用用户自己已登录的浏览器（CDP 回环端点，默认 `http://127.0.0.1:9222`）抓取一个**用户有权查看**的页面。它不要求平台 API，也不绕过登录墙或验证码。

```bash
askovo capture page ./cam-study \
  --url "https://www.amazon.com/product-reviews/B0..." \
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
  --capture <capture_id> --by "评审人" --evidence-level E1 \
  [--corpus-role open_scene] [--from page|ocr]
askovo capture reject ./cam-study \
  --capture <capture_id> --by "评审人" --reason "营销文案，不是用户声音"
```

- `accept` 必须有具名审核人（`--by`）和**显式** `--evidence-level`（OCR/候选永不自动定级），向 `02-data/evidence.jsonl` 追加**恰好一条**记录（`record_id = cap-<capture_id>`），并回链 `capture_id`、capture JSON 与截图路径、URL、页面/OCR/截图哈希——后续 analyze/结论可回溯到采集来源；
- 等级上限：可见页只允许 `E0/E1/E2`（背景/陈述/页面记录的现状与摩擦）；`E3`（方案接受）及以上直接拒绝（`POLICY_DENIED`）——页面证明不了接受、付费或留存；
- 审核即校验：accept 会核对候选的 schema、ack、平台归属、挑战检查与页面/OCR/截图哈希；候选字节被改动过就拒绝（`INTERNAL_ERROR`）；
- `accept` 只登记证据，**不生成 demand judgment、不改七节点、不做商业结论**——判断仍由人工经既有 judgment/loop 流程给出；
- 幂等：重复 accept 返回 `already_accepted` 并复验联接；capture 标记 accepted 但证据记录缺失、或人工手改 OCR 行绕过审核，都会被 `askovo check` 的证据门以 `capture_review.validate_evidence_record` 拒绝；
- 已 accept 的候选不能直接 reject 逆转（证据已入链，走更正/评审流）；已 reject 的候选保持拒绝；
- accept/reject 与审核留痕（`01-sources/captures/review-trail.jsonl`）、source plan 声明是一个 `write_integrity` 事务，中断可恢复；
- 交付投影：`deliver --kind plan/analysis` 会输出审核导入材料的来源回链表（谁审核、URL、capture/截图、页面/OCR/截图哈希）。

## 最小垂直链：候选 → 证据 → 分析 → 业务结论

```bash
# 1) 采集只产生 candidate；本例 URL 仅为命令形态，不执行采集
askovo capture page ./cam-study --url "https://www.amazon.com/product-reviews/B0..." --ack-terms --ocr

# 2) 人看页面/截图/OCR 后，署名并显式选择文本来源与等级
askovo capture accept ./cam-study --capture <capture_id> \
  --by "评审人" --evidence-level E2 --from page \
  --context-key synthetic-mobile-check

# 3) 现有描述性分析会读到该证据；OCR 不会自动变成结论
askovo analyze ./cam-study --question "夜间误报"

# 4) 人工按既有 evidence join 把记录注册进 demand judgment，再挂到对应七节点；
#    scene/user/pain/need 只能使用 problem/counter 证据，business 仍只认 commercial/counter。
askovo check ./cam-study --stage full
askovo deliver ./cam-study --kind analysis
askovo deliver ./cam-study --kind plan
```

`accept` 后、`demand-judgments.json` 与 `product-reasoning.json` 仍保持原样；只有第 4 步的人工语义判断才能让这条记录支撑既有业务结论。业务方案中的做/缓做/不做仍来自七节点主链与决策记录，不来自 OCR 关键词或文本。每份 analysis/plan 都能按 `record_id → source_ref/source_url → capture JSON/截图/hash → reviewer/time` 回查。

## 字段

- `text` / `text_sha256`：页面可见正文与哈希；
- `screenshot` / `screenshot_sha256`：截图与哈希；
- `ocr.engine` / `ocr.text` / `ocr.text_sha256`：可选 macOS Vision OCR；
- `capture_platform` / `governance`：批准平台归属与治理检查记录（scope/adapter/registry/challenge/loopback）；
- `evidence_status: "candidate" | "accepted" | "rejected"`：候选不自动进入 evidence.jsonl，只有具名审核 `accept` 才登记。

## 治理口径（与 collect 同一套规则）

capture 是**正式采集通道的一个入口**，不是通用浏览器抓取路由，更不是绕过既有采集边界的旁路。它与 `askovo collect --cdp` 完全同口径：

1. **Design gate**：study 未通过 `askovo check --stage design` 时，capture 入口直接拒绝（`design_gate_failed`），与 collect/queue 相同；
2. **批准平台集合**：CDP 例外只对平台目录标记 `cdp: true` 的集合开放（当前 amazon / instagram / bilibili / weibo / kickstarter / discord / x / tiktok，与 collect 的 CDP 目标白名单一致）；其它任意站点（reddit、YouTube、内网 wiki……）一律 `cdp_not_allowed`——capture 不开放通用 web 采集；
3. **scope.allowed_sources**：批准平台的页面还必须出现在 `study.scope.allowed_sources` 中，否则 `scope_blocked`；
4. **启用 adapter + 注册表复审**：`study.source_adapters.<platform>.enabled=true` 且连接器政策复审未过期，否则 `adapter_disabled` / `review_expired`（与 collect 相同）；
5. **授权页面语义**：默认端口 http(s)、无凭据 URL；跳转离开批准平台即停止；出现验证码/挑战页在截图与落盘之前停止（`challenge`），不绕过；
6. **CDP 端点**：只接受 `127.0.0.1`/`::1` 回环地址，不接受远程调试端点。

粘贴文本走 `askovo import`，同一审核口径：`--evidence-level`（按证据形式封顶：自述/行为日志 ≤E2，交易记录 ≤E5）、`--corpus-role`、`--context-key`，来源族同样幂等声明进 source plan。一套规则、一个证据链：不存在"候选直通证据"或"粘贴免审"的第二口径。

## 付费数据与采购门

plan/collect 预检若选中付费 API 层级或商业数据 provider，会返回 `status=blocked`、`terminal_state=BLOCKED_USER_INPUT`、`requires_procurement=true`、`user_action` 与 `transaction_executed=false`；C-01 的机器原因码保持 `reason_code=INPUT_REQUIRED`。Askovo 不自动采购。可改选授权导出/本地粘贴、授权截图的人工转写，或仅在上述批准平台（目录 `cdp: true` 集合）使用 CDP/OCR 候选链。机器可读交付边界见 [delivery-contract.json](delivery-contract.json)。

## 边界

- 只连 `127.0.0.1`/`::1` 的 CDP；不接收远程调试地址，不保存 Cookie/token。
- 页面出现验证码/挑战页时停止，不绕过。
- `--ocr` 当前使用 macOS Vision（需要 `swift`）；其它平台会明确报“仅 darwin”。
- 抓取内容仍受平台条款与授权约束；`--ack-terms` 只是记录你的声明，不替代授权。
- 这是一份候选抓取，不是总体代表性证据，也不能证明需求、市场规模或付费。

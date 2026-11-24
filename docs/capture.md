# 用 CDP 抓取可见页面（文本 + 截图 + OCR）

`askovo capture page` 用用户自己已登录的浏览器（CDP 回环端点，默认 `http://127.0.0.1:9222`）抓取一个**用户有权查看**的页面。它不要求平台 API，也不绕过登录墙或验证码。需要逐条采集 Instagram 评论或 Discord 消息时，使用 `askovo collect --attach-existing`；单页候选＋截图／OCR 仍使用本页的 capture 链。

```bash
askovo capture page ./cam-study \
  --url "https://www.amazon.com/product-reviews/B0..." \
  --ack-terms \
  --ocr
```

产物（均为候选材料，不是已登记证据）：

```text
01-sources/captures/<capture_id>.json   # URL、标题、正文、created_at、作者、结构化行、哈希、截图、OCR、CDP 端点
01-sources/captures/<capture_id>.png    # 页面截图
01-sources/captures/index.jsonl         # 追加式抓取索引
```

`structured_rows` 是平台提取出的评论/帖子行，保留 `created_at`、作者和精确 URL；`capture accept` 归一化时优先使用它们，避免只剩整页纯文本后丢失发生时间和来源。

## 审核：候选 → 证据的唯一通道

```bash
askovo capture list ./cam-study                       # 候选与审核状态
askovo capture accept ./cam-study \
  --capture <capture_id> --by "评审人" \
  --observation statement [--evidence-level E1] [--corpus-role open_scene] [--from page|ocr]
askovo capture reject ./cam-study \
  --capture <capture_id> --by "评审人" --reason "营销文案，不是用户声音"
```

- 错误页不产生候选：标题报告 not found/404（含中文"页面不存在"）的页面在截图与落盘前
  直接 `page_not_found` 停止，不进入候选与审核队列；
- 空渲染同样不产生候选：HTTP 200 但标题与正文均为空（如 Invision/MyGolfSpy 在 IAB 内）
  返回 `blank_render`——这是不支持的渲染栈，不是挑战页、也不是空语料；换同垂类信源，
  不重试、不改自动化方式；
- 超时是熔断而不是重试：CDP 调用超时返回 `cdp_timeout` 并带上该平台策略的冷却时间
  （默认 15 分钟）；`CDPClient` 在超时后拒绝继续读同一个流（撕裂的帧边界不可恢复），
  期间不要再碰该平台；
- 会员墙不产生候选：Discord 等会员验证页面返回 `membership_gated`——**加入 ≠ 可读**，
  记为覆盖缺口，不尝试验证角色/机器人/冒充，也不把门禁页写成候选；
- CDP 平台的研究设计声明（study.json `source_adapters.<platform>`）有第一方传输通道：
  `connector_id=cdp-authorized-visible-page` + `access_basis=cdp_authorized_visible_page` +
  `collection_mode=authorized_visible_page` + 引擎版本号，资格来自平台目录 `cdp: true`，
  不要求开源连接器注册表——注册表只治理第三方采集代码；kickstarter/bilibili/weibo 等
  目录开放 CDP 但无可用开源连接器的平台由此才能合法设计研究。脚本化采集仍走注册表与既有枚举。

- `accept` 必须有具名审核人（`--by`），向 `02-data/evidence.jsonl` 追加**恰好一条**记录（`record_id = cap-<capture_id>`），并回链 `capture_id`、capture JSON 与截图路径、URL、页面/OCR/截图哈希——后续 analyze/结论可回溯到采集来源；
- 等级由来源结构与审核过程**推导**，不是审核人自报：`--observation` 说明审核人实际看到了什么（`context` 背景 = E0；`statement` 单页陈述，默认 = E1；`practice` 页面记录的现状/流程/花费 = E2，但 OCR 转写不能支撑 E2，只能是 E1）；可见字符不足 20 的片段一律 E0；`E3` 只由 `--concept-test`（stimulus/sample_size/response_metric/result）推导。`--evidence-level` 只是**上限**：请求高于推导等级时按推导等级登记并返回 `level_capped: true`，请求 E4+/E5 直接拒绝（`POLICY_DENIED`）；
- 每条记录写入 `level_derivation_version`、`level_basis`、`requested_evidence_level`、`level_observation`；`askovo check` 的证据门会用同一规则复算等级，手改证据行抬高等级会被拒绝；
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

# 2) 人看页面/截图/OCR 后，署名并说明实际观察到什么；等级由来源推导
askovo capture accept ./cam-study --capture <capture_id> \
  --by "评审人" --observation practice --from page \
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
2. **批准平台集合**：CDP 例外只对平台目录标记 `cdp: true` 的集合开放（当前 github / reddit / youtube / hackernews / amazon / instagram / bilibili / weibo / kickstarter / discord / x / tiktok，与 collect 的 CDP 目标白名单一致）；有官方 API 的平台也可使用这条已声明路线，但其它任意站点（内网 wiki……）一律 `cdp_not_allowed`——capture 不开放通用 web 采集；
3. **scope.allowed_sources**：批准平台的页面还必须出现在 `study.scope.allowed_sources` 中，否则 `scope_blocked`；
4. **启用 adapter**：`study.source_adapters.<platform>.enabled=true`，否则 `adapter_disabled`（与 collect 相同）；连接器政策复审过期不阻断采集，只在 payload `governance.registry_review` / `review_status` 标记 `expired` 并附 `warning`，采集按降频节奏继续、复审另行排期；
5. **授权页面语义**：默认端口 http(s)、无凭据 URL；跳转离开批准平台即停止；出现验证码/挑战页时只做被动等待（用户在同一个浏览器里手工完成或页面自行清除），超时仍存在则在截图与落盘之前停止（`challenge`），不主动绕过；
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

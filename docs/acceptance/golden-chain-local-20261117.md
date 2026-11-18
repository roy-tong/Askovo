# 本地黄金链验收日志 20261117

- 生成：tests/acceptance/golden_chain_local.py（离线、仅回环）
- 通过 6 / 6 个场景；失败 0

| 场景 | 终态 | 结果 |
|---|---|---|
| paste_to_answer | DELIVERED_WITH_GAP（lexical=go，正式业务决策=continue_research；待七节点+ | PASS |
| capture_ocr_review_to_answer | DELIVERED_WITH_GAP（单页 1 条证据=低样本支持：answer=continue_research，领 | PASS |
| opposite_corpora_flip | A→移动巡检试点；B→保持固定摄像头方案（同 question/options） | PASS |
| no_evidence_unanswerable | DELIVERED_WITH_GAP（answer_status=unanswerable，decision=unans | PASS |
| governance_rejections | scope_blocked（amazon 未列入 allowed_sources）/ design_gate_faile | PASS |
| hand_appended_capture_row_fails_audit | FAILED_UNRESOLVED 不适用；审计为 fail 且指出 cap-forged0001 的审核联接无效 | PASS |

## 支持项 / 未支持项

- 支持：粘贴文本 → 审核 import → analyze → answer
- 支持：授权可见页（批准 CDP 平台）→ capture 文本+截图+OCR → 具名审核 accept → analyze → answer
- 支持：结论随证据改变、反证不被淹没、无证据=不可回答+缺口清单
- 支持：capture 治理与 collect 同口径（design gate/scope/adapter/挑战页/批准平台）

- 未验证/边界：真实外部页面读取（live_external_read）本轮未验证：CDP 端是本地回环 fixture，不是真实浏览器实例
- 未验证/边界：OCR 质量依赖 macOS Vision 与本地渲染截图；复杂版式/低分辨率未覆盖
- 未验证/边界：批量采集、滚动/分页、去重策略属 P2，未在本链验收


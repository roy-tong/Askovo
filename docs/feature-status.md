# Askovo: implementation status

Reviewed 2026-11-01 against the repository implementation. Available means local implementation, not production validation on every platform.

| Feature | Scope | Status |
|---|---|---|
| A01–A02 | Business brief, reasoning chain, action planning | Available; host-authored plans plus `askovo loop`, which derives round actions from audit gaps |
| A03–A05 | Source routing, authorization and bounded collection | Available for supported connectors and offline exports; the loop may only use `scope.allowed_sources` with an enabled adapter or a declared fixture; interrupted actions require review |
| A06 | Local PDF/Office/image document intake | Optional Docling adapter via `askovo document`, with SHA-256 provenance and unreviewed status; not a validated research claim |
| A07–A09 | Study workspace, descriptive analysis, evidence audit | Available; human semantic validation remains required |
| A10–A11 | Active follow-up research and option comparison | `askovo loop` runs gap-driven rounds inside an authorized envelope, re-audits after each round and stops with candidates awaiting semantic review; it never assigns evidence levels, edits judgments or marks a claim validated. Autonomous semantic judgment is not claimed; option comparison is available |
| A12 | Reports, MRD/PRD/BRD and decision package | Available; refreshed audit guards delivery |
| A13–A15 | Continuous validation, evaluation and industry packs | Existing tests/domain packs; scheduled continuous research is not shipped |

Build: SURE reasoning, evidence contracts, authorization, acceptance and delivery. Reuse: existing source connectors; evaluate Crawl4AI/Scrapy for collection and Docling for documents only as optional adapters. Core remains standard-library-only. The optional `askovo_document` MCP tool shares the same local extraction adapter as `askovo document`, and writes only to explicit local paths. New document ingestion uses an optional Docling installation; no vendored fork or mandatory core dependency.

Research loop: `askovo loop plan/authorize/run/status/report` detects gaps from the same audit verdicts, generates deterministic queries per gap and eligible source, executes them inside an authorized envelope (allowed platforms, per-action cap, round and record budgets), re-audits after each round and writes `04-findings/loop-candidates.json` plus `05-audit/research-loop-summary.md`. Candidates carry `proposed_evidence_level: null`: only human review assigns E0–E5 and links records to a demand judgment. The envelope is an operational bound, not tamper protection; platform policy, `allowed_sources`, adapter switches and the Design gate remain the enforcing controls. MCP can plan/status/report/run but cannot authorize.

Recovery: completed actions are checkpointed before analysis; an interrupted `running` action blocks replay. The loop records `interrupted_run` and requires inspection before replanning. Inspect collected files and provenance before preparing a replacement plan. Never reset blindly. Execution is serialized using an OS file lock on macOS/Linux. `research` authorization binds the actual action fields; `loop` authorization binds the envelope hash.

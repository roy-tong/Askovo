# Changelog

## 2.21.0 — 2026-11-22

### Added

- **`askovo chain-node STUDY set --node NODE --field FIELD --value-json JSON`** edits typed task fields through the canonical writer, with field/type validation, idempotent writes and append-only change history. Arrays cover acceptance conditions, alternatives, assumptions, constraints and scope/non-goal lists; no manual JSON editing is needed for these fields.

- **`askovo proof export STUDY --out NEW_DIR --by NAME`** and MCP `askovo_proof_export` project the canonical study into a read-only Prove Anything Proof Bundle. Source files remain byte-identical; only Decision Brief artifacts are copied, P3 semantic review and P4 adoption stay UNCHECKED, stale briefs become EXPIRED, and existing outputs are never overwritten. The common `ovo_acceptance proof` validator accepts the synthetic export with no structural errors.
### Added

- **CDP transport for API-capable platforms**: GitHub, Reddit, YouTube and
  Hacker News now support the same governed authorized-visible-page CDP route
  as the existing CDP platforms. Official APIs remain preferred; Design, scope,
  adapter, human acknowledgement, loopback and challenge-stop gates are unchanged.
- **Collection policy layer (`collection_policies`)**: one entry per acquirable
  platform recording allowed access modes, a request budget (cadence, session
  cap, headroom), graded detection signals, stop rules and dated sources.
  `askovo platforms "<need>" --collection-policies` renders the cards and
  `--json` adds `collection_policy` to each recommendation; `askovo doctor`'s
  new `collection-policies` gate fails when a policy invents an access mode
  outside `platform-catalog.json`, costs more than the enforced runtime budget,
  lacks a `block`-level signal or rests only on `lead` sources, or when a
  catalog-blocked platform has no exclusion note. Each platform also carries an
  `observed[]` community-experience list (claim, threshold, window, confidence,
  dated source URLs); the engine rejects any entry whose suggested cadence is
  faster than the budget, so experience can only slow a run down. The prose
  rationale ships as `references/collection-strategy.md` (§2.1).
- **Executable Instagram / Discord CDP source plans**: overseas `forum,social`
  planning now allocates exact quotas to both platforms, copies five-role route
  templates, and declares the first-party `cdp-authorized-visible-page`
  transport instead of requiring a nonexistent API connector. `--sample-size`
  is explicitly capped at 100,000 strict-primary target records; larger studies
  must be split into separately audited windows.
- **Existing logged-in page collection**: `askovo collect --attach-existing`
  attaches to the exact already-open URL without creating a tab, reading stored
  credentials, or exporting cookies. MCP exposes the same flag, dry-run output
  preserves the complete CDP command, and an explicit CDP route is no longer
  stopped by the paid-API procurement preflight.
- **Dedicated Instagram / Discord DOM extraction**: visible comments/messages
  retain full text, source URL, channel/account, content type and timestamps;
  session platforms use real wheel events for lazy loading. Raw envelopes,
  normalized records and run manifests keep the existing provenance contract.

### Fixed

- **Policy-review expiry no longer blocks collection**: an expired platform
  review is a freshness warning, not a stop. `capture page` and `collect`
  return `review_status: "expired"` with a warning that asks for reduced
  cadence, split batches and a scheduled re-review, while the run continues on
  the authorized visible-page route. `research_loop` no longer treats
  `review_expired` as fatal.
- **API procurement no longer excludes the CDP route**: `x` and `kickstarter`
  design checks accept the first-party `cdp-authorized-visible-page` transport
  before their paid-connector enums, and `plan` scaffolds that adapter for every
  platform whose primary route is CDP (GitHub, Hacker News, X, Kickstarter,
  Instagram, Discord, Weibo). Official APIs stay preferred where available;
  the absence of a purchased API tier only closes that route, not the platform.
- **Contradictory agent authorization guidance**: the Skill now describes one
  CDP allowlist everywhere and does not request a second generic pilot approval
  when the original request already authorized logged-in-browser CDP and Design
  has passed. Explicit terms acknowledgement, Design/scope/adapter checks,
  challenge stops and API-first routing remain unchanged.
- **Study design for the new CDP routes**: Instagram and Discord require access,
  rights, retention, no-personal-data and source-concentration declarations;
  documentation no longer claims that registry-only planning governs them.

### Tests

- `tests/test_cdp_source_expansion.py` covers the 100,000-record allocation and
  cap, route/adapters, existing-page full-text collection, dedicated extractors,
  MCP parity and Skill authorization wording. Full suite: 879 tests OK for the 2.21.0 candidate.


## 2.20.3 — 2026-11-20

The research handoff: a study can publish its premises to a downstream product
without letting them arrive as conclusions.

### Added

- **`askovo context export <study> --out <dir> --approved-by <name>
  --value-event <event>`** writes the chain a downstream product needs, in two
  files: `<context_id>.<version>.payload.json` and a `<context_id>.<version>.json`
  envelope carrying `source.kind: "askovo"`, the payload's absolute `source.ref`
  and its `content_sha256`. Every claim keeps the status it earned in
  `04-findings/product-reasoning.json` — `evidence_supported`, `hypothesis`,
  `insufficient_evidence` — and the export only copies, never promotes, so a
  hypothesis cannot reach Growovo looking like evidence. `product` and
  `business` non-goals are collected into the package and an empty set refuses
  the export; `--approved-by` and at least one `--value-event` are required,
  because exporting is approval to forward the research and Askovo does not
  invent the downstream value metric. Defaults are
  `context_id=askovo-<study_id|context_key|directory>` and
  `version=reasoning-<first 12 of the reasoning sha256>`; `--chain` narrows a
  multi-chain study, and an unknown chain exits 2 listing the ones that exist.
  Re-exporting the same version refuses and leaves both files byte-identical
  (`open(path, "x")`), and a failed envelope write removes the payload it just
  wrote. Output ends with the next command,
  `mkt context import --file <envelope> --by <operator>`.
  `tests/test_context_export.py` covers 7 cases: grades preserved, refusals
  write nothing, payload hash verified, re-export identical.

## 2.20.2 — 2026-11-20

Delivery-truth round from the 2026-11-20 end-to-end business test: what a
report may call a conclusion, how a gap is stated, and how a chain edit is
recorded.

### Fixed

- **a report only calls itself a conclusion when the business node earns it**:
  `deliver` now separates "current judgment" from "conclusion". A conclusion
  requires a `validated` business node, qualifying E4+/E5 commercial evidence
  and a clean `check --stage full`. Otherwise the same page states the current
  judgment, the named gaps and the concrete next evidence action, so a study
  with no paying evidence can no longer read like a finished decision.
- **material gaps are stated the same way everywhere**: every rendered document
  opens with its gaps in `未提供｜影响：…｜补充方式：…` form instead of silently
  leaving fields blank; empty gap lists are no longer serialized as `[]`, and
  `_gap_note` / `_gap_or_value` / `_delivery_gap_block` share one wording path.
- **`roles scaffold` never overwrites a workbench by default**: an existing
  `01-sources/role-workbench/` is protected. `--overwrite` returns an
  added/modified/deleted preview (line counts, before/after sha256, first lines)
  and writes nothing; `--overwrite --confirm` backs the old workbench up to
  `role-workbench.bak-<timestamp>` before an atomic replace and restores it on
  failure; identical content returns `unchanged`. `--force` is deprecated and
  no longer overwrites.

### Added

- **`askovo chain-node`**: edit one canonical chain node in
  `04-findings/product-reasoning.json` without hand-editing JSON.
  `show` is read-only; `set` changes statement/rationale/status;
  `bind-evidence` / `unbind-evidence` manage evidence ids. Every real edit
  appends a `change_log` entry with `base_version` (`chain-vN`), `new_version`,
  `decision` (`--note`), `previous`, `affected_refs` and
  `projection_sync: pending`, so a judgment change can be traced to its
  pre-edit state. The command writes truth only, never audits
  (`audit_status: not_run`); binding checks that the evidence id exists, while
  `check --stage full` still decides whether the evidence class fits the node.
  No-op edits return `unchanged` without writing.
- **unit-economics arithmetic check**: `pricing[]` entries may declare `volume`
  and `revenue`; `askovo check` verifies unit price × volume = revenue in
  `Decimal` with `max(0.01 absolute, 0.5% relative)` tolerance, back-solves the
  one missing figure and marks it as computed. Declared margin, gross-margin
  rate or ROI that contradicts the computed values is reported, never silently
  rewritten, and `unit_economics` warns surface in `askovo check`.

### Tests

- `tests/test_delivery_conclusion_gate.py` — conclusion only with validated
  business node + qualifying commercial evidence + clean full audit.
- `tests/test_delivery_gap_notes.py` — uniform gap wording, no `[]` leakage.
- `tests/test_chain_node_editing.py` — show/set/bind/unbind, change_log,
  unchanged no-op, error exits.
- `tests/test_economics_validation.py` — volume/revenue arithmetic, tolerance
  edges, computed back-solve, warn-only declared mismatches.
- `tests/test_role_workbench_overwrite.py` — default/`--force` refusal,
  preview, backup + atomic replace, `unchanged`.
- Full suite: 818 tests OK.

## 2.20.1 — 2026-11-20

A-TRUST-01 and A-WEB-01 from the 2026-11-20 main review.

### Fixed

- **P0 A-TRUST-01 a self-declared material type no longer buys a high evidence
  grade**: `import ... --evidence-form transaction --evidence-level E5` used to
  cap the row at E5 purely from the caller's label. A `transaction`/`purchase`
  row that declares E4 or above must now carry a real record structure:
  `counterparty`, `occurred_at`, `amount`, `source_ref` and `evidence_ref`
  (Chinese aliases accepted). If any is absent the row is held at E2, and the
  record explains why (`level_basis`, `level_declared`,
  `requested_evidence_level`, `level_derivation_version =
  askovo-import-derivation/2`). A line of free text labelled "transaction" is
  not a transaction record; import also returns `structure_downgrades` and
  `review.structure_rule` so the caller can see the rule that fired.
  `tests/test_p0_import_levels.py` keeps a structured positive row and four
  counter-examples (plain text claiming transaction, missing counterparty,
  missing amount, missing source reference).
- **P1 A-WEB-01 report source links stay safe to share**: an evidence
  `source_url` is rendered as `<a href>` only when its scheme is `http`/`https`
  and the host is non-empty. `javascript:`, `data:`, `file:` and
  protocol-relative URLs render as inert text instead of a clickable link, and
  the generated page carries a CSP meta tag (no scripts, no frames, no forms).

### Tests

- `tests/test_p0_import_levels.py`: 8 tests OK.
- `tests/test_web_surface.py`: 10 tests OK, including unsafe-URL, safe-https
  and CSP cases.

## 2.20.0 — 2026-11-20

The 2026-11-19/20 full-scenario end-to-end test: two P0 evidence-trust defects
fixed, plus the boundary cases from the same run.

### Fixed

- **P0-A zero-corpus studies no longer produce a formal-looking conclusion**:
  `deliver` refuses to render a validated report when no usable evidence is
  registered. It writes an evidence-gap note instead, naming which node lacks
  which evidence class and what would close it. Three distinct errors:
  `EVIDENCE_EMPTY` (nothing registered), `EVIDENCE_UNQUALIFIED` (records exist
  but fail eligibility — unusable source, no review, wrong context key) and
  `EVIDENCE_SOURCE_UNREADABLE` (cited source cannot be read back). A gap note
  is never labelled as a decision conclusion.
- **P0-B `evidence_level` is derived, not self-declared**: the grade comes from
  evidence type, source structure and review history (`IMPORT_LEVEL_CAPS`
  caps what an import or a user assertion can claim). A user-supplied `E4`/`E5`
  on a self-report or an unreviewed import stays at its derived ceiling; the
  derivation basis, method version and review history remain inspectable.
  Users submit evidence and review opinions; they do not assign grades.
- **C-07 counter-evidence-first policy rejection is a usable refusal**: a
  question that the policy refuses on counter-evidence grounds returns the
  refusal reason, the contradicting evidence and a legal next action, instead
  of a dead end.
- **E-08 empty collection window writes a gap note**: a window that returns
  nothing produces an explicit gap record; it is not silently rendered as a
  zero-prevalence finding.
- **X-06 cross-product handoff carries premises only**: the handoff package
  ships source object, version, scope, key assumptions, counter-evidence,
  human-review state and evidence references with `shared_registry=false`.
  Downstream products inherit premises, never Askovo's verdict.

### Tests

- `tests/test_p0_evidence_trust.py` and `tests/test_p0_import_levels.py` cover
  the refusal paths, the derived-level ceilings and the gap-note content.
  Full suite: 775 tests pass on Python 3.9–3.12.

## 2.19.0 — 2026-11-19

The 2026-11-18 end-to-end review: one evidence authority, structured decision
direction, explicit chain choice, visible-page capture and separate owner adoption.

### Added

- **`askovo deliver --kind web` renders a reading surface, not another list**:
  `06-report/web/index.html` is a self-contained page (inline CSS/SVG, no
  external scripts, fonts or images, `noindex`) ordered for a business reader —
  how to read, now vs. when the judgment was formed, conclusions, the seven
  nodes, an evidence wall, distribution charts, reusable playbook, risks,
  method archive and boundaries. Every section is the same canonical chain; the
  renderer never writes `study.json`, judgments or evidence.
- **Four reading labels over the E0–E5 grades**: records project to
  事实 / 自述 (from `behavior_kind` first, then the E level; E4+ price intent and
  attention metrics keep their honest reading), nodes and conclusions to
  推导 / 我的判断. Grades, `behavior_kind`, `measurement_integrity` and
  `claim_eligibility` stay in the page's method archive, so the body reads like
  a business document without losing the audit trail. `plan.md` reuses the same
  `label_for` for its per-section 「证据类型：事实 N 条 · 自述 N 条」 line.
- **Numbers and judgments are dated separately**: the page shows 「现在：数字与
  图表」 next to 「判断形成于」, plus delta version, audit status and a re-run
  command. When the evidence store is newer than the chain it raises 数字已更新，
  结论文字尚未重算 instead of presenting old prose as current; `plan.md` carries
  the matching 时间分层 notice.

Tests: `tests/test_web_surface.py`.

### Fixed

- **`answer` reads the qualified evidence store** (`load_evidence_store` +
  `is_qualified_evidence`) instead of raw `evidence.jsonl` lines: a registered
  row without a valid `evidence_level` can no longer join the lexical support
  counts, and the answer's record count matches audit/deliver.
- **A corrupt evidence file refuses a trusted answer**: malformed or non-object
  lines yield `answer_status=invalid_evidence_store`, `decision=unanswerable`
  and the offending line numbers; a ready DecisionRecord cannot override it.
- **Formal go/no-go comes from the option identity**: `study.decision` may
  declare `option_directions` (option id → `go`/`no_go`) or object options with
  `id`/`label`/`direction`. Free-text polarity scanning is gone, so a statement
  such as “停止拖延，立即上线试点” no longer flips to `no_go`. A missing
  direction returns `continue_research` with a gap, never a guess.
- **Multi-chain studies never default to `chains[0]`**: `answer` and
  `decision brief` select the chain named by the latest DecisionRecord, or
  refuse with `needs_chain_selection` and the candidate ids; `brief --chain`
  names one explicitly.
- **Capture can attach to the user's exact visible page**: `capture page
  --attach-existing` selects an already-open URL through loopback CDP without
  navigating or creating a tab. The normal new-page route still returns its
  validated websocket, waits for navigation to leave `about:blank`, and records
  `blank_render` without a candidate if loading does not commit.
- **Owner adoption is separate from recommendation and delivery**: `decision
  adopt` requires the current DecisionRecord, accountable owner, exact scope and
  an observable receipt/source. The append-only adoption receipt is projected in
  the brief's `decision_lifecycle`; neither a brief nor `decided` implies
  adoption, implementation, commercial success or causality.
- **GitHub REST issue exports remain importable**: a REST `comments` integer is
  preserved as `comments_count` with no invented comment bodies; exports that
  contain full comment objects retain the reviewed comment whitelist.
- **The synthetic sample tracks `VERSION` again**: the release bump left
  `examples/sample-study/study.json` on `2.18.2`, so the CI single-source
  version assertion failed on every Python version. The sample now reads
  `2.19.0`, matching `VERSION`, the CLI, the package and the MCP server.

Tests: `tests/test_askovo_answer_semantics.py`,
`tests/test_decision_adoption.py`, `tests/test_issue_rest_export.py`, and the
new-page/attach-existing regressions in `tests/test_askovo_cdp.py`.

## 2.18.2 — 2026-11-18

The 2026-11-09 end-to-end UX walkthrough (12 findings) rebased onto 2.18.1.

### Fixed

- **Chinese descriptive analysis is word-based**: `askovo analyze` segments
  Chinese with a bundled lexicon (`assets/chinese-lexicon.txt`, greedy longest
  match), so 高频词 are real words instead of character fragments; multi-word
  questions match records (previously silently zero) with a 2-char bigram
  fallback for out-of-lexicon query runs; `collected_at` dates on imported
  records count toward month coverage.
- **Join errors name the misplaced evidence class**; README adversarial
  examples run out of the box; `decision record --contradiction` lists
  full-gate follow-ups; design-contract errors show expected types and the
  full checklist in one pass; a wrong study path is a path error; the business
  plan narrative drops 待填写 placeholders; import honors per-record
  provenance (`source` alias, `collected_at`); MCP accepts `query` as an
  alias of `need`. Domain packs gained software/SaaS terms.

## 2.18.1 — 2026-11-18

Review follow-ups from the 2026-11-17 golden-chain audit, rebased onto 2.18.0.

### Fixed

- **One validity rule for audit and delivery (A-1)**: `_evidence_summary` now
  reads through `load_evidence_store` (single load path, `is_qualified_evidence`
  semantics), so `check --stage decision` and `deliver --kind report` can no
  longer disagree on what counts as decision evidence. Only records registered
  in `evidence.jsonl` with a valid `evidence_level` are decision evidence;
  collecting is not having evidence. The rewritten A-1 tripwire asserts
  delivery basis ids are exactly the audit-accepted qualified set.
- **Delivery no longer overstates its basis (A-1)**: chain-cited ids that
  resolve to no qualified record are excluded from the basis line and surfaced
  as explicit `unresolved_evidence_ids`（不计入依据，审计判 unknown evidence）;
  the projection keeps the C-01-Lite qualification aggregation alongside.
- **Loop map verifies quotes verbatim (A2-1)**: quoted evidence is checked
  character-for-character against the collected record before it is trusted.
- **`validate_study` loads the CLI directly (A-4)**: breaking the cross-tree
  import cycle.

### Performance

- One `deliver` run loads the evidence store exactly once.
- jsonl reads parse once per content digest (A-3): unchanged files are not
  re-parsed within a process.

## 2.18.0 — 2026-11-18

This release publishes the decision surface and the write path underneath it:
`askovo decide` (one decision question tracked as a task, including
`decide delta --since latest-accepted`), the **Decision Brief** (`askovo brief`)
with PRD development acceptance, **incremental research** (`askovo delta`,
append-only `source id + updated_at` comparison), **A-07** canonical decision
write integrity (journalled accept, `askovo issues recover`, cross-process
lock), and the **C-01-Lite** minimal delegation projection on
`askovo decide status`.

It also ships the multi-platform collection line grown out of the golf-device
campaign: `askovo capture page` (CDP capture as a reviewed candidate, governed
by the same collect rule set), `askovo answer` (conclusions follow the reviewed
evidence), four new connectors (YouTube innertube, Kickstarter/Discord CDP,
arctic window) with a rotation scheduler, and the campaign experience compiled
into product surface — platform field notes (35) and strategies (14) as a
registry, runtime policies enforced by `cdp_strategy` guards, `analyze` field
completeness, and the 2026-11-17 postmortem as the campaign-level index.

The site also ships an English mirror of its six pages under `website/en/`,
with reciprocal `hreflang` and a sitemap entry for each.

### Engine integration for the postmortem: field completeness, membership gates, App Store route

Reviewed the 35 notes / 14 strategies for what belongs in the engine rather
than docs. Three rules earned engine surface; the rest stayed operator-level
because encoding them as fake runtime budgets would overclaim.

- `askovo analyze` now publishes `field_completeness` and `zero_rate_fields`
  for the join fields (`record_id`, `text`, `source_url`, `created_at`) and
  renders a "字段完整性（管线体检）" section. A 0% `record_id` is flagged as a
  pipeline bug; text/url/time can legitimately be absent for first-party or
  structured material and are reported for source-level review. This gives
  `field-preservation` a product surface instead of leaving it in the
  postmortem.
- The Discord collector gains `--list-channels`: one cell, one goto, a sidebar
  snapshot printed as JSON and no empty snapshot written. The
  "name the channels before scanning" rule is now a product command, not a
  prose suggestion.
- `capture page` refuses a Discord membership gate too (`membership_gated`, no
  candidate): the gate is a coverage gap, not evidence, and never something to
  work around.
- `connectors.cdp_strategy.detect_membership_gate` recognises the membership
  wall (Discord and generic community pages); the Discord collector stops with
  `membership_gated`, writes no empty snapshot and records the gap. The
  `join-is-not-access` strategy is now `enforcement: runtime`, bound to that
  helper in `runtime_policies.guards`, so `askovo doctor` fails if the guard
  disappears.
- `app_store` in `platform-catalog.json` now states that the customer-reviews
  RSS endpoint is retired, so platform planning stops recommending it; the
  browser-visible route remains unverified and is labelled as such.
- Left operator-level on purpose: classification coverage (a campaign counter,
  not an engine concept), single-writer for derived outputs (a local job
  concern), Instagram keyword/profile routing, Discord channel naming and vB5
  cross-link dedupe (each needs a specific collector that does not exist yet).
  The registry keeps them visible; no runtime field pretends to enforce them.
- `askovo platforms --platform <known-but-unranked>` now returns that source's
  notes/JSON instead of "unknown platform"; the App Store RSS retirement is
  reachable from the CLI even when app_store is outside the top-ranked set.
- Tests: `analyze` field-completeness rates and required-field flags, gate
  detection, the runtime guard binding and the known-unranked filter. Full
  suite: 645 tests green.

### Campaign postmortem becomes strategy: join is not access, buckets reconcile, fields survive

A full read of the 2026-11-17 golf-device campaign session (≈1,150 messages,
≈323k cleaned records) collected the lessons that were still prose after the
first registry pass. The pattern is consistent: the expensive failures were
access assumptions, silent data loss and multi-process collisions — not
selectors.

- Six new field notes (35 total): **Discord membership-gated history** (SGT,
  40,967 members: join succeeded, history stayed behind member verification —
  a coverage gap, never a gate to work around); **Discord channel-name
  targeting** (snapshot the sidebar once, rank by name, stop burning cells on
  rules/welcome/empty rooms); **Instagram keyword search over profile
  crawling** (`/explore/search/keyword/?q=` yields 3–8 posts/query while
  two-post profile cells timed out); **App Store RSS retired** (0 entries
  across variants; browser-visible comments API is the remaining route);
  **vB5 sidebar cross-links** (dedupe section threads by canonical href); and
  **silent normalized-field loss** (`author_hash` dropped by a positional
  mismatch; 0/16,226 Amazon dates were a parser field issue).
- Three new operator strategies (14 total): `join-is-not-access`,
  `classification-coverage` (every raw file maps into a bucket; Rapsodo/
  FlightScope 5,863 records had fallen outside every bucket and the "gap" was
  partly a classifier bug) and `field-preservation` (named-field conversion,
  golden record, 0% non-empty rate is a bug).
- Existing strategies refined from the same postmortem: single-writer now
  covers derived outputs and managed jobs (clean4 still writing when clean5
  started, then nohup residue); multilingual routing records that word choice
  dominates language (generic Japanese ≈3 posts vs `ゴルフスイング` 42);
  cell budget covers slow surfaces and one page per cell; goal counting
  reconciles raw → deduped → cleaned → classified; session health covers
  idle-open sessions and Instagram's account-level 24–72 h block risk.
- Note corrections: `vertical-forum-cloudflare` moves from channel_verified to
  verified (GolfWRX vB5 Equipment section reached 4,601 floors; MyGolfSpy blank);
  `discord-invite-rot` now distinguishes a bounced invite from a membership
  wall; `x-search-infinite-scroll-stall` keeps one search page per cell;
  `instagram-locale-keyword-grid` separates term yield from locale yield.
- Playbook: new platform quirks (membership walls, channel naming, IG keyword
  surface, App Store RSS, vB5 cross-links), a data-pipeline hygiene section
  (join keys, bucket reconciliation, nominal/deduped/cleaned counts), and
  run-hygiene rules (verify a background launch with `ps` and absolute paths;
  a browser lane stops when the agent turn ends).
- Docs: the English/Chinese field-note strategy tables and the platform index
  are regenerated from the registry; the new
  `docs/campaign-postmortem-20261117.md` indexes each incident to its note or
  strategy id (linked from the docs index); feature-status counts updated.
  Full suite: 637 tests green.

### CDP strategies become runtime policy: one guard, timeouts as circuit breakers

The campaign's CDP strategies used to live in three disconnected places — prose
in the registry, helper modules nothing called, and hand-rolled loops in each
collector. The 2026-11-17 close made the cost concrete: four Discord session
drops, and every one shared the same precursor — a timed-out/aborted operation
followed by continued driving. Equally fast but timeout-free navigation never
dropped; one drop arrived 40 minutes after the last operation with zero browser
contact. That is now one runtime layer instead of prose plus per-script logic:

- `assets/platform-field-notes.json` gains `runtime_policies`: per-platform
  budgets (`cadence_seconds`, `session_minutes`, `session_cooldown_minutes`,
  `timeout_cooldown_minutes`, `max_gotos_per_cell`, `budget_fraction`,
  `allow_reload`, `exclusive_modes`, `requires_session`, `challenge_policy`,
  `blank_render_status`) plus `guards`, which bind every runtime-enforced
  strategy to the helper that enforces it. Each strategy now declares
  `enforcement: runtime | operator`; `askovo doctor` fails when a runtime
  strategy has no guard, an operator strategy claims one, or a CDP platform
  cannot build a policy.
- `connectors/cdp_strategy.py` compiles the section into `RuntimePolicy` and
  `SessionGuard`: one goto per cell (`reload()` refused), timeout → circuit open
  for the cooldown (15 min), session time-box (Discord 40 min), mode exclusivity
  (messages/forum/invite; comments/posts), cell-budget headroom (Discord 60%,
  others 70%), page triage (challenge / not-found / blank render / content) and
  a persisted `askovo.cdp-session/1` journal. `--selftest` and `--policy
  <platform>` run offline.
- `sure_engine.CDPClient` gains a per-call timeout and marks the websocket torn
  after one: no read-on, no retry (`CDPTimeout` / `CDPTransportError`). A torn
  stream is a stop signal, not a transient error.
- `capture page` and `collect --cdp` share the triage: a blank 200 returns
  `blank_render` and writes no candidate/run, a timeout returns `cdp_timeout`
  with the cooldown, and both record the applied policy in
  `governance.runtime_policy` / the run manifest. `collect --cdp` also stops
  scrolling after two stale rounds instead of metronome-scrolling a page that
  is not producing.
- The Discord and Kickstarter collectors run under the guard: persisting the
  best harvest before stopping, writing `<out>.session.json`, and exiting 2 on
  timeout/circuit/session drop/blank render instead of retrying.
- `connectors/rotation.py` now takes cadence and the session requirement from
  the same registry for every platform the policy layer declares (explicit
  call arguments still win); archive-only routes (Reddit/YouTube) keep their
  field table. The scheduler and the collectors can no longer disagree about
  how fast a site may be hit.
- Engine surface: `platform_fit` attaches `runtime_policy` to every CDP
  platform (plan-level `runtime_policies` map), `askovo platforms "<need>"
  --policies` renders the enforced-budget table, `--json` carries the same
  data, and MCP `askovo_platforms` gains the matching `policies` flag.
- `askovo doctor` resolves registry artifact paths in an installed runtime too
  (`skills/askovo/...` maps onto the bundled `runtime/`), so a wheel doctor run
  no longer fails on field-note or strategy artifact paths.
- Docs: the playbook's anti-automation post-mortem is rewritten to the
  four-drop protocol (timeout circuit breaker, one goto per cell, no reload,
  mode exclusivity, 30–40 minute session box, deliberate logout); the
  field-note references (EN/ZH), capture/CLI/feature-status docs, connectors
  README, llms.txt, SKILL.md and both READMEs are in sync. Full suite: 635
  tests green.

### CDP studies become designable; error pages stop pretending to be evidence

Live-chain finding (2026-11-17): the catalog opened eight CDP platforms, but
six of them (kickstarter/bilibili/weibo blocked-only in the registry,
discord/instagram/tiktok absent) could never pass the study design gate —
`capture` accepted URLs no study was allowed to declare. Two fixes:

- First-party CDP transport declaration in `source_adapters.<platform>`:
  `connector_id=cdp-authorized-visible-page`,
  `access_basis=cdp_authorized_visible_page`,
  `collection_mode=authorized_visible_page`. Eligibility comes from the
  platform catalog (`cdp: true`, review current); the open-source connector
  registry still governs scripted collection exactly as before. A kickstarter
  study is now designable and its captures can enter evidence legally.
- `capture page` returns `page_not_found` and writes no candidate when the
  final page title reports a not-found/error state (404, "not found",
  "页面不存在"); it stops before the screenshot instead of minting a
  reviewable candidate out of an error page.
- Scaffolded canonical stores (`evidence.jsonl`, `gold-set.jsonl`) ship empty:
  the old two-line comment headers made a freshly scaffolded study fail its
  first `capture accept` with `INTERNAL_ERROR`, because canonical JSONL has no
  comments. A regression test now parses every template store through the
  strict reader.

### CDP platform contract alignment: catalog `cdp: true`, passive challenge wait

- The CDP capture allowlist is now explicitly tied to the platform catalog's
  `cdp: true` set (currently amazon/instagram/bilibili/weibo/kickstarter/
  discord/x/tiktok). The delivery contract lists the same eight; a test fails
  if the code allowlist, catalog and contract drift.
- A challenge page is no longer rejected at first sight: capture waits
  passively for the same browser session to clear it or a human to complete
  it, then proceeds; if the wait expires it stops before screenshot/write.
  It never solves, bypasses or reloads around the challenge.

### Multi-platform rotation strategy (stay under every site's frequency radar)

The campaign's answer to per-platform rate control is now product capability:
**alternate between platforms instead of raising any one site's frequency**.
A site can only measure its own request stream, so rotation lowers every site's
observed cadence while total throughput stays flat (or rises when render waits
overlap). The strategy layer records the invariants that make this safe to
automate, and `connectors/rotation.py` enforces them at runtime.

Registry (`assets/platform-field-notes.json`): a `strategies` section with 11
records — platform rotation, one tab per site, single-writer archive quota,
channel pivot (not identity), windowed search, session health/cooldown,
batch auto-relay, multilingual query routes, blank-render triage, cell budget
headroom, nominal-vs-deduped goal counting. Each record carries `when`,
`invariant`, `mechanism`, `platforms`, repo-relative artifacts, the runtime
helper and an honest verification status; the registry also absorbs the five
late field notes the campaign produced (X `since:/until:` windows, PullPush
commercial wall, archive-client contention, IAB blank-render stacks, YouTube
multilingual routes), now 29 notes with normalized repo-relative paths.

Engine surface: `platform_fit` attaches the applicable strategies to the plan
and to every recommended entry; `askovo platforms "<need>" --strategies`
renders the invariant table, `--json` carries the same data, and
`askovo doctor` gates the strategy layer (`collection-strategies`: required
fields, platform ids, artifacts, helper references, verification legend).
MCP `askovo_platforms` gains the matching `strategies` flag.

Runtime: `connectors/rotation.py` — `RotationScheduler` with per-site minimum
interval (`PlatformCooling`), classified cooldown through
`common.classify_backoff`, session-drop gate plus human re-login, daily quota,
fair round-robin (`plan_round`/`next_platform`), JSON resume (`save`/`load`)
and offline `--selftest`/`--plan`. Rotation never rotates identities, proxies,
keys or accounts, never bypasses a challenge, and records a blocked platform as
a gap.

Docs: reference `platform-field-notes.md` gains the strategy table; Chinese
`docs/platform-field-notes.md`, the CDP playbook ("Multi-platform rotation"),
connectors README §4d, CLI flags, `llms.txt` and the feature-status row are in
sync. Full suite: 591 tests green.

### Platform field notes: campaign experience becomes a product capability

Every platform limit the 2026-11 campaign hit now ships as data, not prose.
`skills/askovo/assets/platform-field-notes.json` records 24 field notes — one
restriction per note, with symptom, detector, field-verified solution,
verification status (`verified` / `partially_verified` / `login_verified` /
`channel_verified`), the repo-relative artifact and the runtime helper that
encodes the mechanism — for Reddit (Arctic Shift backoff, empty-window
honesty), YouTube (PO-token block, `commentEntityPayload`, relative time),
Kickstarter (Cloudflare, load-more expansion, reply threading), Discord
(sandboxed internal APIs, real-wheel lazy loading, anti-automation session
drops, forum cards, invite rot), X (infinite-scroll stall, reply density),
Instagram (comment ancestor chain, reel caption fallback, locale keyword
grids), TikTok (login verified), vertical forums (Cloudflare) and four
cross-platform rules (tab-binding rot, silent extractor failure, parallel
lanes, single-writer state). A note records the field and never an approval:
access permission stays in the platform catalog plus the study's scope,
adapter, Design gate and human ack.

Engine surface: `platform_fit` attaches each ranked platform's notes (cross-
platform practice included) to its entry, `askovo platforms "<need>"
--field-notes` renders the restriction/solution table, `--platform <id>`
filters to one catalog platform or source type, `--json` carries the same data,
and `askovo doctor` gates the registry (required fields, unique ids, legend
status, artifact paths, helper references, and a `cdp` flag that must match the
platform catalog). A note may cover a declared source type (`vertical_forum`)
or cross-platform practice (`*`); neither claims a catalog route, and the
pre-existing CDP entries (amazon / bilibili / weibo) deliberately carry no
field note.

Runtime guards extracted from the same experience: `connectors/common.py` gains
`classify_backoff` (429/403 reset waits, 422 slow-down retry, permanent stop),
`single_writer_state` (exclusive pid lock, live-owner stop, stale reclaim),
`parse_relative_time` (en/zh/ko/ja → approximate UTC with `date_precision`) and
`atomic_write_json`; new `connectors/cdp_runtime.py` provides passive
`wait_for_challenge_clear`, real `wheel_scroll`, `rebind_tab`,
`bounded_load_more` and `run_lanes` (parallel lanes with isolated failures and
a one-tab-per-site guard), plus an offline `--selftest`. The Kickstarter and
Discord CDP collectors now import these helpers instead of forking the logic.

### Multi-platform CDP collection + crawler methods from the golf-device campaign

The CDP exception now follows the platform catalog's `cdp: true` set
(currently amazon / instagram / bilibili / weibo / kickstarter / discord /
x / tiktok, up from the fixed four). Kickstarter moves blocked → limited via
authorized visible public pages; Discord joins the catalog; X and TikTok gain
the `cdp_visible_page` route alongside their APIs; YouTube stays API-only.
Semantics made explicit: challenges are only waited out passively or completed
by hand (never bypassed), login sessions are user-operated (no credentials
entered, read, or cookies exported), and a consistency test now locks the
runtime whitelist to the catalog set.

Four field-verified connectors collected into `scripts/connectors/` (from the
golf-device research campaign, 2026-11): `collect_arctic_windows.py` (windowed
Arctic Shift backfill with in-window cursor paging and resume),
`collect_youtube_innertube.py` (login-free innertube comments incl. the 2024+
`commentEntityPayload` shape, approximate dates flagged via
`date_precision`), `collect_cdp_kickstarter.py` (CDP visible pages, passive
Cloudflare wait, bounded load-more expansion, comments + creator updates) and
`collect_cdp_discord.py` (user-session CDP with real wheel events, slow
anti-automation cadence, per-round persistence, text + forum channels). The
CDP collectors reuse the engine's CDP client via importlib instead of forking
the transport.

New reference `references/cdp-collection-playbook.md` records the method:
channel decision tree (no-login API → CDP → paste → OCR), the Nov-2026 field
matrix, CDP operation patterns (login collaboration, passive challenge waits,
lazy-loading via real input events, the Discord anti-automation post-mortem
and corrected protocol, platform rotation), and crawler engineering rules
(classified backoff, resume state, bounded collection, empty-window honesty,
two-layer raw-JSON-then-envelope output). Platform references for YouTube,
Kickstarter, Reddit, X and the shared social adapters gained field-verified
notes; catalog limits/bias updated accordingly (yt-dlp PO-token blocks,
Cloudflare on direct fetches, Discord sandbox/storage constraints, invite
rot).

The playbook also records the last methods the campaign proved after the first
connector pass: **parallel lanes** (background archive processes plus a
two-tab browser pipeline for logged-in sites — per-site cadence stays flat
while render waits overlap, ≈55 s per cell for two sites), the **one-writer
per state file** rule (a stale duplicate collector doubles request rate and
corrupts resume state; verify by `ps` before restart), and two Instagram
quirks (reels break caption selectors — fall back to `og:description`; keyword
grids are locale-dependent, so queue per term × locale instead of assuming
paraphrase parity).

### Decision integrity: lexical research assistance is not a business go

`askovo answer` now reads only `02-data/evidence.jsonl` and separates
`lexical_projection` from `business_decision`. Option-keyword support counts,
including 3+ same-source E1 hits, can at most recommend `continue_research`.
A formal go/no-go is projected only through the canonical seven-node chain,
audited support and a named DecisionRecord; normalized-only records cannot
create an answer. This prevents lexical matches from being misrepresented as
seven-node scientific reasoning, causal evidence or commercial truth.

### Study onboarding: fill checklist, terminal-friendly check output, label fallback

`askovo do` now scaffolds `01-sources/fill-checklist.md` — an ordered,
hypothesis-only task list for `study.json` and the seven-node
`product-reasoning.json` (it invents no content and is not a second truth;
`product-reasoning.json` stays the machine source). `askovo check --format`
gains `text` (auto: text in a terminal, JSON when piped) so humans get the
failed checks plus the next step instead of a JSON wall. Delivered plans and
decision packages no longer read "产品类型：；阶段：" when `route.json` is
absent: labels fall back to the domain pack via `_study_labels`.
`deliver --strict` returns 1 on `audit_failed` while still writing the draft,
so automation can gate on it.

### Local golden-chain acceptance run (offline, 6/6 scenarios)

`tests/acceptance/golden_chain_local.py` drives the real pipeline end to end
and writes `docs/acceptance/golden-chain-local-20261117.{json,md}` with the
review §2.1 fields (user_intent / expected_terminal_state / real_side_effect /
receipt / observed_outcome / evidence_paths): paste → import → analyze →
answer; loopback fake-CDP fixture page + real macOS Vision OCR → `capture
accept` → answer (honest low-n continue_research with capture back-links);
opposite corpora flip the leading option; empty store → unanswerable + gap
list; scope/design/host/challenge rejections at the capture entrance; a
hand-appended capture row fails the evidence audit. The log grades evidence
honestly: synthetic corpora, local loopback fixture transport (not a real
browser), real local OCR; live external reads remain unverified.

### Governance hardening: capture = collect rule set, audit-checked review join, procurement preflight

- `capture page` is not a generic browser route: the CDP exception stays on
  the four approved platforms (amazon/instagram/bilibili/weibo) with
  default-port http(s), no credentials, an enabled per-study adapter, a
  current connector registry review, and a redirect that leaves the platform
  stops the capture. X/YouTube/arbitrary hosts are refused before any CDP
  I/O (`cdp_not_allowed`), and a challenge page stops before the screenshot.
- `capture accept` now requires an explicit `--evidence-level`, verifies the
  reviewed bytes are the captured bytes (schema/ack/platform/page+OCR+
  screenshot hashes), refuses accepted→reject flips, and writes the source
  plan inside the same journalled transaction. The CLI evidence audit calls
  `capture_review.validate_evidence_record` for every capture row, so a
  hand-appended OCR line can no longer bypass review. `deliver --kind plan`
  and `analyze` render the reviewed-capture back-link table (reviewer, URL,
  capture/screenshot refs, hashes).
- Paid live routes (x official API, app_store/google_play licensed
  providers) are stopped at planning and collection by a
  `requires_procurement` preflight: `terminal_state: BLOCKED_USER_INPUT`,
  registered `reason_code: INPUT_REQUIRED`, alternatives listed, and no
  transaction is ever executed.
- `docs/delivery-contract.json` (askovo.delivery-contract/1) now carries both
  vocabularies: the five delivery terminal states and the decision-outcome
  semantics (do/defer/do_not_do/decision_adopted), plus supported intents,
  candidate-input governance, review/delivery commands, exclusions, evidence
  requirements and the procurement branch.

### P0.1 delivery contract: machine-readable and shown at first interaction

`docs/delivery-contract.json` freezes the Askovo delivery contract
(askovo.delivery-contract/1): supported intents with entry commands, common
inputs, the five terminal states (DELIVERED / DELIVERED_WITH_GAP /
BLOCKED_USER_INPUT / UNSUPPORTED / FAILED_UNRESOLVED) with their meanings,
explicit exclusions (no publishing/ads/sales/collection, no physical/human/
road tests, no evidence-free market or payment conclusions, no challenge
bypass, no auto-promotion of candidates), the `requires_procurement` branch
(BLOCKED_USER_INPUT, alternatives listed, transaction never executed) and
the evidence requirements. Bare `askovo` now prints this contract summary
first (exit 2) instead of a bare usage error, and a test asserts the first
interaction mentions every terminal state, every supported intent and the
contract path — the boundary is seen before any capability list.

### P1 golden chain, step 2: `askovo answer` — evidence-following research answer

The golden chain's terminal projection (`04-findings/research-answer.json` +
`.md`). It reads `study.decision.question/options` and the reviewed evidence
store, tallies support per option using distinctive CJK-bigram/latin match
keys (bigrams shared by two options cannot distinguish anything and are
dropped), and emits `answer_status` (supported / supported_low_n / contested
/ inconclusive / unanswerable) plus a decision (`go` / `no_go` — the
status-quo option winning — / `continue_research` / `unanswerable`). Counter
records (claim_type=counter, control/substitute_rejector roles, E4-) are
tallied separately and are never outvoted by support count; `go` needs at
least three supporting records and zero counters. Every cited record keeps
its collection back-link (record id, source family, source_ref, capture id
and URL for captures). With no evidence — or evidence silent on every
option — the answer is `unanswerable` with a gap list (empty-store next
actions, unmet `decision.minimum_evidence`, missing required corpus roles),
never an invented conclusion. The command is a read-only projection: the
evidence store and `product-reasoning.json` stay the only truth.

### P1 golden chain, step 1: reviewed capture/paste registration into evidence

`askovo capture` becomes `page|list|accept|reject`. Acceptance is the only
bridge from a candidate into the canonical evidence store: a named human
(`--by`, `AUTH_REQUIRED` otherwise) appends exactly one record to
`02-data/evidence.jsonl` with full back-links (capture id, capture JSON,
URL, screenshot/OCR hashes). A visible page can only support E0/E1/E2 —
requesting E3+ is `POLICY_DENIED` because a page cannot prove acceptance or
payment. Acceptance registers **no demand judgment and no chain node**
(judgments stay human-authored), is idempotent, verifies the accepted join
(A-07 lesson), and writes the capture document + review trail as one
journalled `write_integrity` transaction; the `capture` source family is
declared in the source plan idempotently. `askovo import` gains the same
review semantics for pasted text: `--evidence-level` capped by evidence form
(self-report/behavior log ≤ E2, transactions ≤ E5), `--corpus-role`,
`--context-key`, idempotent source-family declaration, so the paste path no
longer produces audit-failing `unclassified` records.

Capture review now requires an explicit E0/E1/E2 choice, preserves page/OCR/
screenshot content and hashes plus reviewer/time, reuses import normalization,
and verifies the accepted source join in the evidence audit; generic `import`
cannot relabel a capture candidate as paste. `analyze`, `deliver --kind
analysis`, and `deliver --kind plan` carry the source back-links without
authoring judgments or business conclusions. Paid API/licensed-provider plan
and collect preflights stop with `terminal_state=BLOCKED_USER_INPUT`,
`requires_procurement=true`, user alternatives, and
`transaction_executed=false` (the frozen C-01 reason remains INPUT_REQUIRED).

### P0.4 unified capture governance + CDP page capture (candidate only)

`askovo capture` captures one user-authorized visible page through the local
CDP endpoint (page text + screenshot + optional macOS Vision OCR via
`scripts/ocr_image.swift`) into `01-sources/captures/` as a **candidate** — it
never registers evidence or touches the seven-node chain by itself. Governance
is unified with `collect` instead of opening a second, laxer collection
entrance: the Design gate must pass before capture starts, only the approved
amazon/instagram/bilibili/weibo hosts are eligible, the exact platform must be
listed in `study.scope.allowed_sources` with an enabled adapter and current
registry review, default-port/final-URL rules apply, challenge pages stop the
capture before screenshot or candidate writes, and the CDP endpoint stays
loopback-only. There is no generic-web, Reddit, X, or YouTube capture bypass.
See `docs/capture.md` for the full rule set.

### C-01-Lite minimal delegation projection

`askovo decide status` now also returns a `delegation` block with the eight
fields frozen in `ai输出/ovo-C01-Lite-最小委托契约-v1-20261115.md`
(task_id / task_state / next_actor / next_required_action /
blocked_reason_code / result_ref / authorization_scope / recovery_entry) plus a
one-line boundary. `task_state` uses the six-word C-01 vocabulary and
`next_actor` is normalised to human/agent/system; the older flat `state` and
`next_actor` fields are kept unchanged so existing consumers do not break.

### Added

- **A-07 canonical decision write integrity.** Accepting an issue candidate now
  writes the evidence store, `demand-judgments.json`, `product-reasoning.json`,
  the candidate document and the acceptance trail as one journalled transaction.
  A canonical file that cannot be parsed is refused with `INTERNAL_ERROR` before
  anything is written — the previous `except JSONDecodeError: []` fallback could
  silently rebuild an empty judgment array and destroy history. `askovo issues
  recover` reports or replays a journal left by an interrupted accept
  (`--apply`), an unrecoverable journal blocks every read and write entry with
  the completed/pending list, and a cross-process lock makes two concurrent
  accepts serialize instead of overwriting each other. Read errors are no longer
  silently skipped: `issue-imports.json` is parsed as the JSON document it is.

- **A-06: external research bridge safety boundary** (`askovo external-research`).
  Running a host adapter is the highest-privilege operation in the repository, so
  the subprocess boundary now lives in `external_bridge.py` and is enforced, not
  documented: the child environment is **built from an allowlist** (`PATH`,
  `HOME`, `LANG`, … plus an entry's explicit `extra_env` plus four `ASKOVO_*`
  context variables) instead of inheriting the parent environment (A29); only a
  command in the signed per-study registry `01-sources/external-research.json`
  may run, and its adapter SHA-256 must match, so a tampered adapter is refused
  (A30); stdout/stderr go to temp files with hard caps (256 KiB / 64 KiB) and an
  oversized run fails with `RATE_LIMITED` instead of being truncated into a
  success, while a caller can only lower the cap (A31); each run gets its own
  `ext-<utc>-<random>` id and writes `04-findings/external-research/<run_id>.json`
  with exclusive create, so two runs in the same second both survive (A32); the
  output path is resolved (symlinks included) and must stay inside the study
  (A30); and a URL stays `candidate` with `evidence_level: null` and
  `url_verification: not_attempted` — the bridge performs **no network access**
  and never promotes an evidence level (A33). Timeouts report
  `INDETERMINATE_EXTERNAL_ACTION` and must not be replayed. The run record
  captures the command, adapter hash, allowlisted env **keys** (never values),
  effective limits and boundary.
- **A-05: incremental research delta** (`askovo delta`). The same decision
  question keeps accumulating public issue material; `sync` compares an
  authorized local export with the latest snapshot by **source id + `updated_at`**
  and appends an immutable `04-findings/deltas/vNNN-<hash>/` version only when
  something changed. Older versions stay byte-identical, so a deleted or edited
  record keeps its previous content, hash and acquisition basis (A25); the
  append-only `index.jsonl` and `state.json` make the history auditable. A
  repeated sync is a no-op — no new version, untouched index, and a delta that
  says 无变化 (A24). Identity is normalised through A-03's `author_ref`, with
  `author_id` preferring the stable GitHub `user.id`, so an author rename is not
  a new observed user and a login-only rename becomes `identity_drift` instead of
  inflating the count (A26). `decision_delta.md` carries the four blocks — added
  evidence, affected canonical nodes with record references, counter-evidence
  impact, re-review recommendation — and a new counter-evidence only raises
  `needs_re_review`: the approved `DecisionSnapshot` stays read-only
  (`decision_record_mutated: false`) and `accepted` / `current` / `differences`
  spell out the current-vs-accepted gap (A27). An unreachable source still shows
  the last good snapshot, marked `stale` with `STALE_SOURCE`, the reason and the
  last success time (A28). `askovo decide delta --since latest-accepted` now
  returns the same document, replacing A-02's explicit refusal.
- **A-04: Decision Brief + PRD dev acceptance** (`askovo brief`). One page per
  decision question, projected read-only from `product-reasoning.json`,
  `demand-judgments.json`, `evidence.jsonl` and `decision_review`; it writes
  only `06-report/decision-brief.{json,md}` and a `source_fingerprint` over its
  four inputs, so canonical artifacts are never rewritten. The document keeps
  the PRD §5 `askovo.decision-brief/1` fields and the nine §2.3 sections
  (question/boundary/window/owner, recommendation, 2-5 uniform-dimension
  options, evidence and counter-evidence with source/date/context/qualification,
  limitations, rejected options, next cheapest validation action with owner and
  stop condition, PRD acceptance, four independent states). Gates: no evidence
  yields `hold` with an action and never a validated decision or an approval
  (A19); the acceptance checklist keeps the canonical `acceptance_conditions` /
  `acceptance_criteria` field names with
  `product-reasoning.json#chains/<id>/nodes/<node>` references and marks an
  empty checklist `undefined` instead of done (A20); counter-evidence sets
  `needs_re_review` + `decision_status: needs_review` and shows what it
  challenges without overwriting the previous recommendation (A21); a number
  missing its unit, time window or source is withheld and listed in
  `numbers_without_provenance` (A22); `research_facts` stay `null` with
  `invented_facts: []`, and `heuristic_score` is never a probability
  (`calibrated: false`) (A23). Broken references or drifted inputs mark the
  brief `stale` (`STALE_SOURCE`, `delivery_state: blocked`, `diagnostic_only`,
  exit 1) and leave only a diagnostic draft. `askovo decide brief` and
  `askovo decide result` now return the same document; `decide delta` stays with
  A-05.
- **A-03: issue -> user task / demand structuring** (`askovo issues`). A local
  authorized GitHub issue export becomes machine candidates and — only through a
  named human — canonical evidence. `import` snapshots the export
  (`02-data/raw/issues/`, SHA-256, acquisition basis, retention rule), reuses
  `sure_engine._normalize_platform_record` for `02-data/normalized.jsonl`, and
  declares the `github` source family in `01-sources/source-plan.csv` so the
  audit never sees evidence from an unplanned source. `extract` writes
  `04-findings/issue-candidates.json` with the thirteen PRD candidate fields
  plus claim kind, disposition, support/counter counts, snapshot provenance and
  an explicit `selection_bias`. Semantic rules live in code: one login with ten
  issues is one observed user and comments are not users (A13); a feature
  request caps at E1 and is refused as behaviour evidence with `POLICY_DENIED`
  (A14); no quotable body text stays `unverified` with a null span (A15); a
  deleted source keeps snapshot + hash + rights note and reports
  `snapshot_only` (A16); one counter-evidence yields `challenged` with
  `majority_wins: false` (A17); non-public rows are dropped and counted while
  snapshots are built from a field whitelist, so private content never reaches
  an artifact (A18). `accept` requires a named human, is idempotent, and writes
  one evidence record + one demand judgment + one product-reasoning chain plus
  an append-only `04-findings/issue-acceptance.jsonl` trail; `reject` records
  its reason. `LIVE_CONNECTOR_ENABLED` marks the future live-connector seam and
  stays False: no network, no API call.
- **A-02: one-question decide executor** (`askovo decide` + the
  `askovo_decide_*` MCP entry points). An `askovo.decision-task/1` document
  (PRD §2.2) now becomes a tracked task instead of a one-off prompt:
  `decide start` normalizes the input, binds or scaffolds the study, writes the
  research-loop plan and stops — **dry run by default**. Reading only happens
  with `--run` *and* a human `askovo loop authorize`; decide never authorizes,
  never calls `loop assess`, and a task without a declared owner and source
  stops at `needs_input` / `AUTH_REQUIRED` with executable import tasks (AC A6).
  The product state is a projection of the loop
  (`created → scoped → collecting → analyzed → review_required → brief_ready →
  delivered`, exceptions `needs_input|blocked|interrupted|cancelled`) and
  `delivered` never means `decision_approved`. `status` always returns the C-01
  §3 fields (`next_actor`, `next_required_action`, `blocked_reason_code`,
  `last_updated_at`, `has_pending_external_effect`, `artifact_refs`) plus
  `budget` and `gaps`; refusals carry stable reason codes (`INPUT_REQUIRED`,
  `AUTH_REQUIRED`, `UNSUPPORTED_SCOPE`, `POLICY_DENIED`, `ARTIFACT_PARTIAL`)
  and exit 2 instead of a look-alike success. `brief`/`result` write a
  `partial` Decision Brief that lists every gap and keeps
  `decision_state: not_approved` (AC A12). `authorization.max_records` becomes
  the loop envelope bound (AC A7); `cancel` stops all further reading with
  `POLICY_DENIED` (AC A8); identical input resumes the same task, study, plan
  and candidate set (AC A9, A11); an interrupted loop becomes `interrupted` and
  requires reconcile without replay (AC A10). Scaffolded studies copy their
  authorized export into `01-sources/authorized/` so the study owns the snapshot
  it cites. `decide review` / `decide delta` are explicit `UNSUPPORTED_SCOPE`
  stubs until A-04. MCP exposes `askovo_decide_start` /
  `askovo_decide_status` / `askovo_decide_result` on the same orchestration
  functions, so the CLI, Skill and MCP keep one behavior.

### Changed

- **BREAKING (A-06):** `askovo external-research --command "<arbitrary command>"`
  is no longer accepted by default. Only a command registered in
  `01-sources/external-research.json` (with `adapter`, `argv`, `sha256`,
  `access_basis`, `reviewed_at`, `reviewed_by`) may run. Migrate by registering
  the adapter, or add `--trusted-local` (still requires `--authorize`) for a
  one-off local workflow; its use is recorded in the run. The refusal JSON names
  the registry path and the required fields. Reason: PRD §3 A-06 requires a
  command allowlist / explicit signed path, which an arbitrary `--command` cannot
  provide. See `docs/external-bridge.md` §6.

### Changed

- **C-01 §3: `INPUT_DRIFT` is a detail code, not a reason code.**
  `decision_brief` put `INPUT_DRIFT` / `BROKEN_REFERENCE` on
  `stale_reasons[].code`, which reads like an eleventh entry in the C-01 error
  registry. The top-level `reason_code` is now always the registered
  `STALE_SOURCE`; the challenged/expired distinction moved to
  `stale_reasons[].detail_code` plus a top-level `input_drift: true`, so "the
  content changed under the same id" stays visible without extending the frozen
  vocabulary.

### Fixed

- **A-03: a counter-evidence record kept the supporter's provenance.** The
  canonical record written by `issues accept` for a counter-evidence item used
  `candidate["issue_ref"]` (the supporting issue, e.g. `github:o/r#1`) while its
  `record_id` and `text` came from the counter issue (`github:10009`), so an audit
  following `source_ref` landed on the wrong issue — worse than a dropped
  counter-evidence because it looked traceable. `counter_evidence[]` now carries
  each counter record's own `source_ref` / `author_ref` / `created_at` /
  `updated_at`, and `_counter_record()` writes those; the supporting record is
  pinned by a test too, so both branches of the same function family are covered.
- **A-lane integration: two staleness contradictions between tickets.**
  `decide brief` / `decide result` exited 0 on a `stale` brief while
  `askovo brief` exited 1 for the same document (A-04 introduced the
  "stale blocks delivery" exit-1 convention; A-02's task entry never adopted
  it), and `delta show` / `delta sync` reported `fresh` for a broken canonical
  reference while the brief reported `stale` / `delivery_state: blocked` (A-05
  derived freshness only from its own sync error). Both entries now share
  `decision_brief.stale_inputs()`: a projection over a broken chain is not
  current, on every entry and in every projection.
- **A-01: attention metrics no longer pass as commercial E5 evidence**
  (orthogonal evidence qualification). `docs/plan-evidence-check.md` graded the
  GitHub star baseline, the follower count and an internal precedent as E5,
  conflating "the number is real" with "it supports a
  paid/retention/repurchase conclusion". The E0–E5 contract is unchanged;
  `sure_engine` now derives three orthogonal display attributes per evidence
  record — `measurement_integrity`
  (confirmed_source|self_reported|unverified|conflicted), `behavior_kind`
  (statement|problem_behavior|solution_acceptance|commercial_intent|
  commercial_transaction|attention_metric) and the rule-derived
  `claim_eligibility` (problem|solution|commercial|descriptive_only|none).
  An API-verified star count qualifies as confirmed_source / attention_metric /
  descriptive_only and can never yield commercial E5 eligibility; an unverified
  or self-reported "already paid" statement gets no commercial eligibility and
  is marked for human review. Cross-dimension conflicts (e.g. an attention
  metric coded E5) surface as a `needs_requalification` flag in `askovo audit`
  output, decision review items and the delivery chat summary — original
  levels are never rewritten and legacy studies stay read-compatible. Copying
  one source into three records no longer raises the independent-source count
  (`independent_source_count`). The three misgraded rows in
  `docs/plan-evidence-check.md` are corrected to descriptive observations with
  a revision note; no historical study data is migrated.

### Tests

- 13 new regression tests (`tests/test_evidence_qualification.py`) freeze the
  counterexamples first (A1 verified star stays descriptive_only; A2
  unverified payment gets no commercial eligibility; A3 copied source does not
  raise independence; A4 legacy data stays read-only without silent promotion;
  A5 doc, auditor and delivery projection agree on the same record). Full
  suite: 300 passed.
- 18 new regression tests (`tests/test_decide_executor.py`) freeze AC A6–A12
  on synthetic fixtures only: dry run reads nothing, unsupported
  decision_type/source are refused without a fake task, missing question is
  `INPUT_REQUIRED`, identical input yields an identical task id and plan digest,
  missing authorization reads nothing, the orchestrator never self-authorizes or
  assesses, the state machine order holds, the record cap is never exceeded,
  cancel stops all reading, repeat start/resume does not duplicate imports,
  interrupted resume requires reconcile and recollects nothing, status carries
  the C-01 fields at every gate, the brief is `partial` and lists its gaps, and
  the MCP entries share the same orchestrator. Full suite: 318 passed.
- 33 new regression tests (`tests/test_issue_structuring.py`) freeze AC
  A13-A18 offline on synthetic GitHub issue exports: the thirteen PRD fields,
  the four claim kinds (never collapsed into one `type`), exact quote spans,
  same-author and same-issue comment accounting, login-only identity, separated
  maintainer feedback, duplicate-theme merging that keeps every source,
  deterministic re-extraction, feature-request caps, unverified-without-text,
  deleted-source snapshots, counter-evidence not outvoted, private-row and
  private-note containment, selection bias, human-only acceptance with an audit
  trail, idempotent acceptance and a passing audit afterwards. Full suite: 351
  passed.
- 29 new regression tests (`tests/test_decision_brief.py`) freeze AC A19-A23
  offline: the nine sections and PRD contract fields, 2-5 uniform-dimension
  options, four independent states, limitations covering sample/population/
  commercial gaps, read-only projection (canonical digests unchanged), JSON and
  Markdown from one document, hold-without-validation, traceable PRD acceptance
  with an undefined empty checklist, counter-evidence re-review that keeps the
  previous recommendation, numbers keeping unit/window/source and being withheld
  without them, null-is-not-zero, no invented interviews or rates, uncalibrated
  heuristic scores, the stale gate at exit 1 with a diagnostic draft, and
  `decide brief` sharing the same builder. Full suite: 381 passed.
- 25 new regression tests (`tests/test_research_delta.py`) freeze AC A24-A28
  offline: versioned first sync with the full `DecisionSnapshot` field set,
  no-op repeat sync, added/changed/deleted classification, deletion not asserted
  under changed filters, old versions byte-identical, deleted and edited records
  keeping their previous content, append-only index, content-addressed versions,
  stable-id rename not a new user, login-only rename recorded as drift,
  edit never becoming new evidence, the four delta blocks with record
  references, counter-evidence impact, deterministic digests, declaration-only
  approval, `needs_re_review` without mutating the approved record,
  current-vs-accepted differences, no accepted baseline, degraded read at
  `stale` with exit 1, authorization required, and `decide delta` sharing the
  same document. Full suite: 406 passed.
- 26 new regression tests (`tests/test_external_bridge.py`) freeze AC A29-A33
  against **real child processes** and temporary scripts (no mocks stand in for
  "we did not pass the variable"): an unauthorized parent secret is unreadable
  while `PATH` and `ASKOVO_*` are present, the allowlist (not the parent
  environment) defines the child view, `extra_env` must be registered explicitly
  and its value never reaches the run record, unregistered commands and tampered
  adapter hashes are `POLICY_DENIED`, `--trusted-local` needs `--authorize` and
  is recorded, oversized stdout/stderr fail with `RATE_LIMITED` and leave no
  record, caps can only be lowered, two same-second runs keep distinct ids and
  files, `..`/absolute/symlink output escapes are refused while an inside path is
  allowed, URLs stay candidates, a socket/`urlopen` trap proves no network is
  attempted, malformed and non-http payloads are refused, and the legacy
  `--command` path reports the migration hint. Full suite: 438 passed.
- 5 suite-integrity guard tests (`tests/test_suite_integrity.py`) make "silently
  skipped test" impossible to ship: every `tests/test_*.py` must collect exactly
  as many cases as it defines `def test_` (a mismatch names the module and the
  difference), a class defining `test_*` methods without inheriting
  `unittest.TestCase` is reported by name, `@unittest.skip*` decorators must be
  whitelisted with an optional-dependency reason, and a module-level
  `load_tests` / `setUpModule` / `tearDownModule` hook is flagged. Verified by
  deleting a base class: three assertions go red with precise messages. The
  guard caught the new integration file's own two missing bases immediately.
- 6 A-lane cross-ticket integration tests
  (`tests/test_askovo_decision_service_integration.py`) cover what single-ticket
  suites cannot: one lifecycle from dry start through the human gate, run,
  brief, delta sync and approval (product state never moves backwards, the brief
  stays `partial` with its gaps, brief and delta agree on `needs_re_review`, an
  approved DecisionSnapshot stays byte-identical); MCP `askovo_decide_*` and the
  `decide` CLI report the same task, state, reason code and next action; an A-06
  external adapter produces candidates that never reach the brief's evidence and
  never raise a level; and a deleted cited evidence record makes both the brief
  (blocked) and the delta (exit 1) stale. Full suite: 449 passed.
- 5 C-01 reason-registry contract tests (`tests/test_reason_code_contract.py`)
  freeze the ten-code vocabulary against
  `ai输出/ovo-C01-委托语义合同-v1-20261115.md` §3: sorted equality with
  `decide.REASON_CODES`, no duplicates and exactly ten entries (an eleventh code
  is a three-repository contract change), every refusal class defaulting inside
  the registry, a static scan proving no script emits a `reason_code` literal
  outside it, and `INPUT_DRIFT` / `BROKEN_REFERENCE` staying detail codes.
  Verified by injecting `SNEAKY_NEW_CODE`: two assertions go red with the
  offending values. Full suite: 461 passed.
- 1 more acceptance test pins per-record provenance: after accepting a challenged
  candidate, the counter record's `source_ref` / `author_ref` / `created_at` /
  `text` all describe the counter issue (and the supporting record describes its
  own), so an audit cannot follow `source_ref` to the wrong issue. On the
  previous implementation it fails with
  `counter source_ref points at 'github:owner/repo#1'`. Full suite: 462 passed.

### Fixed

- **Audit now enforces E2 for validated demand judgments.** `askovo audit`
  previously checked problem / solution / commercial chains, counter-evidence
  and context keys, but a `validated` judgment whose problem chain held only
  E1 spoken statements could still be reported as `supported`. The judgment
  verdict now requires at least one E2 observed-behavior record in the problem
  chain, matching the rule already enforced for product-reasoning need nodes.
  Regression test: `tests/test_askovo_cli.py::test_audit_flags_validated_claim_with_only_spoken_evidence`.

## 2.17.1 - 2026-11-14

### Fixed

- **PyPI wheel/sdist carried the fullstack sample**: `MANIFEST.in` did not list
  `examples/sample-study-fullstack`, so the sdist (and the wheel `python -m
  build` derives from it) shipped without it and `askovo demo --story
  fullstack` failed with exit 2 on installed packages. The directory is now
  declared in `MANIFEST.in`, and the CI packaging job runs
  `askovo demo --story fullstack` from the installed wheel as a regression
  gate. Local wheel-only builds had masked the sdist path.
- **Release workflow on Python-3.9-capable runners**: the `release` and
  `pypi-publish` jobs ran on `ubuntu-latest`, which since migrated to Ubuntu
  26.04 where EOL Python 3.9 cannot be provisioned ("version '3.9' was not
  found"); v2.17.0 was published via a `release/v2.17.0` backfill branch. Both
  jobs are now pinned to `ubuntu-22.04` on main (the validate matrix got the
  same pin in v2.17.0).

### Tests

- 287 tests pass locally; packaging CI additionally exercises the fullstack
  demo story from the installed wheel.

## 2.17.0 - 2026-11-14

### Added

- **Full-stack developer persona**: developers stepping into full-stack roles who
  now own product discovery and design are a first-class audience. The new
  `skills/askovo/references/fullstack-developer-playbook.md` translates research
  practice into engineering terms (bug report → pain evidence, failing test →
  `falsified_if`, logs → corpus, reproducible build → `context_key`), gives a
  community-corpus first run (GitHub issues / Hacker News / Reddit), points to
  the interview kit for a first user interview, covers working as a team of one,
  and lists engineer-specific anti-patterns ("I am the user", feature request ≠
  need, stars ≠ demand, shipping ≠ validating). SKILL.md, README (en/zh),
  docs/quickstart, docs/README and llms.txt now name this audience and link the
  playbook.
- **Persona-aware team recommendation**: `roles recommend` / `do` / `route`
  recognize 全栈/研发转型/独立开发/自己扛产品/full-stack/indie queries and add R26
  (product management) to the lean team with the labeled reason
  `任务触发：转型全栈研发的产品职责`; need discovery still leads with R09 and no
  new role family is introduced (the persona composes existing roles). The
  software domain pack gains `CLI`/`命令行`/`SDK` routing keywords so the canonical
  developer entry phrase ("给自己的 CLI 工具找值得做的方向") routes without `--domain`,
  and a router test now locks that routed `route`/`do` payloads expose the
  industry context and role team.
- **Fullstack demo story**: a second synthetic sample
  (`examples/sample-study-fullstack`, a local-first CLI log-triage study with
  the same 7-record evidence contract) ships beside the mobile sample;
  `askovo demo --story fullstack` runs it through the full audit. Both samples
  are bundled into the wheel, and both `delivery.audiences` lists now include
  `fullstack_developer`.
- **Persona-smooth routing**: when the domain gate blocks a persona query
  ("研发转全栈要自己挖需求"), the questions add a targeted hint (describe your
  product — CLI tool, open-source repo, SaaS, App — to auto-route); and when
  discovery and decision keywords tie, discovery leads, so "开源项目 issue
  很多，哪些值得做成功能" now gets an R09-led discovery team instead of a
  decision-only one (`discover` hints gain `issue`/`issues`; other ties keep
  declaration order).
- **PRD dev-view acceptance checklist**: `deliver --kind prd` now renders
  "PRD 需求与验收（开发视图）" — the feature node's `acceptance_conditions` and the
  product node's `acceptance_criteria` projected read-only as a copy-pasteable
  checkbox checklist with chain-node sources, plus scope/non-goals and
  per-capability lines. Explicit boundary: checked boxes never mean validated,
  engineering-approved or release-ready; acceptance changes go through the
  canonical chain first.
- `delivery.audiences` gains `fullstack_developer`; the engine contract and the
  study template stay in sync and the sync is now test-enforced.

### Tests

- 282 tests pass. New: template/engine audience-consistency check and a persona
  recommendation test (lean team, R26 with the persona reason, CLI parity).
  The hardcoded audience expectations in the `init` and `do` workspace tests
  now include `fullstack_developer`.

### Verification

- `python3 -m unittest discover -s tests` green (282).
- `askovo roles recommend "我是后端研发，转型全栈要自己挖掘用户需求和设计产品"
  --json` returns R09 (accountable) + R26 with the persona reason, lean scale.
- README quickstart (`askovo do … --dry-run`, `askovo demo`) unchanged and green.

## 2.16.1 - 2026-11-05

### Fixed

- **Opportunity map Markdown now renders items**: previously it always printed
  "current items: none" even when the JSON contained sourced entries. Items now
  show id, statement, status, evidence ids, counter-evidence and next test.

## 2.16.0 - 2026-11-05

### Changed

- **Discover studies scaffold the opportunity map automatically**: `askovo do`
  now writes `04-findings/opportunity-map.json` and `.md` when the routed mode is
  Discover, so the five-layer structure is part of the study rather than an
  optional afterthought. `askovo explore --force` remains available to rebuild
  it.

### Tests

- 279 tests pass.

## 2.15.0 - 2026-11-05

### Added

- **Opportunity space scaffold** (`askovo explore <study>`): writes
  `04-findings/opportunity-map.json` plus a readable Markdown version with five
  layers (market/alternatives, users/tasks, opportunity hypotheses, solution
  space, validation paths), an item schema and an explicit evidence boundary.
  It is a structure, not a finding; items start empty.
- **External research bridge** (`askovo external-research <study> --command …
  --authorize`): runs a host-provided research command (e.g. an isolated GPT
  Researcher adapter) and stores its output as candidate sources. Output must be
  a JSON object with http(s) source URLs; records stay `candidate`, with
  `evidence_level: null` and `review_required: true`. Askovo does not import the
  external framework or call its APIs.

### Tests

- 279 tests pass, including opportunity-map scaffolding and the external bridge
  (authorization required, candidates never auto-promoted).

## 2.14.0 - 2026-11-05

### Changed

- **Validate mode can hand off instead of scraping more**: when Validate ranks an
  experiment or external-evidence action first, `loop plan` records an
  `external_validation_task` (recommended action, reason, required
  authorization/participants) and excludes that gap from collection. `loop run`
  stops with `awaiting_external_validation` rather than substituting more public
  comments for a paid pilot or real delivery test.
- **Mode-specific planning**: Discover still favours collection, Optimize still
  favours local analysis; the new handoff only applies to Validate.

### Tests

- 277 tests pass, including the external-validation handoff case.

## 2.13.0 - 2026-11-05

### Changed

- **Research mode now drives the Research Loop**: `loop plan` reads `research_mode`
  and reweights collect/analyze/experiment/external-evidence candidates
  (Discover expands opportunity and substitute evidence; Validate prefers
  falsifying behaviour and external evidence; Optimize prefers local diagnosis).
  Mode weights only reorder candidates; authorization, evidence levels and
  semantic review are unchanged.
- **Task type beats product stage**: mode priority is now explicit mode > task
  text > explicit stage > keyword-inferred stage > default. An already-launched
  product researching a new market can stay in Discover even with
  `--stage postlaunch`.
- **Mode score is labelled as a heuristic**: the contract exposes `mode_score`,
  `score_basis` and `calibrated=false`; CLI output says it is not a probability.

### Tests

- 276 tests pass, including mode-weighted loop planning and updated priority
  cases.

## 2.12.0 - 2026-11-04

### Added

- **Research modes**: `askovo mode` and `route --json`'s `research_mode` now derive Discover/Validate/Optimize entry contracts with a rotated seven-node order and explicit upstream hypotheses, without waiving any node's evidence requirement.
- **Study persistence**: `askovo do` writes the `research_mode` contract into `study.json`, the study README and the research plan, so the entry node and upstream hypotheses stay visible after scaffolding.
- **Priority order**: explicit mode > explicit stage > text signals > keyword-inferred stage > default Discover; verbatim "值不值得" no longer forces Discover when the task is a validation request.

## 2.11.0 - 2026-11-04

### Added

- **Product-innovation role operating system**: a single catalog for 80 role
  families across 10 lifecycle areas, with responsibilities, KPI formulas and
  anti-gaming guardrails, input/action/output/gate SOPs, deliverable templates,
  handoffs and accountable-human boundaries.
- **Task-sized staffing and adaptive output**: infers decide/discover/define/
  design/validate/launch/operate/review from the product, goal, stage and task;
  selects a minimum sufficient team, lists deferred roles and reasons, and sets
  an output contract for primary/supporting deliverables, format, length,
  audience, structure, evidence display, visual forms and industry expression.
  `--task`/`--scale` override the inference; workplans generate only the task's
  output templates by default (`--all-templates` expands).
- **Ten industry context overlays**: consumer software, enterprise SaaS,
  AI-native, smart/traditional hardware, CPG, apparel/home, industrial robotics,
  automotive and medical/health. Overlays change stakeholders, design inputs,
  prototypes, verification and professional gates without forking the five SURE
  base-domain packs or the seven-node schema.
- **`askovo roles` / `askovo_roles`**: list/search/show, team recommendation,
  deliverable-template rendering and study workbench scaffolding through the
  same CLI command function. `do/route` expose the industry and role plan;
  `roles scaffold` explicitly and atomically writes an orchestration-only workbench.
- **Reference-based workplans**: catalog/industry hashes, role/SOP/KPI/template
  references, null KPI baselines/targets, bound chain/node/edge targets and
  separate work status. Empty chains are rejected, multi-chain studies require
  an explicit chain, stateful workplans cannot be force-overwritten, and
  scaffolding verifies that reasoning, judgments and evidence stay unchanged.
- **Role and lifecycle delivery**: flat `06-report/role-Rxx-Dyy.md` and
  `lifecycle-board.md` are bound read-only projections, not template-authored
  findings. Workplan/catalog/industry freshness and reference validity join full
  audit and decision review; legacy studies without a workplan stay compatible.
- **Role documentation and validation**: Chinese operating-system guide,
  English Agent protocol, README/CLI/Skill guidance, catalog completeness checks
  in `doctor`, and CLI/MCP/industry/scaffold regressions.

### Boundaries

- Role SOP completion does not assign evidence levels or validate demand;
  value, usability, engineering, safety/compliance/clinical and production
  validation remain separate. Templates and role workplans never become a
  second market, requirements, product or business truth. Commercial KPI targets
  require canonical `business.success_metrics` references.

### Verification

- The merged catalog contains 80 exact role families, 340 KPI definitions, 517
  SOP steps, 257 deliverable templates and 1,859 template sections; `doctor`
  validates all role/lifecycle/industry references and base-domain mappings.
- `python3 -m unittest discover -s tests`: **254 tests pass** on Python 3.9.
- Wheel and sdist build plus `twine check` pass. A non-editable wheel installed
  outside the source tree passes `doctor`, `demo`, MCP tool discovery, role
  scaffold, role delivery and lifecycle delivery on Python 3.9.6.
- No real online collection, professional approval or external publication was
  performed; generated studies and reports remained in temporary directories.

## 2.10.0 - 2026-11-04

Depth release: research actions now have an independent stop gate, executable
offline analysis, and a DecisionRecord that can make a substantive revision on
trusted contradictory evidence.

### Added

- **Independent StopDecision** (`research_loop.py`): `stop` no longer participates
  in the positive action-utility score. It ranks first only when all three
  explicit declarations hold: evidence is sufficient for the decision, remaining
  unknowns cannot change it, and continued research value is below its cost/risk.
  The criteria, basis refs, rationale and restart condition remain visible; a
  missing or contrary declaration makes stop ineligible.
- **Executable offline analysis**: for `unwritten_node` / `claim_needs_decision`
  gaps with existing local normalized/evidence JSONL, the analyze candidate is
  preferred and executable through the same CLI/MCP loop. It reuses
  `analyze_study`, writes an input-fingerprinted result and
  `04-findings/loop-executions.json`, and records `open → analyzed` with human
  semantic revision still required. No network, experiment or external send;
  canonical chain and judgments are not rewritten.
- **Adversarial DecisionRecord revision** (`decision_review.py`): registered,
  same-context evidence with provenance and a pre-recorded `contradicts` or
  counter-evidence mapping can create a new decision version. Without a human
  replacement it deterministically applies a safe `hold`, reopens
  chain/product/business for validation, lowers confidence one ordinal step
  (including `very-low`) and replaces the current recommendation with an explicit
  safe fallback. `--recommendation` is only an optional human override. Evidence
  IDs without a contradiction mapping are rejected.
- **Replayable revision history**: before/after recommendations, confidence,
  evidence relations, snapshots and change-log refs are retained; new evidence
  is not promoted into a demand judgment, validated node or causal state.
- **Release hardening**: release tags must descend from `main` and match
  `VERSION`; full tests run inside the release job; CODEOWNERS added.

### Verification

- `python3 -m unittest discover -s tests`: **238 tests pass** on Python 3.9 and
  3.11 (3.11 skips 2 optional-dependency tests).
- A1/A2/A3 focused regressions, replay and MCP paths pass.
- `py_compile` and `git diff --check` pass.
- No real online collection, experiment or external send was performed.

## 2.9.0 - 2026-11-04

Research action selection, explicit method boundaries, versioned decisions and a
single machine/chat delivery projection.

### Added

- **Next-best research action**: every gap, including `unwritten_node` and
  `actionable:false`, produces `collect`, `analyze`, `experiment`,
  `request_external_evidence` and `stop` candidates. The loop ranks them by
  expected uncertainty reduction, relative cost and decision-changing potential
  with a transparent formula; candidates never auto-execute and never mark a
  judgment `validated`.
- **Method choice projection**: route, `method-choice.json`, study plans and
  action candidates carry research question → sample formation mechanism →
  suitable method → conclusion boundary. Convenience samples cannot estimate
  population rates, interviews cannot size a market, and public comments cannot
  prove payment. Quote/delivery experiments record recruitment frame, exposure,
  response, acceptance, paid/delivered and churn bias fields.
- **Versioned DecisionRecord**: `askovo decision record/list/replay` and the
  `askovo_decision` MCP tool store hypothesis, candidate actions, basis,
  observations, revisions, next action, decision maker and read-only chain
  snapshots inside canonical `04-findings/product-reasoning.json`. Replay shows
  version differences and current drift without creating a second truth.
- **Unified `chat_summary` for `deliver`**: every kind and error result carries
  decision, basis, actions, costs/boundaries, unknowns, input fingerprint,
  freshness, reproduce command and rendered text. `fresh`, `stale`,
  `no_artifact` and `audit_failed` remain distinct.
- **MCP delivery compatibility**: machine-readable JSON stays the first content
  item for 2.8.0 compatibility; the same human-readable summary follows.

### Changed

- **Source-family wording**: “multiple source families observed” replaces
  claims of independent observation. Different source-family strings are not
  treated as proof of independence.
- Research-loop status and reports expose the action ranking and why an action
  cannot be executed automatically.

### Fixed

- Public commercial gaps no longer default to more comment collection when a
  real quote, paid pilot or delivery experiment is the decisive next step.
- Delivery freshness and audit failures are reported explicitly instead of
  implying a current artifact exists.

### Verification

- `python3 -m unittest discover -s tests`: **229 tests pass** (216 baseline +
  13 new P0 regression tests).
- `git diff --check` passes.

## 2.8.0 - 2026-11-03

Business Plan projection, the data-first narrative, and the multi-chain analysis fixes.

### Added

- **Business Plan (`askovo deliver --kind plan` → `06-report/plan.md`)**: the business-user default view of the same seven-node chain — nine business sections (方案导读 / 目标场景 / 目标用户 / 痛点 / 需求 / 产品特性 / 产品形态 / 商业与 GTM / 风险与下一步) rendered in business language. Every judgment carries a deterministic **数据基础** line (sources · corpus size · time window, computed from `02-data/evidence.jsonl`) and **来自语料的声音** (verbatim user excerpts, falling back honestly to coded 典型情况); sections without collected data say so plainly. Evidence codes (E0–E5) and raw statuses appear only in the closing 研究方法档案, never in the narrative body. Registered across CLI, MCP (`askovo_deliver`), and the router (`业务方案` keyword).
- **Evidence-strength markers (●◐○) in the Business Plan**: every judgment and every chain roll-up now carries a deterministic strength marker (node-aware levels: see Fixed) — ● 已观察到 (≥2 observed-level records from ≥2 source families), ◐ 有线索 (E1+ material that has not met the ● bar), ○ 假设 (no E1+ record yet; includes nodes backed only by E4- counter behavior). Absorbed from the hand-written prototype; computed only from the records a node cites, never hand-set. The exact rule and thresholds live in the 研究方法档案; the narrative body stays free of evidence codes.
- Tests: `--kind plan` rendering (nine sections, data-basis lines, voices, body free of engine tokens, boundary footer) and the MCP round-trip; three-tier strength markers with the body/archive vocabulary split.
- **Data-driven business reasoning in the Business Plan**: each node section now carries a 数据读出 line computed from the records it cites (observed-level share, platform count, money/proportion mentions); the plan opens with a 推理主线 paragraph threading scene → user → pain → need → capability → product → revenue from short fields; the 商业与 GTM section extracts up to five 金额与比例线索 from the cited records. All values are deterministic projections, never hand-set numbers.
- **`--kind analysis` cross-tab**: adds a 来源 × 用途 table so the analysis shows not just totals but which platform carries which kind of record.
- **结论与推进建议 in the Business Plan**: `--kind plan` now opens with a deterministic decision block — 判断依据, 先做哪一段, 为什么是这段特性, 为什么是这个形态, 先卖给谁, 怎么收钱, 30 天验证, 过关线, 失败线, 明确不做, 结论强度与成立前提 — projected from the same chain (feature/product/business nodes plus `next_test` / `failure_condition`). The 方案导读 also carries a 语料画像 (source, year and corpus-role distribution) with an explicit "not population shares" reading note.
- **Feature capabilities (`feature.capabilities`)**: an optional array of `{name, what, solves, proof}` on the feature node, validated structurally, scaffolded in new studies and rendered as 逐条特性 in the Business Plan — each capability says what it does, which pain it answers and what the evidence is. `askovo review` adds a `reasoning_depth` item that warns when a capability or node rationale is missing.
- **Corpus analysis deliverable (`askovo deliver --kind analysis` → `06-report/analysis.md`)**: deterministic funnel (raw → screened → coded → cited), source/year/role distributions, per-node coverage and strength, concentration and duplicate groups, counter-evidence and a can/cannot-answer split. Registered across CLI, MCP (`askovo_deliver kind=analysis`) and docs.
- Tests: analysis deliverable content, capability rendering and validation failure, MCP analysis round-trip, review depth item.

### Fixed

- **`analyze` reads canonical evidence**: without a `text` column the CLI produced an empty descriptive analysis (unknown types, zero average length, no terms or matches). It now falls back to `text_excerpt`, derives a coarse `claim_type` from the evidence level when absent (E0 context / E1–E2 need / E3 acceptance / E4+–E5 commercial / E4- counter) and falls back `evidence_form` to `corpus_role`.
- **Multi-chain conclusions**: the Business Plan only rendered the first chain's 结论与推进建议. It now renders a cross-chain comparison table plus one conclusion block per chain; detailed sections 2–8 render once for the priority chain (other chains stay in the comparison table and section 9).
- **Report decision section**: `deliver --kind report` left “产品决策” as empty placeholders. It now fills chain state, strength, recommendation, next test and failure line, and states explicitly when no chain is `decided`; the method/sample line uses the collection funnel.
- **Cumulative funnel**: `deliver --kind analysis` counted only the local `02-data/raw` directory. It now reads `01-sources/collection-summary.json` (`raw_records`, `screened_records`) for multi-wave or merged corpora, falling back to local raw files.
- **Duplicate sources**: the evidence gate only compared text hashes, so the same post could be coded twice under different ids. It now rejects duplicate `source_url` citations, reports `source_duplicate_rate`, and honours `quality_gates.max_source_duplicate_rate` (default 0).
- **Node-aware strength markers**: business nodes counted E1/E2 counter-evidence as observed (● even with no commercial evidence); feature/product did the same with complaints. Business now counts only E4+/E5 and feature/product only E3+, so counter-evidence cannot inflate the marker.
- **Report risk section**: the combined report now fills 反证、缺口与下一步 with each chain's alternatives, counter-evidence excerpts, gaps, next test and failure line instead of leaving three empty bullets.
- **Chain render boundary**: `askovo chain` now writes a 边界 footer into `06-report/product-reasoning.md`.
- **Plan retrofit (`askovo plan --force`)**: `plan` can now run against an existing study and writes a reviewable proposal under `01-sources/plan-proposal/` (`plan-proposal.json`, `source-plan.proposed.csv`, `tasks.proposed.md`). It never overwrites `study.json`, `source-plan.csv` or route templates; a non-empty directory without `study.json` is still refused.
- **MCP plan parity**: `askovo_plan` exposes `force`; the MCP handler and CLI share the same proposal path.
- **Unit-economics boundary**: `askovo economics` now closes `unit-economics.md` with a 边界 section so the projection cannot be read as commercial proof.
- Tests: eight regression tests cover `analyze` schema fallbacks, multi-chain conclusions, report decision/risk fill, cumulative funnel, duplicate `source_url` rejection, node-aware strength, and the chain boundary.

### Changed

- **Data-first narrative**: SKILL.md, both READMEs, AGENTS.md, llms.txt and docs/ now lead with the business promise — bring a product/market question, get a business plan built on collected data (frame → collection plan → collect → analyze → judge → `deliver --kind plan`), with evidence grading repositioned as the quality engine under the hood plus an explicit expression rule for business-facing deliverables (business logic as the subject, judgments tied to data basis, engine vocabulary confined to the method archive).
- `askovo-discover` closes with `deliver --kind plan`; the Decision Package remains the decision-side deep-dive for validate/decide.

## 2.7.0 - 2026-11-02

Research loop: collected material no longer counts as a closed gap.

### Added

- **Gap lifecycle** (`open → collected → analyzed → resolved / unresolvable`) stored per gap key in `research-loop.json`. A candidate record only advances a gap to `collected`; only a named operator's assessment can close it. Loop state written by older versions falls back to `collected` from candidates, never to `resolved`.
- **Typed analysis action**: `build_actions` emits `analyze` before further collection for `collected` gaps. The deterministic executor writes `04-findings/loop-analysis/<gap>.json` (record count, platforms, duplicate ids, samples, `analysis_version`, `input_fingerprint`, explicit boundary) and consumes no collection budget. Re-running the same input fingerprint reuses the existing artifact instead of re-analyzing; analyses are counted separately in `totals.analyses`. Analysis never grades evidence, judges support/counter-evidence or closes a gap.
- **`askovo loop assess`**: the only path from `analyzed` to `resolved`/`unresolvable`. Requires a named operator; `resolved` requires at least one evidence reference (checked against `02-data/evidence.jsonl` when present), `unresolvable` requires a recorded reason. Evaluations are appended to `research-loop.json` and `04-findings/loop-evaluations.json`; an optional `--hypothesis` id must exist in `study.hypotheses`.
- **`askovo loop map`**: validates host-supplied evidence mappings (record id must be a collected candidate, hypothesis id must be declared in `study.json`, stance is `supports`/`contradicts`/`contextual`, quote must be verbatim). Writes `04-findings/loop-mappings.json`. A mapping only carries provenance; it is never an evidence level or a judgment status.
- **`askovo loop advise`**: a deterministic, read-only summary of reviewer-supplied mappings per analyzed gap (`insufficient` / `resolved_candidate` / `unresolvable_candidate` / `conflicted`). It never closes a gap, assigns an evidence level or edits a judgment; `loop assess` remains the only close path.
- **Typed planner decision** recorded per round and exposed as `last_decision`: `continue_collecting` / `analyze_existing` / `request_external_evidence` / `stop_with_reason`.
- **New stop reasons** `awaiting_analysis` and redefined `awaiting_semantic_review` (analyzed gaps awaiting assessment), plus `gaps.resolved/open/collected/analyzed/unresolvable` counters and an `awaiting_assessment` report field.

### Changed

- `_covered_keys` now means *resolved* gaps; the previous "a candidate exists, therefore covered" inference is removed.
- `loop report` adds a gap-state line and a "待人工评估" section that names the exact `loop assess` command; `loop status` reports evaluation counts and the evaluations path.
- MCP still cannot authorize and deliberately cannot `assess` or `map`; semantic closure stays a named human CLI action.

### Tests

- Golden-case coverage: collect → `analyzed` (never auto-`resolved`), assessment requires evidence/reason, evaluation artifact written, report lists gaps awaiting assessment.

## 2.6.0 — 2026-11-01

First published release since v2.4.1. It carries the prepared 2.5.0 Decision
Package work (documented below) plus the research loop and the decision review.

### Added

- **Research Loop** (`askovo loop plan|authorize|run|status|report`): gap-driven rounds that turn `askovo audit` verdicts into collection actions, execute them inside an authorized envelope, re-audit after every round and stop with a review-ready summary. Gaps cover `exceeds_evidence`, `open_claim`, `missing_counter`, `node_without_evidence`, `unwritten_node`, `claim_needs_decision`, `source_concentration`, `missing_corpus_role` and `blocked_source`; queries are composed deterministically from the claim title or node statement plus an intent hint (no model call).
- The loop only collects from platforms in `study.scope.allowed_sources` that the catalog does not block and that have an enabled bundled adapter or a declared offline fixture (`study.research_loop.fixtures`, path constrained to the study). The authorization envelope binds the platform set, per-action cap and round/record budgets; changing the envelope invalidates the authorization. Interrupted actions stop the run as `interrupted_run` and require inspection.
- Collected records become **candidates** in `04-findings/loop-candidates.json` with `proposed_evidence_level: null`; they never enter audit counts, judgments or `validated` status. `05-audit/research-loop-summary.md` separates verified (audit-supported) claims, open hypotheses, blocked/unverifiable items and next actions.
- **Decision review** (`askovo review`): deterministic quality items over one study — audit gate, per-claim evidence verdicts, decision readiness (question, owner, deadline, options, minimum evidence, decided chains, business gate), falsifiability (`falsified_if`, `next_test`, gaps, alternative explanations), bias (minimum records, source concentration, duplicates, corpus roles, time window) and deliverable freshness (`06-report/*.md` mtime vs latest evidence, boundary section). Writes `05-audit/decision-review.json` and `.md`; exit 1 only when a `fail` item exists. It never decides, scores business success or replaces review.
- **Deeper descriptive analysis**: `askovo analyze` now reports segment counts by platform/claim type/evidence form/corpus role with `low_n` flags, an evidence-level distribution, and source-time-window coverage (`outside_window`), all descriptive with no significance or causal test.
- **Research Run** (`askovo research plan/authorize/run/status`): executes a bounded, machine-readable action list supplied by the Skill/agent. Every action is bound to a platform allowed in `study.scope.allowed_sources`, a reasoning node and an action-list hash; fixtures must stay inside the study; `run` requires the Design gate and stops on the first blocked action. State is `04-findings/research-run.json`; optional `--analyze` runs the descriptive analysis only.
- Nested business evidence is now audited: `segments[].evidence_ids`, `pricing[].evidence_ids` and `change_log[].reason_evidence_ids` must exist, share the chain `context_key`, and belong to the linked demand judgment under their schema-specific roles.
- MCP parity: `askovo_research_loop` (plan/status/report/run; never authorizes) and `askovo_review`; `askovo_audit` now exposes the shared `audit_payload()` used by the loop.
- `docs/open-source-integrations.md` records the cross-product integration ledger: Docling/invoice2data/Playwright are optional or existing dependencies; Stagehand/Midscene remain operator-supplied providers; no upstream fork was created.

### Changed

- `deliver` runs a fresh full audit through the CLI/MCP path instead of trusting an old `05-audit/audit.json`; Decision Packages show an audit-failure banner, and `signoff` is blocked without a passing audit and an existing product-reasoning chain.
- Decision Package option comparison uses one field set for every candidate (readiness, evidence count, counter-evidence, business gate, resource commitment, prioritization, gaps, next test) and does not compute a composite score.
- Interruption/evidence handling hardened with regression coverage; the bilingual README keeps English as the repo default with a full Chinese mirror (`README.zh-CN.md`).

### Validation

- 181 tests pass, including gap detection, envelope tamper rejection, unauthorized-run refusal, Design-gate refusal before any record is written, platform-without-adapter blocking, candidate/report generation, MCP authorization refusal, decision-review fail/warn items, nested-evidence negatives, fresh-audit delivery and signoff refusal.

## 2.5.0 — 2026-10-31

### Added

- **Decision Package (`askovo deliver --kind decision`)**: `06-report/decision-package.md` renders five decision-side views from the same seven-node chain and demand judgments — Opportunity Map (chain readiness, prioritization), Evidence Graph (per-node evidence ids with E0–E5 levels, counter-evidence, judgment link), Options & Trade-offs (multi-chain comparison; a single chain is stated as such, never dressed up as a comparison), Decision Memo (only `decided` chains: prioritization, business gate, confidence bounds, rejected/deprioritized reasons, delivery/outcome/causal states kept separate; degrades to a gap list without a decided chain), and Validation Backlog (gaps, needs-validation nodes, cheapest decision-changing test). Zero new facts: every field is a projection of `04-findings/`; MRD/PRD/BRD/ops remain its market/requirements/business/operations views. MCP `askovo_deliver` gains the `decision` kind.
- **Task entries in the Skill**: `askovo-discover` / `askovo-validate` / `askovo-decide` map the three recurring task shapes onto the existing modes and the Decision Package sections — one skill, one entry, never separate installs.
- README repositioned: a full "research question → decision result" walkthrough (sample study → chain → Decision Package excerpt) now leads; five-domain and MRD/PRD/BRD tables stay as the support layer; first-focus domains stated (AI software, developer tools, smart hardware). Free/commercial boundary wording unchanged.

### Validation

- 150 tests pass, including Decision Package section structure/order, evidence-id traceability against `evidence.jsonl`, no-decided-chain degradation, and MCP `kind=decision` dispatch.

## 2.4.1 — 2026-10-31

### Fixed

- `deliver --kind signoff` crashed on a freshly initialized study: the template `evidence.jsonl` starts with `#` comment lines and the sign-off page parsed every line as JSON. Non-JSON lines are now skipped; regression test covers the fresh-init path.


## 2.4.0 — 2026-10-31

### Added

- **F2 boundary audit (`askovo boundary`)**: deterministic lexical Added/Missing/Inflated lists between a requirements doc and an AI-produced doc. Items are traceable to `file:line`; the three lists are candidate deviations for human review, never error verdicts. Thresholds are tunable; report lands in `06-report/boundary-audit.md`. Derived from the dogfood study's PRD feature derivation (evidence-anchored: R42/R43/R50).
- **F3 stakeholder sign-off page (`askovo deliver --kind signoff`)**: one page per chain — conclusion summary, per-node judgment with evidence-level distribution (E1×n/E2×n), unverified assumptions, boundary statement, review-status counts, and blank signature rows. Nothing on the page upgrades evidence status.
- **F4 verification cost log (`askovo cost`)**: per-task manual minutes with an optional no-tool baseline; `report` outputs arithmetic totals and the baseline/actual ratio with an explicit not-a-productivity-proof boundary.
- MCP parity: `askovo_boundary` and `askovo_cost` tools, `signoff` added to `askovo_deliver`.

### Validation

- 146 tests pass, including planted Added/Missing detection, sign-off page content assertions, and cost log/ratio arithmetic.


## 2.3.0 — 2026-10-31

### Added

- **Hard minimum for the pain→need inference**: a validated `need` node must now cite at least one E2 record (observed substitute, workaround, or failure). Stated pain alone (E1) keeps the node at `needs-validation` — words are a signal, observed effort is a stronger one. Protocol docs (product-reasoning, research-protocol, SKILL) and the Chinese README/data-contract state the same rule.
- **PSM chain anchoring**: `askovo psm` stamps the owning `study_id` into the report header, and `askovo check` emits a `pricing_psm_link` warning (never a fail) when `06-report/pricing-psm.md` exists without a `business.pricing` entry citing PSM or a registered E4- record, so the projection cannot silently float outside the chain.
- **Cross-node reference resolution**: `segments[].user_refs` and `change_log[].affected_refs` must now resolve as `CHAIN_ID.node` against the chains in the file; dangling references fail the check instead of passing as opaque strings. The human-review checklist now also names the judgment↔chain phrasing seam (the judgment stays the canonical demand-side wording; no machine check compares free text).

### Fixed

- The bundled sample study duplicated the user node's `role` and `statement` text verbatim; the role is now a concise label, as the schema intends.

### Validation

- 140 tests pass, including the need-E2 gate, both PSM anchor cases, and unresolved-ref rejection for segments and change logs.


## 2.2.0 — 2026-10-31

### Added

- **First-class dataset stages**: `askovo label <dir>` / `askovo build <dir>` map an analysis project to `config/taxonomy.json` plus `data/raw → data/processed` defaults; explicitly passed flags win and everything else is passed through verbatim. MCP gains the `askovo_stage` forwarder. The layering is unchanged: rule labels are candidate discovery, evidence still requires human gold review.
- **Business-node support commands**: `askovo economics` renders a deterministic unit-economics projection (numeric, unit-matched, source-referenced inputs only; cost-like sums are name-based and labeled indicative; null means unknown, never zero) and `askovo psm --input <csv>` renders a van Westendorp price-sensitivity projection (PMC/OPP/IDP/PME plus the acceptable range, with invalid-ordering rows rejected). PSM is stated intent, not paid behavior; neither output validates the business node by itself. Both are exposed as MCP tools (`askovo_economics`, `askovo_psm`).
- **Connector registry expansion (2026-10-31 review)**: five new pinned decisions — `HackerNews/API` supported (official API); `google-play-scraper`, `app-store-scraper` (undocumented store/amp-api endpoints), `bilibili-API-collect` (archived after the 2026-01 legal notice to the maintainer), and `dataabc/weibo-search` (no declared license, terms-prohibited route) all blocked with reasons. `connectors --platform` choices now derive from the registry itself; app-store reviews are documented as export/licensed-provider only.
- **Automated release workflow**: pushing a `v*` tag — or a `release/vX.Y.Z` recovery branch for an already-published tag — builds wheel/sdist from the exact tag, runs `twine check` plus isolated-venv smoke, and creates the GitHub Release with CHANGELOG notes and SHA-256 checksums.

### Fixed

- Version single-sourcing: the sample study's `method_version` follows `VERSION` again; the CI gate had failed on every push since the 2.1.0 bump.
- The MCP stage forwarder now captures child-process output instead of letting it corrupt the JSON-RPC stream.

### Validation

- 135 tests pass on Python 3.9, covering first-class stages, unit-economics/PSM projections, the expanded registry, and the existing gates.


## 2.1.0 — 2026-10-31

### Added

- **Product and business reasoning chain**: `do` scaffolds and `askovo chain` renders 场景→用户→痛点→需求→特性→产品→商业 for product managers, user researchers, user operations, and market/requirements/business analysis. Every node has statement/rationale/status/evidence/assumptions; features include alternatives, products include scope/non-goals, and business includes market boundary, segments, payer, price/cost/unit-economics inputs, metrics, and a resource gate. Legacy six-node chains stay readable; new studies scaffold schema 2.0 with supporting delivery/outcome/causal states, alternative explanations, prioritization, human review, and a change log.
- **Three analysis workflows and projections**: market research/analysis → MRD, requirements research/analysis → PRD, business analysis → BRD. `deliver --kind mrd/prd/brd` renders these from one chain; BRD is the business analysis output, not a parallel workstream. Added role/responsibility and source-backed methodology coverage.
- **Reasoning/evidence join and decision states**: chain nodes may cite only evidence registered in their linked demand judgment and context; business nodes use commercial/counter evidence. `decided` records a product/business choice; independent delivery/outcome/causal states require release/metric/experiment references and cannot be inferred from E3/E5.
- **Role projections and methodology**: chain-led PM memo/report, UXR `research-status.md`, user-operations `user-ops.md`, business metrics in the tracker, and populated postlaunch tracking rows share one semantic source. Added researched methodology for five domains, senior UXR, user operations, and market/requirements/business analysis.
- **Guides and templates**: new Chinese guides `docs/product-reasoning.md`（产品与商业推理主链）、`docs/product-methodology.md`、`docs/business-analysis.md` and the English skill reference `references/product-reasoning.md`; MRD/PRD/BRD and interview-kit templates are chain-led; the bundled sample study ships a filled seven-node chain.

### Changed

- **Canonical repository live**: the GitHub rename to `roy-tong/askovo` completed — old URLs redirect and metadata/topics are updated.
- **Manifest text**: `askovo chain` help, the MCP `askovo_chain` description, and the `docs/cli.md` command table now cover all seven nodes and every public command.
- **Packaging metadata**: description and keywords state the scene-to-business positioning for PM/research/ops/analysis roles.

### Fixed

- Validation: 119 tests pass on Python 3.9, including seven-node business, market-estimate discipline, MRD/BRD projections and legacy six-node compatibility; a dedicated 24-case product-reasoning suite was added. Wheel/sdist pass twine and isolated wheel smoke; Python 3.10–3.12 remain covered by the CI matrix.


## 2.0.1 — 2026-10-30

### Added

- **Research integrity**: `validated` judgments and every cited evidence record must share a `context_key`; real collection now enforces the Design gate, `scope.allowed_sources`, and adapter enablement across CLI, MCP, and queue run.
- **Collection contract**: raw source envelopes, normalized projections, canonical run manifests, platform-scoped ID/text-hash dedup, conflict reporting, and attempt-specific queue run IDs.
- **Policy gates**: connector `policy_watch.recheck_by` now produces machine-enforced `review_expired` states in doctor, plan, and collection. Reddit has a limited 2026-10-30 review and a 2026-12-31 Devvit migration re-review deadline.
- **Release health**: contribution/AI policy, security policy, Contributor Covenant 3.0, Issue Forms, PR template, `RELEASING.md`, Python 3.9–3.12 CI, and non-editable wheel verification.
- **Regression coverage**: core and auxiliary negative tests for gates, context mismatch, stale reports, queue ownership/rate slots, CDP URL boundaries, formula injection, workbook sampling/gold gates, connector startup, and Amazon dataset pinning.

### Changed

- **Canonical repository**: GitHub and raw-content URLs now use `roy-tong/askovo`; the pre-2.0 entries below retain their historical SURE names and commands. The remote rename and metadata update are external release steps.
- **CDP boundary**: limited to authorized visible pages on amazon/instagram/bilibili/weibo with loopback-only debugging, approved default-port HTTP(S) targets, no redirects, same-port WebSockets, bounded frames/responses, and handshake verification. X/YouTube use official APIs only. Collection run IDs are unique and writes refuse collisions.
- **Queue reliability**: owner-checked completion, heartbeat renewal, lease-loss cancellation before collection/artifact writes, atomically reserved rate slots, and attempt-specific run IDs.
- **Collection safety**: source-plan scaffolding now matches the audit schema; plan quotas allocate exact totals and all validation happens before workspace writes; next commands shell-quote untrusted text.
- **Optional tools**: HN/PullPush require explicit config and User-Agent; Amazon HF uses `trust_remote_code=False`, an immutable reviewed dataset revision, and SHA-256 fallback IDs. Core remains stdlib-only; openpyxl/datasets are optional tool dependencies.
- **Spreadsheet outputs**: source-controlled CSV/XLSX cells are formula-escaped, workbook snapshots hash full record content, small pools are retained, and empty gold reviews fail an enabled agreement gate.
- **Packaging**: removed the obsolete duplicate MCP server, preserved console arguments, expanded metadata and sdist contents, and ignored generated study state/reports/credentials.

### Fixed

- English bare requests, strict MCP boolean handling, missing `askovo-mcp --tools` forwarding, stale/non-full report reuse, missing-evidence report crashes, manifest count aggregation, cross-platform ID collisions, same-platform text duplicates, and incomplete package help.
- Auxiliary connector import failures, Amazon process-random IDs, small-workbook sampling, and empty-gold agreement bypasses.
- Legacy Reddit exact day boundaries, candidate-signal document-frequency scoring, and CSV-only workbook generation without openpyxl.
- Validation: 95 tests pass on Python 3.9 and 3.12; wheel/sdist pass twine and isolated installation on both versions.


## 2.0.0 — 2026-10-30

- **Brand rename**: the product is now **Askovo**; `askovo` is the CLI, Python package, Skill and MCP server. SURE (Structured User Research with Evidence) remains the underlying research engine (`sure_engine.py`), not the outward product name.
- **Logo**: added `assets/brand/askovo-logo.png`; README uses the Askovo wordmark and the line “Ask better. Decide with evidence.”
- **Breaking surfaces**: `sure` / `sure-mcp` scripts and `sure_*` MCP tools are replaced by `askovo` / `askovo-mcp` and `askovo_*` tools. Old `sure` command is not installed by this package.
- **Runtime**: `skills/askovo/scripts/askovo.py` (CLI) + `sure_engine.py` (research logic) + `askovo_mcp.py` (MCP). Wheel bundles the runtime under `askovo/runtime`.
- **Env vars**: Reddit credentials are `ASKOVO_REDDIT_CLIENT_ID`, `ASKOVO_REDDIT_CLIENT_SECRET`, `ASKOVO_REDDIT_USER_AGENT`.
- **Version**: 2.0.0. The earlier SURE 1.x history remains below.
- Tests: 55 (all passing after rename).


## 1.14.0 — 2026-10-30

- **CDP transport**: minimal stdlib WebSocket client for Chrome DevTools Protocol; `collect --cdp-url --url --ack-terms` captures only visible page text from an authorized browser session. Challenge/robot pages stop the run. Enabled for amazon, instagram, x, youtube, bilibili and weibo; blocked platforms remain blocked.
- **Durable queue**: SQLite-backed jobs with leases, worker pool, retries/backoff, expired-lease recovery, per-platform rate limiting and persisted status. Commands: `sure queue init/add/run/status/retry`.
- **Concurrency fixes**: unique run IDs per job, cross-process append lock, dedup under lock, CDP row dedup.
- **Packaging**: wheel now bundles the runtime (`skills/` assets, templates and sample) under `sure_research/runtime`; `sure` and `sure-mcp` work after a normal wheel install, not only editable.
- **MCP**: `sure_queue_add/run/status`; `sure_collect` gains `cdp_url`, `url`, `ack_terms`.
- **Docs**: CDP terms boundary, queue operations, 23 platforms/sources.
- Tests: 55 (queue concurrency/retry/lease, CDP frame/terms gate, plus v1.13 router/platform suites).


## 1.13.0 — 2026-10-30

- **Single entry**: `sure "<request>"` (bare shorthand) or `sure do "<request>"` routes software / hardware / consumer / automotive / mobile requests to a method pack, lifecycle stage, claim types, risk gate and platform preview; `route` is read-only. No per-domain installs or forked protocols.
- **Method catalog + domain packs**: 32 methods and five packs under `assets/`; `sure methods`, `sure catalog`, `sure domains` expose them.
- **Platform radar**: `sure platforms` ranks 22 platforms/sources by data availability, access mode, evidence fit, bulk capability, bias and legal limits; `supported` / `limited` / `blocked` are explicit.
- **Collection runtime**: `sure collect` supports GitHub Search API, Reddit Data API and local JSONL/CSV fixtures; writes raw records, normalized records and a run manifest; blocked platforms return exit 3, never a bypass.
- **Normalized analysis**: `sure analyze` dedups and describes platform/time/claim/form distributions, candidate terms and question matches; descriptive only, no prevalence or causality.
- **Instruments and delivery**: `sure instruments`, `sure codebook`, `sure deliver` generate interview/observation/test kits, six-claim codebooks, memo/report/PRD/tracker outputs.
- **Safety gate**: high-risk requests return exit 4 until a human acknowledges; `--ack-risk` is never implied.
- **MCP**: new tools `sure_route`, `sure_do`, `sure_platforms`, `sure_collect`, `sure_analyze`, `sure_instruments`, `sure_codebook`, `sure_deliver`, `sure_methods`, `sure_domains`.
- **Docs**: README, quickstart, concepts, modes, CLI, data contract, connectors, troubleshooting updated for the single-entry design.
- Tests: 47 (bare shorthand, router, safety gate, platform ranking, authorized exports, fixture collection, analysis, delivery, MCP).


## 1.12.0 — 2026-10-29

- **Packaging**: added `pyproject.toml`, `sure_research` entry package, and `sure` / `sure-mcp` console scripts. `pipx install --editable .` now exposes the CLI; `sure --version`, `sure doctor`, and `sure demo` work from any directory.
- **Single version source**: added `VERSION`; the CLI, MCP `serverInfo`, and the study template read it. `plan` writes the current version into `study.json`; `audit` warns when an existing study records a different one. Removed the hardcoded `SURE 1.6` template value and `SERVER_VERSION = "1.9.0"`.
- **`sure audit`**: new command that runs all gates, computes deterministic signals, and returns per-claim verdicts — `supported`, `exceeds_evidence`, `open`, `rejected`, `deprioritized` — with reasons, gaps, and next actions. Writes `05-audit/audit.json` and `audit.md`. `--claim` filters to one claim; exit code 1 means a claim exceeds its evidence.
- **`sure demo`**: moved into the core CLI (no longer shim-only), so `python3 skills/user-demand-research/scripts/sure.py demo` works without installation.
- **MCP**: added the `sure_audit` tool; `sure mcp` starts the stdio server without an absolute path. `serverInfo.version` now follows `VERSION`.
- **Docs**: new `docs/` set — quickstart, concepts, modes, CLI reference, data contract, connectors, troubleshooting. README first screen now leads with the 30-second demo and the audit/plan entry choice.
- **Skill install**: added `scripts/install-skill.sh` (symlink, idempotent) and documented `sure mcp` / `npx skills add`.
- **CI**: verifies the single version source, rejects hardcoded versions in the template/MCP, and smoke-tests packaging (`pip install -e .`, `sure doctor`, `sure demo`).
- Tests: 32 (was 26), covering audit verdicts, claim filtering, version injection, and the template placeholder.


## 1.11.0 — 2026-10-02

- Added `skills/user-demand-research/templates/` with two judgment-layer template groups in Chinese, distilled from completed research projects (高尔夫智能设备调研, 脑机接口调研, 大人糖, 灵泷视界) with synthetic examples only — no real customer or company names:
  - `templates/integration-docs/` (B-5): the research-layer → integration-layer document set — 文档地图, BRD, MRD, PRD, 缺口审计 (with the research-layer backlink mechanism: forward source tags plus a per-chapter gap/falsifier/trigger audit table), 定价研究, 关键五问 — plus a runbook covering growth order (map → MRD → PRD → BRD → audit → pricing/questions), hypothesis-state vs mature-state trimming, quality checks, and layer-sync rules.
  - `templates/interview-kit/` (A-6): the interview research package — outline generation (opening-script design, probe trees, a hypothesis→question mapping table), conclusion-first minutes with timestamped evidence citations, a hypothesis-validation ledger with status-transition and single-instance rules, and a digestion runbook chaining recordings through the local bilibili-transcript-pipeline (v0.3.0+ local-audio ASR stage, reused as-is) into segmented transcripts, minutes, evidence records, and archival.
- SKILL.md now points Synthesize/fieldwork work at the two template runbooks (one sentence added to the mode-selection paragraph).
- Added `skills/user-demand-research/scripts/stages/`: a first-party dataset-pipeline toolbox consolidated from four finished research projects (Tiiny 用户研究, AI眼镜用户研究, 泛具身用户研究, 灵泷视界/用户研究), project-agnostic and documented in its own README (Chinese, per repo convention). It covers everything after collection: `import_feedback_export.py` (external exports → raw-record contract; the AI眼镜/灵泷 variants were byte-identical), `label_feedback.py` (rule labeling over taxonomy dimensions), `build_primary_dataset.py` (dedup, quality/relevance floors, counter-evidence control buckets, month-inverse weights; AI眼镜 base), `build_month_balanced_dataset.py` (month/platform-month/source-family-month caps; 灵泷 base), `extract_candidate_signals.py` (灵泷 code-noise-stripping cleaner + 泛具身 thread/platform/month ranking with a discriminative background filter, pandas dropped), `export_metadata_detail.py`, and `audit_workbook.py` (泛具身 spot-check sampling + styled openpyxl workbook as the base; deterministic seeded sampling with input snapshot hashes and verdict columns from the BCI manual-review flow; concentration warnings from AI眼镜 `audit_dataset_quality.py`; an optional codebook-coverage sheet from 大人糖 `audit_codebook_coverage.py`). Every domain rule table (label dimensions, product terms, relevance vocabulary, sample buckets, control buckets, quality-penalty overrides, signal stopwords, export columns, import aliases) moved into one taxonomy JSON config (`taxonomy.example.json`); matching is CJK-aware word-boundary (灵泷 evolution). Standard library only except openpyxl for the audit workbook; JSONL and JSONL.gz both supported throughout the data/raw → data/processed contract. Added a thin `sure.py stage <name> [args…]` forwarder to the stage scripts (choices-validated, exit code passthrough; no core behavior touched). The stages produce candidate labels and analysis views only — gold-set calibration and E-level evidence stay with `check`/`signals` and the Skill protocol.
- Added `collect_hn.py` (Hacker News via the Algolia public endpoint) and `collect_pullpush_reddit.py` (PullPush Reddit backup source) to `connectors/`, harvested from the byte-identical Tiiny/AI眼镜/泛具身 project copies; the project-side duplicates were removed with migration pointers left in each project `scripts/README.md`, making this directory the sole upstream for those collectors.


## 1.10.0 — 2026-09-21

- Added `skills/user-demand-research/scripts/connectors/`: a first-party collection/cleaning toolbox consolidated from finished research projects (脑机接口调研, Tiiny 用户研究), project-agnostic and documented in its own README (Chinese, per repo convention): a merged two-generation legacy Reddit archive collector (sub-window slicing, shard support, rate-limit backoff, whole-route 404 blacklist, effective `--start`, month range derived from CLI instead of hardcoded years), the Tiiny `common.py` schema/quality family plus its Arctic Shift cursor collector, Amazon Reviews 2023 HF-streaming and manifest scripts, a concurrent Range downloader, and a reusable `clean_screen_corpus.py` stage (PII scrubbing, stable derived ids, dedup, envelope output, state.json resume, audit). Hardcoded SALT/User-Agent/window constants became CLI arguments. The tools are deliberately NOT registered in `assets/open-source-connectors.json`; the toolbox README records why (first-party scripts have no upstream revision to pin, and enabling the non-official archive route is a four-gate review decision, not a side effect of collecting tools).

## 1.9.0 — 2026-08-27

- Added unnamed-experience research (命名前研究) for frontier products without settled vocabulary, with the grounding reference covering edge-language mining, substitute-behavior archaeology (E2 demand fossils), psychophysical dimension mapping, cross-domain literature anchors, and first-principles derivation.
- Added `sure.py plan --mode unnamed-experience`: copies lexicon and experience-space templates, adds Phase 0 grounding tasks, and records a 3–5× raw-to-clean intake estimate alongside the sample target.
- Added `sure.py lexicon`: per-term and per-grounding-path yield, acceptance-association proxy, demand-fossil count, zero-yield terms, and a stock-corpus sufficiency verdict (`--min-per-term`; exit 1 = insufficient, a collection instruction).
- Added the `lexicon_grounding` design gate: at least 5 retained terms across at least 2 grounding paths; experience-space.csv required when the psychophysical path is used.
- Evidence records gained optional `lexicon_terms` and `grounding_path` fields; the report gained a 命名前研究信号 section; MCP gained the `sure_lexicon` tool.

## 1.8.0 — 2026-08-27

- Added agent-discovery layer: repository `llms.txt` (stable raw index for agents) and `AGENTS.md` (working rules for coding agents inside the repo).
- Added `instructions` to the MCP initialize response so MCP clients receive the plan → check → collect → signals → report workflow, exit-code semantics, and hard boundaries without reading the repo first.
- Added an "Agent 接入速查" block at the top of the README with one-line capability framing and the four machine-readable entry points.
- Expanded the Skill description triggers (研究计划生成、调研报告、批量反馈挖掘).

## 1.7.0 — 2026-08-27

- Added `scripts/sure_mcp.py`: a standard-library-only MCP stdio server exposing `sure_plan`, `sure_init`, `sure_check`, `sure_signals`, `sure_report`, `sure_connectors`, and `sure_platform_map` as MCP tools for MCP-first clients (Claude Code, ZCode, Cursor, Cline, and similar).
- Tool results embed the CLI exit codes so agents can distinguish success, a failed gate (1), and no-feasible-platform (3) from usage errors (2).
- Documented the three integration paths (Skill for judgment, CLI for scripting, MCP for tool-native agents) with registration snippets for common clients.
- Added MCP protocol tests (initialize, tools/list, tools/call, invalid-params handling); 22 tests total.

## 1.6.0 — 2026-08-27

- Added `sure.py plan`: turns a research goal, region, sample size, and platform types into a study workspace with platform feasibility, sample quotas, scaled route targets, a feasibility report, and a collection task list; exits visibly when no requested platform has an enabled connector.
- Added `assets/platform-map.json` mapping regions (cn/overseas/global) and platform types to concrete platforms resolved against the connector registry.
- Added `sure.py signals`: deterministic corpus signals (level/role distributions, role × level matrix, source-family concentration, duplicate rate, time spread, chain readiness, gate deltas) written to `04-findings/signals.json`.
- Added `sure.py report`: assembles a Chinese research-status report into `06-report/report.md` from the study contract, source plan, manifests, signals, judgments, and blocked routes, keeping a visible failure banner until the full check passes.
- Added `06-report/` to the study template and documented the plan → collect → signals → report pipeline in the Skill, runbook, and README.

## 1.5.0 — 2026-08-27

- Replaced commercial research providers and seller/merchant APIs with a machine-readable registry of reviewed GitHub open-source connectors.
- Added separate code-license, platform-access, data-rights, and research-eligibility gates; a permissive repository license no longer implies a usable data route.
- Added supported official-API clients for Reddit (PRAW), X (Tweepy), and YouTube (Google API Python Client), plus a historical-only Amazon Reviews 2023 route.
- Preserved `snscrape`, `twikit`, unofficial YouTube downloaders, JD/Taobao scrapers, and KSInsights as blocked negative reviews with pinned commits and reasons.
- Added `sure.py connectors`, connector selection validation, run/connector provenance in platform evidence, and a standard collection-manifest contract.
- Recorded Reddit's 2026 public Data API transition: existing apps must register by 2026-09-30, new self-service access is closed, and the Devvit migration sets a `recheck_by` date on the PRAW entry.
- Added Amazon, JD, Taobao/Tmall, and Kickstarter route templates and audits; unsupported live routes now fail visibly instead of switching to a commercial or authenticated workaround.

## 1.3.0 — 2026-08-27

- Added the first platform-neutral social-media adapter layer with runbooks and route templates for Reddit, X, and YouTube.
- This release's broad tool-market survey was removed and superseded by the OSS-only connector registry in 1.5.0.
- Added optional CLI gates for Reddit subreddit/thread concentration, X conversation/day/repost concentration, and YouTube channel/video concentration, comment hierarchy, content status, and refresh deadlines.
- Added platform-specific access, policy-review, retention, original-source, and AI-summary controls to the starter study contract.
- Added repeatable `sure.py init --platform reddit|x|youtube` flags that enable adapters and copy editable route matrices into a new study.
- Documented that X reposts are E0 distribution signals, YouTube comment-thread responses may omit replies, and platform engagement metrics do not raise evidence levels.

## 1.2.0 — 2026-08-26

- Split the public material into a human learning path, an installable Agent Skill, and a deterministic local CLI while keeping one evidence model.
- Added `sure.py init` and stage-specific `design`, `evidence`, and `full` checks with JSON and Markdown audit reports.
- Added a standard study directory, machine-readable source plan, evidence index, codebook, demand judgments, and inter-Agent handoff contract.
- Replaced the translated “opportunity card” wording with demand judgments and explicit status/evidence gates.
- Expanded the synthetic sample into all five corpus roles with problem, solution, commercial/behavioral, and counter-evidence.
- Added tests for initialization, non-overwrite behavior, duplicate evidence, false validation, report generation, and the legacy validator wrapper.

## 1.1.0 — 2026-08-14

- Renamed the repository-facing product to `User Demand Research` and the canonical Skill to `user-demand-research`; SURE now expands clearly to Structured User Research with Evidence.
- Added a no-network synthetic sample study and deterministic validator for research contracts, evidence records, opportunity cards, and three-chain validation.
- Rebuilt the README around the task, first success, evidence gates, and explicit inference boundaries.
- Added CI tests for both a passing study and a false validation claim.

## 1.0.1 — 2026-08-12

- Separated untrusted source content from Agent control instructions.
- Added explicit prompt-injection handling for comments, transcripts, exports, and other third-party research data.

## 1.0.0 — 2026-08-12

- Published SURE in the standard `skills/scene-user-demand-research` layout for cross-agent discovery.
- Aligned the public README with the Skill's actual E0–E5 evidence model.
- Added direct `gh skill` and skills.sh installation paths, an Agent input/output contract, and privacy-safe measurement boundaries.

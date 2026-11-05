# Changelog

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

<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center">
  <b>English</b> | <a href="README.zh-CN.md">简体中文</a>
</p>

# Askovo

**Bring a product or market question, get back a business plan — built on collected data, not invented judgments.**

Askovo is built for product managers, user researchers, and business analysts. The default run: ① frame the question as a seven-node hypothesis canvas, ② design the data-collection plan (platforms, queries, quotas), ③ collect a large corpus through permitted routes, ④ turn the data into scene/user/pain/need/feature/product/GTM judgments, ⑤ render the **Business Plan** (`askovo deliver --kind plan`) — every judgment showing its data basis (sources, corpus size, time window) and user voices from the corpus, in business language. MRD/PRD/BRD and the Decision Package remain projections of the same chain for analyst and decision-side readers.

CLI, Skill, and MCP surfaces are live today. The host agent can author the action list, or `askovo loop` derives rounds from audit gaps inside an authorized envelope; the executor runs only what was authorized. Source gaps and human semantic review are kept explicit, never hidden. See [capability status and trade-offs](docs/feature-status.md) (Chinese).

> **scene → user → pain → need → feature → product → business**

Data collection, descriptive analysis, interviews, experiments, evidence grading, and platform connectors are supporting steps only: they validate a node or an inference edge — they never substitute for the product and business reasoning itself.

Quality is enforced under the hood: every conclusion carries an internal evidence grade, and when a conclusion outruns its evidence, `askovo audit` says so outright (exit code 1 can gate CI). In business-facing deliverables those grades stay in the method archive — the narrative is the business logic itself, with "no collected data yet" flags where a judgment still waits for data.

[Website](https://roy-tong.github.io/Askovo/) · [Quickstart](docs/quickstart.md) · [Product & business reasoning chain](docs/product-reasoning.md) · [Role methodology](docs/product-methodology.md) · [Platforms & connectors](docs/connectors.md)

[![Agent Skill](https://img.shields.io/badge/Agent_Skill-Askovo-111111)](skills/askovo/SKILL.md)
[![CI](https://github.com/roy-tong/askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/askovo/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## Proof it works in 30 seconds

```bash
pipx install askovo
askovo do "home security camera false alerts at night, want to validate the prototype" --domain hardware --dry-run
askovo demo
askovo decision --help   # versioned decisions, safe-hold adversarial revisions and replay
```

No `pipx`? Use a virtualenv and the same published PyPI package:

```bash
python3 -m venv .venv && .venv/bin/pip install askovo
.venv/bin/askovo demo
```

<!-- Hero demo GIF: record with marketing/demo/askovo-demo.tape (vhs), copy the artifact to assets/demo/askovo-demo.gif, then uncomment.
<p align="center">
  <img src="assets/demo/askovo-demo.gif" alt="askovo demo: one-line routing, chain skeleton, overclaim audit" width="860">
</p>
-->

You can also route directly: `askovo "SaaS subscription churn is dropping, want to know why users don't renew" --dry-run`. `--dry-run` only routes and writes nothing; `demo` runs the built-in synthetic sample. Router keyword tables are Chinese-first — English queries work, and `--domain` pins the product type whenever English keywords don't match.

**Language note:** CLI *output* is Chinese today; `docs/` are Chinese too. The command surface, JSON output and audit exit codes are language-independent, so it is usable from an English workflow, but the rendered text will not be English. English localisation is not scheduled yet.

Expected key results: `status: pass`, `supported: 1`, `overclaims: 0`. This only proves that the synthetic sample is self-consistent in structure, chain, and evidence references. It proves **nothing about real demand, product quality, market size, or release readiness**.

## From research question to decision result: what a full delivery looks like

Feed in a product question, get back a **Business Plan** — target scenes, personas, pains, demands, a feature map, a product form, and a GTM path, each judgment with its evidence-strength marker (● 已观察到 / ◐ 有线索 / ○ 假设， computed from cited records), data basis and user voices from the corpus. Using the built-in synthetic sample (`examples/sample-study`):

```bash
askovo chain examples/sample-study
askovo deliver examples/sample-study --kind plan   # → 06-report/plan.md (business language)
```

The plan reads like a business document: "## 2. 目标场景：哪些场景值得做", "## 4. 痛点：现在怎么办、痛在哪", "## 8. 商业与 GTM：怎么走向市场" — with evidence-strength markers `● 已观察到 / ◐ 有线索 / ○ 假设`, `数据基础`（sources · corpus size · time window）and `来自语料的声音`（verbatim user quotes）under each judgment, and "暂无采集数据" flagged honestly where a judgment has no data yet. Evidence codes and raw statuses live in the method archive at the end, not in the narrative.

When the reader is the decision maker rather than a business reader, the **Decision Package** renders the same chain decision-side — every judgment traceable to its evidence and counter-evidence:

> Research question: for remote pet owners, is it worth running a two-week phone-based check-in pilot for "pet watch while away from home"?

Once the chain is complete (all seven nodes validated, 2 counter-evidence items on record), one command produces the decision package:

```bash
askovo deliver examples/sample-study --kind decision   # → 06-report/decision-package.md
```

The decision package gives the decision maker five views:

| View | Answers |
|---|---|
| Opportunity Map | Which directions are worth considering (scene × user × pain, node readiness, priorities) |
| Evidence Graph | Which evidence (with E0–E5 levels) supports or refutes each judgment |
| Options & Trade-offs | Benefits, costs, counter-evidence, and alternative explanations per candidate direction |
| Decision Memo | Recommended choice, confidence bounds, why the others were not taken; delivery/outcome/causal states listed separately |
| Validation Backlog | The unknowns most worth validating next (gaps, needs-validation nodes, cheapest falsification test) |

Sample decision memo (excerpt, from the synthetic sample): prioritization method — "test privacy, acceptance and retained use before any scale decision"; rationale — "the smallest test that can reverse the concept; no market-size ranking is claimed"; confidence bounds — counter-evidence `R05`/`R07`, gaps include "Privacy controls are not tested in real homes"; three states — delivery `unplanned` / outcome `observing` / causality `not-claimed`. **`decided` is only a record of choice, not release or commercial proof** — the three states are independent and must not be inferred from one another.

The Business Plan, MRD/PRD/BRD, and the Decision Package are not separate sets of conclusions — they are business-user, market/requirements/business, and decision-side projections of the same chain.

The three recurring tasks all run the same chain and differ only in what they deliver: **discover** (product question → Business Plan, with the Decision Package as the decision-side deep-dive), **validate** (review a hypothesis → Validation Backlog), **decide** (compare candidates → Decision Memo).

### Versioned and adversarial DecisionRecords

`askovo decision` records and replays decisions inside the canonical `04-findings/product-reasoning.json` — not a second decision-truth file:

```bash
askovo decision record ./study --chain PR01 --by "product-owner" \
  --decision "Support the current bounded opportunity"
# Prerequisite: the id is registered, same-context, has provenance, and already has
# a contradicts/counter-evidence mapping. R05 ships with the sample; a newly
# collected counter record must be graded and registered the same way first.
askovo decision record ./study --chain PR01 --by "product-owner" --contradiction R05
askovo decision replay ./study --chain PR01
```

The second record deterministically applies `hold`, reopens the chain/product/business for validation, lowers confidence one ordinal step, and preserves before/after recommendations, evidence relations and snapshots. `--recommendation "..."` is an optional human override; the system does not invent a replacement product. An ID without a recorded contradiction relation is rejected. Newly mapped evidence is not promoted into a validated judgment or causal proof.

## One chain, 80 role families, 10 industry contexts, five base research packs

Askovo now includes an executable **product-innovation role operating system**, not just a job-title list. It covers 80 role families across opportunity research, user/needs research, product strategy, concept/service design, digital experience, physical engineering, consumer-product development, validation, lifecycle delivery, and ResearchOps/DesignOps. Every role defines its mission, responsibilities, KPI formulas and guardrails, input→action→output→gate SOPs, core deliverables, working templates, handoffs, and human accountabilities. Ten industry overlays adapt the work from consumer software and SaaS to AI, smart/traditional hardware, CPG, apparel/home, industrial robotics, automotive, and medical/health products.

```bash
askovo roles list --json
askovo roles show R52 --industry ai_native
askovo roles recommend "AI photography app concept" --stage concept --task design
askovo roles recommend "warehouse robot process and ROI" --task decide --scale lean
askovo roles scaffold ./study --role R29 --role R52 --role R72
askovo roles template R52 --output agent-interaction-spec.md
askovo deliver ./study --kind role --role R52  # canonical read-only role projection
askovo deliver ./study --kind lifecycle        # 10-module role/workflow board
```

`do` and `route` recommend a **task-sized** team, not all 80 roles. Askovo classifies the work as decide/discover/define/design/validate/launch/operate/review, selects the minimum sufficient roles, lists deferred roles and reasons, and builds an output contract that sets the primary deliverable, format, length, audience, section structure, evidence display and industry-specific expression. A software decision may need 1–3 roles; hardware validation or regulated work can expand to cross-functional review. After the canonical chain is confirmed, `roles scaffold` atomically creates `01-sources/role-workbench/` with the task/output contract, RACI, bound chain/node targets, SOP quality gates, null KPI targets and only this task's primary/supporting templates (multi-chain studies require `--chain`; `--all-templates` explicitly expands). These are orchestration artifacts only: they never create a second product/market/requirements/business truth or turn SOP completion into demand validation, engineering approval, clinical/safety/compliance sign-off, production readiness, or causal proof. See [Role operating system](docs/role-operating-system.md) (Chinese) and the [Agent role protocol](skills/askovo/references/role-operations.md).

The five SURE base-domain packs still own method routing. The ten industry overlays change professional context without forking the seven-node schema. The following chain projections remain available for their specific readers:

| Role | What they get from the same chain | Primary deliverables |
|---|---|---|
| Product manager | End-to-end trade-offs, scope, priorities, acceptance, risks, and business gates | Business plan, decision memo, product/business report, BRD, and final sign-off |
| User researcher | Scene, user, pain, and need evidence; counter-evidence and semantic review | Research status report, demand judgments, evidence ledger, evidence-backfill plan |
| User operations | Scene × user segmentation, real behavior, objections, lifecycle interventions, feedback loops | User-ops projection, tracker, behavior and retention evidence |
| Market research / analysis | Market boundaries, segments, competitor substitution, channels, pricing, sizing conventions, entry assumptions | MRD |
| Requirements research / analysis | Turning user, market, business, and technical needs into features, product requirements, priorities, acceptance, and traceability | PRD |
| Business analysis | Revenue model, pricing, cost, unit economics, resource gates, and risk acceptance | BRD |

A small team can wear several hats, but the workflows and outputs must not be conflated:

| Analysis workflow | Formal output | Must not masquerade as |
|---|---|---|
| Market research & analysis | MRD: candidate markets, segments, substitution, channels, pricing, and sizing conventions | User demand established, product success |
| Requirements research & analysis | PRD: traceable requirements from scene to need to feature, product, and acceptance | Market demand, business viability |
| Business analysis | BRD: product-to-business-model decisions, resource gates, unit economics, and residual risk | Product having succeeded, market having been proven |

All five domains share one chain schema — no per-domain forking. Domain packs only change methods, evidence forms, risk gates, and acceptance focus. Current first focus: **AI software, developer tools, and smart hardware** (the five-domain methodology stays compatible):

| Domain | Validation & delivery focus |
|---|---|
| Software / SaaS | Workflows, task usability, beta, A/B, cohort retention, release guardrails |
| Hardware / IoT | Install & maintenance, prototype bias, lab vs. field, configuration baselines, RMA |
| Consumer goods | Usage occasions, concept & packaging, CLT/HUT, sensory, first purchase & repurchase |
| Automotive | HMI, clinic/simulator/closed-course/road, misuse, engineering V&V and safety boundaries |
| Phone / wearable | Real-world scenarios, grip and cross-device use, weak network/power/compatibility, versions and after-sales |

## How it works

### 1. Build the product and business reasoning first; decide what to research second

```bash
askovo do "SaaS subscription churn is dropping, want to know why users don't renew"
askovo chain ./askovo-software-postlaunch
```

`do` detects domain, lifecycle stage, intent, and risks, then creates the chain canvas. `chain` renders the same machine truth:

```text
04-findings/product-reasoning.json   seven nodes, inferences, assumptions, counter-evidence, decision states
06-report/product-reasoning.md       human-readable projection
```

Every node must carry:

- `statement`: the current judgment;
- `rationale`: why the previous node licenses this one;
- `assumptions`: what must also hold for the inference to stand;
- `evidence_ids`: which registered evidence supports it;
- `status`: hypothesis / needs-validation / validated / rejected / deprioritized.

Feature nodes also record alternatives and acceptance criteria; the product node records form factor, scope, non-goals, and acceptance; the business node records market boundaries, segments, payers, competitive positioning, channels, pricing, cost, market-sizing conventions, unit economics, success metrics, and business gates. A chain's `decided` only means the current product/business choice was recorded — **it is not semantic review, engineering verification, release approval, commercial validity, or causal effect**.

### 2. Find the weakest node; backfill it with research

```bash
askovo check ./study --stage design
askovo platforms "home security camera night-alert complaints" --domain hardware --bulk
askovo instruments ./study
askovo collect ./study --platform reddit --query "night alert" --limit 100
askovo analyze ./study --question "night false alerts"
```

`source-plan.csv` marks which chain node each route serves via `reasoning_nodes`, so you never collect just to pump volume. Real collection still requires the Design gate, source authorization, and adapter checks.

`analyze` only normalizes, deduplicates, computes distributions, frequent candidate terms, and question-matched snippets; it never auto-generates scene, need, feature, or product conclusions.

When the weakest node is not obvious, `askovo loop` derives the gap from the audit, plans one query per gap and eligible source, runs rounds inside an authorized envelope, and re-audits after each round. Collected records stay review candidates — the loop never assigns an evidence level or edits a judgment.

```bash
askovo loop plan ./study
askovo loop authorize ./study --by "researcher"
askovo loop run ./study
askovo loop report ./study
```

For writing/decision gaps with existing local JSONL, `analyze` is an executable offline candidate: it reuses the descriptive analyzer and writes an execution record and follow-up review state without promoting candidates. Collection retains its authorization and Design gate; experiments and external-evidence requests are not auto-run. `stop` is separate from positive action scoring: an explicit three-condition `StopDecision` can rank it first only when more research cannot change the decision and is not worth its cost/risk; otherwise stopping for its own sake is not allowed.

### 3. Audit both "is the evidence enough" and "is the reasoning broken"

```bash
askovo check ./study --stage full --write-report
askovo audit ./study --json
askovo review ./study                 # decision review: readiness, falsifiability, bias, deliverable freshness
```

Two files, two owners:

- `product-reasoning.json`: owns the seven-node product semantics and inference rationales;
- `demand-judgments.json`: owns the evidence-eligibility judgments for demand, solutions, commercial behavior, and counter-evidence.

They join on `demand_judgment_id + context_key`. Evidence cited by a node must already be registered in the linked demand judgment — you cannot bypass the E1/E2, E3, E4+/E5, counter-evidence, and context gates by editing the chain file. The pain → need edge has a hard floor: **a need node can only reach `validated` with at least one piece of E2 evidence (observed substitution, workaround, or failure behavior); E1 verbal statements alone cap it at needs-validation** — saying is not doing.

A complete chain still does not prove product/business success; complete evidence cannot compensate for a missing inference rationale. Automated checks validate structure and configuration only — key semantics, market sizing, and unit economics stay with human and professional review.

### 4. Project the same chain into role-specific deliverables

```bash
askovo deliver ./study --kind plan    # business plan (business-user default): conclusions + nine sections + data basis + user voices
askovo deliver ./study --kind analysis # corpus analysis: funnel, source/year/role distribution, node coverage, counter-evidence
askovo deliver ./study --kind decision # decision package: opportunity map / evidence graph / options & trade-offs / decision memo / validation backlog
askovo deliver ./study --kind report   # combined product & business reasoning report
askovo deliver ./study --kind mrd      # market research & analysis → MRD
askovo deliver ./study --kind prd      # requirements research & analysis → PRD
askovo deliver ./study --kind brd      # business analysis → BRD
askovo deliver ./study --kind memo     # product decision memo
askovo boundary ./study --requirements req.md --output ai-prd.md  # F2 boundary audit: Added/Missing/Inflated candidates
askovo cost ./study log --task "audit PRD" --minutes 25           # F4 logged human minutes (optional no-tool baseline)
askovo deliver ./study --kind signoff   # F3 stakeholder sign-off page: conclusions + evidence levels + boundaries + signature block
askovo deliver ./study --kind ops      # user-ops projection
askovo deliver ./study --kind tracker  # behavior, acceptance, and business metric tracking
askovo report ./study                  # research status: 06-report/research-status.md
```

`deliver --kind report` is the single writer of the combined product/business report; `askovo report` writes a separate research-status file. The business plan, decision package, MRD, PRD, BRD, and ops views are all projections of one seven-node chain — not parallel sources of truth.

With multiple candidate chains, the plan opens with a cross-chain decision table and one conclusion block per chain, then renders the detailed sections once for the priority chain; `--kind report` fills its product-decision section with the same chain states instead of leaving placeholders. When a study aggregates several collection waves, `01-sources/collection-summary.json` supplies the funnel totals. Business strength (●◐○) is node-aware: the commercial node only counts E4+/E5, so counter-evidence cannot make it look observed.

## Askovo and SURE

**Askovo is the product; SURE is the research and evidence engine underneath.**

- **Askovo**: the chain workspace, five-domain routing, CLI/Skill/MCP, collection, analysis, and role deliverables.
- **SURE (Structured User Research with Evidence)**: method selection, evidence forms and levels, claim boundaries, anti-survivorship bias, safety gates, and judgment constraints.
- All three surfaces share `sure_engine.py` and the CLI command functions — behavior never forks.

In one line: **Askovo handles "reasoning from users to product and business"; SURE makes sure "every step knows how far its evidence actually reaches".**

**Post-launch growth is handled by [Growovo](https://github.com/roy-tong/Growovo)**: it consumes askovo's research judgments for positioning and growth (position → build → run), and first-party growth feedback flows back with the same E0–E5 grading — upstream and downstream exchange evidence instead of duplicating research.

## Research support capabilities

### Method routing

```bash
askovo route "how to validate the takeover experience of automotive cockpit voice" --domain automotive --json
askovo methods --domain automotive --stage validation
```

Automotive routes to clinics, simulators, closed courses, road, or naturalistic driving; consumer goods route to CLT/HUT/repurchase; software routes to usability, beta, A/B, and cohorts.

### Platform radar

```bash
askovo platforms "home security camera night-alert complaints" --domain hardware --bulk
```

Answers "where is the data, can it be obtained compliantly, which reasoning node does it help, and what can it not prove". Platform verdicts come as `supported`, `limited`, or `blocked`; where no compliant bulk channel exists, only authorized exports, research APIs, or compliant historical datasets are accepted.

### Collection, queues, and reproducibility

- GitHub goes through the official Search API; Reddit through the official Data API; everything else uses authorized exports, historical datasets, or local fixtures.
- Every collection run stores raw envelopes, normalized records, and a manifest recording access basis, rights, counts, discard reasons, restrictions, and bias.
- A SQLite queue supports multiple workers, lease recovery, failure backoff, rate limits, and resumable runs.
- CDP is limited to authorized visible pages on amazon / instagram / bilibili / weibo; X / YouTube and blocked platforms never use it, and captchas, login walls, and platform controls are never bypassed.

See [Platforms & connectors](docs/connectors.md) and the [CLI reference](docs/cli.md) (Chinese).

## Six finding types that must not be conflated

| Type | Answers | Must not substitute for |
|---|---|---|
| need | Who has what unmet job in what scene | Feature requests, anecdotes, prevalence |
| acceptance | Whether users understand/accept the solution | Liking ≠ will use / will buy |
| usability | Whether users can complete the task; learnable, low-error | Usable ≠ demand established |
| performance | Whether it meets the bar under stated conditions | Benchmark scores ≠ experience |
| commercial | Purchase, retention, repurchase, returns | Stated intent ≠ transactions |
| safety | Usage risk and compliance gaps | User trials ≠ certification |

E0–E5 grade demand and commercial evidence strength only — they are not a product/business reasoning score. Usability, engineering performance, safety, feasibility, business gates, and release gates each carry their own verification requirements.

## Boundaries

- No unauthorized scraping; blocked connectors, login walls, captchas, and platform challenges are never bypassed.
- Platform availability is never treated as sample-represents-population; record counts are never treated as user counts or audience size.
- Feature-mention frequency is not need; purchase intent is not purchase; adoption rate is not product outcome.
- One-time liking is not repurchase; beta, zero complaints, or zero incidents are not safety or release readiness.
- Demand evidence never substitutes for usability, performance, safety, engineering V&V, regulatory, or certification evidence.
- High-risk research stops at S0: the agent may only propose a plan, never instruct execution.
- All deliverables are drafts by default; a passing CLI run never replaces human semantic review, product sign-off, or risk acceptance.

## Installation

Askovo is published on PyPI. Install the released package with `pipx`:

```bash
pipx install askovo
askovo --version
askovo decision --help
```

Or with venv:

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install askovo
.venv/bin/askovo demo
```

For source development inside a checkout, use `pip install -e .` instead.

The core CLI, Skill, and MCP use only the Python standard library and support Python 3.9–3.12. The optional Workbook XLSX and Amazon HF tools declare openpyxl/datasets separately.

**Agent Skill**

```bash
bash scripts/install-skill.sh
bash scripts/install-skill.sh ~/.codex/skills
```

**MCP**

```json
{
  "mcpServers": {
    "askovo": {
      "command": "askovo",
      "args": ["mcp"]
    }
  }
}
```

MCP exposes `askovo_route`, `askovo_do`, `askovo_chain`, `askovo_platforms`, `askovo_collect`, `askovo_analyze`, `askovo_audit`, `askovo_decision`, `askovo_deliver`, and more, sharing behavior with the CLI; `collect` defaults to dry-run.

## Services & support

**The engine is free and open source forever**: the CLI, Agent Skill, MCP, and the five base domain packs are all MIT, with no feature-crippled edition. The only paid things may be deep domain assets and human delivery — never the engine itself.

| Capability | Current boundary |
|---|---|
| Seven-node chain with decision package / MRD / PRD / BRD projections | Structure and evidence references checked automatically; semantic review stays human |
| Evidence-graded audit (E0–E5, CI-ready exit code) | Checks structure and configured gates only; proves neither demand prevalence nor market success |
| Platform radar and collection | Blocked platforms never bypassed; the Design gate and authorization checks precede any collection |
| Human delivery (demand-validation study / team workshop) | Scope and fee agreed per engagement; commercial repeat business still being validated |

Human delivery has **no published price list**: email <a href="mailto:tongroy18@gmail.com?subject=Askovo%20research%20engagement%20%E2%80%94%20initial%20brief&body=Product%20%26%20domain%20%28software%2Fhardware%2Fconsumer%2Fautomotive%2Fmobile%29%3A%0AThe%20demand%20or%20decision%20question%20to%20validate%3A%0ADecision%20or%20review%20date%3A%0AExisting%20materials%20%28please%20don%27t%20attach%20raw%20data%20in%20the%20first%20email%29%3A%0AWho%20owns%20the%20decision%3A%0A">tongroy18@gmail.com</a> describing the task (domain, decision question, dates, existing materials, who owns the decision); if it fits, you get a written quote and work starts after confirmation — see the [engagement page](https://roy-tong.github.io/Askovo/first-look.html). Commercial delivery follows the same discipline as the open-source engine: conclusions never outrun the evidence, and semantic review and product sign-off belong to the decision maker. Free support goes through [GitHub Issues](https://github.com/roy-tong/askovo/issues); no SLA is promised.

<!-- Real cases (fill in after anonymization; rules in marketing/services/services.md §4; update after each engagement)
## Real cases

| Domain | Original question | Weakest node | Evidence action | Conclusion status |
|---|---|---|---|---|
-->

## Documentation

Docs under `docs/` are Chinese for now; this README and [llms.txt](llms.txt) are the English entry points.

| Doc | Contents |
|---|---|
| [Market, demand & business analysis](docs/business-analysis.md) | The three analysis workflows, role boundaries, and how MRD/PRD/BRD relate |
| [Role methodology](docs/product-methodology.md) | Method basis for PM, UXR, user-ops, and analyst roles across five domains |
| [Product & business reasoning chain](docs/product-reasoning.md) | Seven nodes, inference edges, business gates, counter-evidence, human review |
| [Quickstart](docs/quickstart.md) | From `do` to chain, evidence backfill, audit, and role deliverables |
| [Core concepts](docs/concepts.md) | Six finding types, evidence forms, forbidden inferences |
| [Five product modes](docs/modes.md) | Domain-specific validation differences on one chain |
| [Data contract](docs/data-contract.md) | product-reasoning, study, evidence, judgments |
| [SURE engine](docs/sure-engine.md) | Division between the product chain and the research support engine |
| [Platforms & connectors](docs/connectors.md) | Platform tiers, access modes, and scraping boundaries |
| [CLI reference](docs/cli.md) | Commands, arguments, artifacts, and exit codes |
| [Troubleshooting](docs/troubleshooting.md) | Install, routing, broken chains, collection, MCP |

Agent entry points: [llms.txt](llms.txt) · [AGENTS.md](AGENTS.md) · [SKILL.md](skills/askovo/SKILL.md).

## Repository layout

```text
skills/askovo/
  SKILL.md                     single-entry protocol and judgment rules
  assets/domain-packs/         five product research packs (never change the chain)
  assets/study-template/       workspace template including product-reasoning
  references/                  research, chain, data, and connector protocols
  templates/                   MRD/PRD/BRD and interview support templates
  scripts/askovo.py            deterministic CLI (single source of behavior)
  scripts/sure_engine.py       SURE support engine and chain scaffolding
  scripts/askovo_mcp.py        MCP shell
docs/                          Chinese product & methodology docs
examples/sample-study/         offline synthetic sample with a complete chain
tests/                         CLI, chain, routing, platforms, queue, MCP tests
```

Participating & releasing: [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) · [Release process](RELEASING.md) · [Code of conduct](CODE_OF_CONDUCT.md). If Askovo helps you, a star helps more people find it — entirely voluntary, no strings attached.

## License

MIT. Third-party components and data-rights boundaries: see [LICENSE](LICENSE) and [docs/connectors.md](docs/connectors.md).

## Local document intake (optional Docling adapter)

Study a PDF or Office file without copying it into the chat. This **local, opt-in extraction** turns a file into Markdown with a SHA-256 provenance sidecar. It does not claim to validate the document, source permission, or any business conclusion.

```bash
# Python 3.10+ for current Docling; Askovo's base installation remains dependency-free
pip install docling
askovo document ./research-report.pdf --out ./report-extracted.md
# Read provenance and check source rights before treating its text as evidence.
askovo import ./my-study ./report-extracted.md --source-family imported
askovo audit ./my-study
```

Plain UTF-8 `.txt` / `.md` work without Docling. The resulting `.provenance.json` records the original file hash and marks the extraction `unreviewed`. It does **not** make unsupported public-platform scraping permissible. See [feature status](docs/feature-status.md).


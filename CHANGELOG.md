# Changelog


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

- **Brand rename**: the product is now **askovo**; `askovo` is the CLI, Python package, Skill and MCP server. SURE (Structured User Research with Evidence) remains the underlying research engine (`sure_engine.py`), not the outward product name.
- **Logo**: added `assets/brand/askovo-logo.png`; README uses the askovo wordmark and the line “Ask better. Decide with evidence.”
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

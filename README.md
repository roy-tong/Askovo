<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/Askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Askovo

**Build product decisions on real evidence.**

Askovo helps product teams collect user and market evidence, test demand assumptions, and decide what to build next. It adds research execution, source traceability, counterexamples and validation records to the agent workflow you already use.

[Website](https://roy-tong.github.io/Askovo/) · [Decision replay](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html) · [Quickstart](docs/quickstart.md) · [Method](docs/product-reasoning.md)

[![CI](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## A general agent can reason. Askovo brings real evidence into the study.

A polished research answer is only as useful as the material behind it. Askovo helps a team go beyond the information already in the prompt:

- **Collect real material.** Gather community feedback, interview material, competitor records and authorized exports with source and acquisition history.
- **Test demand assumptions.** Keep concept feedback, prototype responses, longitudinal diary entries, willingness-to-pay statements and observed behavior distinct; simulated users do not become demand evidence.
- **Compare support and counterevidence.** Put exact source quotes, alternative explanations and coverage gaps beside each candidate direction.
- **Move and revisit the decision.** Turn the material into a Decision Brief and next validation, then revisit the same decision when new evidence arrives.

| General-purpose agent | Askovo |
|---|---|
| Helps frame a study, analyze supplied material and draft a recommendation | Adds collection, evidence provenance, demand-validation records and decision state |
| Can produce a plausible answer from the current context | Keeps support, counterexamples and unknowns attached to the claims they affect |
| Can rewrite a report for different readers | Projects the same research chain into a Decision Brief, business plan, MRD, PRD and BRD |

## What you can make

| Deliverable | What it helps the team do |
|---|---|
| Decision Brief | Align on the recommendation, supporting evidence, counterexamples and next action |
| Business plan | Connect target scenes, user needs, product form and the route to market |
| Needs report | Start with the business conclusion, requirement changes, product/business impact and next action; keep evidence and technical detail in the appendix |
| Decision Package | Compare opportunities, options, trade-offs and the cheapest useful validation |
| MRD / PRD / BRD | Give market, requirements and business readers a view built for their work |
| Decision replay | Revisit how new evidence changed an earlier recommendation |

Every deliverable comes from one reasoning chain: **scene → user → pain → need → feature → product → business**. You get different views for different readers without reconciling several versions of the conclusion.

## Research data without hand-edited JSON

Use the formal writers for study contracts, chain-level fields, commercial nodes, demand judgments and role workplans. CSV imports recognize `记录编号 / 内容 / 证据等级 / 来源 / 采集时间`; duplicate text is not counted twice, and conflicting record IDs reject the whole batch before evidence is written.

```bash
askovo chain STUDY set --field context_key --value-json '"after_sales_saas"'
askovo study STUDY set --field decision.owner --value-json '"周航"'
askovo evidence STUDY retract R01 --by "Research owner" --reason "Imported by mistake"
askovo evidence STUDY restore R01 --by "Research owner"
askovo case list
```

Retraction preserves the original text but removes the record from analysis, demand judgments and audit; restoration preserves it too. E3 correction requires a valid concept test. BRD projects the latest DecisionRecord without implying execution or business acceptance. See [CLI reference](docs/cli.md).

For every external platform, `.askovo/account-quotas.json` persistently records the account identity, tier and optional `collect` daily cap. Direct collection, rotation and queue runs share this policy across processes and conversations. Publishing quotas never become collection quotas; unknown tiers and limits stay unknown. See [platforms and connectors](docs/connectors.md).

## Run the product-reasoning sample

```bash
pipx install askovo
askovo demo
askovo do "Should we rebuild onboarding for small teams?" --domain software --dry-run
```

The offline synthetic sample shows how Askovo structures a study, links evidence and turns a question into a reviewable product judgment. [See how one counterexample changes a decision](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html).

## A workflow built for real research execution

1. **Frame the decision.** Start with the choice that has a real cost, not a generic request for research.
2. **Collect and import.** Use community feedback, interview material, competitor records, authorized exports and concept or prototype feedback.
3. **Analyze with provenance.** Quantitative and semantic analysis stay linked to exact source material and counterexamples.
4. **Validate and decide.** Keep stated interest, willingness to pay and observed behavior distinct; the decision owner selects the next move and revisits it as evidence changes.

Use the CLI directly, attach Askovo to your agent as a Skill, or call the same behavior through MCP. Collection, analysis, interviews and evidence grading support the product judgment rather than replacing it.

```bash
# Agent Skill
bash scripts/install-skill.sh

# CLI and MCP share the same engine
askovo decision --help
askovo mcp
```

CLI output and the detailed guides under `docs/` are currently Chinese. Commands, JSON fields and audit results are language-independent.

## Continue

- [Quickstart](docs/quickstart.md)
- [Product and business reasoning](docs/product-reasoning.md)
- [Decision Brief](docs/decision-brief.md)
- [Role and industry methods](docs/product-methodology.md)
- [Platforms and connectors](docs/connectors.md)
- [CLI reference](docs/cli.md)
- [Agent Skill](skills/askovo/SKILL.md) · [llms.txt](llms.txt) · [AGENTS.md](AGENTS.md)

Askovo is MIT open source. Bring a product decision through the [task page](https://roy-tong.github.io/Askovo/first-look.html), or open a reproducible issue on [GitHub](https://github.com/roy-tong/Askovo/issues).

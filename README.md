<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Askovo

**Great products grow from quantitative reasoning**

Askovo performs thorough quantitative research for product definition and decisions. It automatically collects and analyzes user and market data, then builds reasonable product judgments step by step—from scene and user to pain and need. Teams gain a reasoned answer to why, for whom and what to build, making data-driven product judgment part of everyday work.

[Website](https://roy-tong.github.io/Askovo/) · [Decision replay](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html) · [Quickstart](docs/quickstart.md) · [Method](docs/product-reasoning.md)

[![CI](https://github.com/roy-tong/askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## From scattered inputs to a product definition you can defend

A product discussion can easily become a contest of seniority, volume or report length. Askovo connects automatic collection, quantitative analysis and step-by-step reasoning directly to product definition:

- **See the opportunity.** Connect scenes, users, pains and needs instead of starting from a feature request.
- **Compare real options.** Put supporting evidence, counterexamples and trade-offs beside each candidate.
- **Move the decision forward.** Turn the discussion into a Decision Brief, a business plan and a concrete validation backlog.
- **Keep learning.** Revisit the same decision when new material arrives and see how the recommendation changes.

## What you can make

| Deliverable | What it helps the team do |
|---|---|
| Decision Brief | Align on the recommendation, supporting evidence, counterexamples and next action |
| Business plan | Connect target scenes, user needs, product form and the route to market |
| Decision Package | Compare opportunities, options, trade-offs and the cheapest useful validation |
| MRD / PRD / BRD | Give market, requirements and business readers a view built for their work |
| Decision replay | Revisit how new evidence changed an earlier recommendation |

Every deliverable comes from one reasoning chain: **scene → user → pain → need → feature → product → business**. You get different views for different readers without reconciling several versions of the conclusion.

## Run the product-reasoning sample

```bash
pipx install askovo
askovo demo
askovo do "Should we rebuild onboarding for small teams?" --domain software --dry-run
```

The offline synthetic sample shows how Askovo structures a study, links evidence and turns a question into a reviewable product judgment. [See how one counterexample changes a decision](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html).

## A workflow built for real product work

1. **Frame the decision.** Start with the choice that has a real cost, not a generic request for research.
2. **Bring the material you have.** Use documents, interviews, authorized exports and community discussions.
3. **Find the weakest link.** Askovo helps identify which assumption deserves new evidence first.
4. **Choose and revisit.** The decision owner selects the next move; new evidence can reopen the same decision.

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

Askovo is MIT open source. Bring a product decision through the [task page](https://roy-tong.github.io/Askovo/first-look.html), or open a reproducible issue on [GitHub](https://github.com/roy-tong/askovo/issues).

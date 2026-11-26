<p align="center">
  <img src="https://raw.githubusercontent.com/roy-tong/Askovo/main/assets/brand/askovo-logo-600.png" alt="Askovo" width="300">
</p>

<p align="center"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Askovo

**Discover the demand you did not know existed.**

Askovo is an AI-native research service for product teams. Bring a product idea, an assumption or a live product. Your agent can use Askovo to find real user and market evidence, test demand and revisit the decision as the evidence changes.

[OVO unified website](https://roy-tong.github.io/ovo/) · [Decision replay](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html) · [Quickstart](docs/quickstart.md) · [Current capabilities](docs/feature-status.md)

[![CI](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml/badge.svg)](https://github.com/roy-tong/Askovo/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/askovo)](https://pypi.org/project/askovo/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

## A general agent can design the study. Askovo brings back the evidence.

A plausible answer is cheap when the model already has enough context. The expensive part is finding the user who disagrees, the substitute people already rely on, the behavior that contradicts the pitch, and the result that should change the roadmap.

Askovo gives the agent you already use a research service with provenance, counterevidence, validation records and durable decision state.

### Three research services

| Service | Start with | Business delivery |
| --- | --- | --- |
| **Opportunity Research** | An industry, technology or product idea | Real user problems, existing substitutes, counterevidence and an evidence-backed opportunity |
| **Demand Validation** | A demand assumption or product concept | Participant screening, local experiment contracts, concept/prototype observations and a clear validation result |
| **Product Intelligence** | A live product | Durable research watches, incremental evidence and a changing picture of users, competitors and demand |

The first service creates the magic moment: **“I found something important that I did not know.”** The second helps a real decision. The third keeps the decision current.

## The goal is not a better-looking report

A good first result changes what the team does next:

- **Find the unknown.** Real user discussions and alternatives reveal needs that were absent from the original brief.
- **Test the assumption.** Concept, prototype, diary and price-sensitivity records stay distinct from actual payment or market prevalence.
- **Change or reaffirm a decision.** The Decision Brief keeps support, counterexamples and unknowns beside the recommendation.
- **Review it again.** New evidence triggers a bounded re-review instead of quietly rewriting an old conclusion.

One real research project analyzed **109,429 deduplicated comments across 8 communities over 24 months**. It moved the product sequence from dedicated hardware to software and export validation first. That is a convenience sample, not a user count or a market-share estimate. [Inspect the research method](docs/product-reasoning.md).

## Built for agents to compose, not for people to learn another workflow

Your host agent decides the research path. Askovo supplies the capabilities and the rules that protect research quality:

1. **Frame a consequential decision.** Start with a real choice, not a generic research prompt.
2. **Acquire what is missing.** Collect public material or import authorized customer feedback, interviews and product records.
3. **Challenge the answer.** Keep exact source material, alternative explanations and coverage gaps attached to each candidate.
4. **Validate when evidence is insufficient.** Use participant screening and local experiment runtimes where appropriate; public recruitment and deployment require separately authorized services.
5. **Deliver and revisit.** Produce a Decision Brief, record the owner’s choice and reopen it when new evidence arrives.

CLI, Agent Skill and MCP share the same research engine. Use the high-level decision entry or compose collection, analysis, experiments and evidence exports as atomic capabilities.

## Run the offline sample

```bash
# Stable
<!--OVO:askovo-stable-->pipx install askovo==2.25.0
askovo demo<!--/OVO:askovo-stable-->
# Preview (prerelease acceptance)
<!--OVO:askovo-preview-->pipx install askovo==2.25.1rc1
askovo demo<!--/OVO:askovo-preview-->
askovo do "Should we rebuild onboarding for small teams?" --domain software --dry-run
```

The synthetic sample shows how a study becomes a reviewable product judgment. [See how a counterexample changes a decision](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html).

For a whole decision task:

```bash
askovo decide start --input task.json
askovo decide status TASK_ID
askovo decide brief TASK_ID --format md
```

External collection requires source authorization. Human semantic review remains separate from candidate generation, and simulated users never become demand evidence.

## What is proven, and what comes next

- **Available now:** research collection and imports, evidence provenance, counterexample review, Decision Briefs, participant screening, local survey/landing/prototype/diary runtimes, research watches and proof exports.
- **Being validated next:** real participant recruitment, public experiment hosting, richer product-event sources and continuous host-led research.
- **Still to prove with users:** independent first-task success, a second decision review by the same owner and repeated external adoption.

See [feature status](docs/feature-status.md) for the implementation boundary. A local experiment or a passed structural check is not recruitment, demand proof or product acceptance.

## Continue

- [Quickstart](docs/quickstart.md)
- [Demand-validation guide](https://roy-tong.github.io/Askovo/guides/need-validation.html)
- [Product and business reasoning](docs/product-reasoning.md)
- [Decision Brief](docs/decision-brief.md)
- [Platforms and connectors](docs/connectors.md)
- [CLI reference](docs/cli.md)
- [Agent Skill](skills/askovo/SKILL.md) · [llms.txt](llms.txt) · [AGENTS.md](AGENTS.md)

Askovo is MIT open source. Bring one consequential product decision through the [task page](https://roy-tong.github.io/Askovo/first-look.html), or open a reproducible issue on [GitHub](https://github.com/roy-tong/Askovo/issues).

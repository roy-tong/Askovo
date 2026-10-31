# Product and business reasoning protocol

Use one shared spine for product managers, user researchers, user operations, market research/analysis, requirements analysis, and business analysis across software, hardware, consumer products, automotive, and mobile:

`scene → user → pain → need → feature → product → business`

The spine is an auditable value narrative, not a deterministic waterfall and not an automatic text-to-product generator. Work may start from an outcome, a behavioral anomaly, a user request, or an existing solution; always return to the spine to expose missing reasoning.

## Artifact ownership

- `04-findings/product-reasoning.json` is the only machine-readable source for the seven-node product/business semantics, incoming rationales, assumptions, alternatives, product scope, business model, market-estimate method, and resource gate.
- `04-findings/demand-judgments.json` owns demand, solution-acceptance, commercial/behavioral, and counter-evidence eligibility.
- `02-data/evidence.jsonl` owns direct observations, E-levels, provenance, and evidence basis.
- Descriptive analysis and corpus signals are supporting inputs. They never create or upgrade a product chain.
- Markdown reports, MRD/PRD/BRD, and user-operations views are projections of the same chain, not additional fact sources.

## One chain is one value thread

Keep one clear role × scene × task context per chain. Use multiple chains to compare candidate features, serve multiple scenes, or represent a multi-need product. Do not hide mutually exclusive solutions in one feature node.

Each chain contains:

```text
id / title
context_key / demand_judgment_id
status / confidence
supporting_states
nodes {scene,user,pain,need,feature,product,business}
prioritization
change_log[]
alternative_explanations[]
counter_evidence_ids[]
human_review
gaps[] / next_test
```

## Node contracts

Every node has:

- `statement`: the current claim;
- `rationale`: why this node follows from the previous node (for scene, why the scene enters the current decision);
- `status`: `hypothesis`, `needs-validation`, `validated`, `rejected`, or `deprioritized`;
- `evidence_ids`: direct supporting records already registered in the linked demand judgment;
- `assumptions`: atomic conditions that still must hold for the inference.

Node-specific fields:

| Node | Required semantics | Fields |
|---|---|---|
| scene | Trigger, environment, and task context | `trigger`, `environment`, `task_context` |
| user | Role, current state, and decision role in this scene | `role`, `state`, `decision_role` |
| pain | Current substitute, friction/cost, and consequence | `current_substitute`, `friction_cost`, `consequence` |
| need | Solution-neutral desired outcome, constraints, and measure | `desired_outcome`, `constraints`, `measure` |
| feature | Candidate capability, acceptance conditions, and alternatives | `capability`, `acceptance_conditions`, `alternatives_considered` |
| product | Coherent offer with form, scope, non-goals, and acceptance boundary | `form`, `scope`, `non_goals`, `acceptance_criteria` |
| business | Market boundary, segments, payer, positioning, revenue/pricing/cost hypotheses, market-estimate method, unit economics, metrics, and resource gate | `market_definition`, `geographies`, `time_window`, `included_markets`, `excluded_markets`, `target_segment`, `segments`, `payer`, `positioning`, `revenue_model`, `pricing_hypothesis`, `pricing`, `channels`, `competitive_alternatives`, `cost_drivers`, `market_estimates`, `unit_economics_inputs`, `success_metrics`, `non_goals`, `gate` |

A feature request is both a demand signal and a candidate solution, never sufficient proof of the Need node. Rewrite the need without solution vocabulary, then compare the original request with other candidates.

Evidence on a node does not prove its incoming inference. Pay particular attention to `pain → need`, `need → feature`, and `feature → product`. For the `pain → need` edge the CLI enforces one minimum: a validated need node must cite at least one E2 record (observed substitute, workaround, or failure). Stated pain alone (E1) keeps the need at `needs-validation` — words are a signal, observed effort is a stronger one.

## Decision and evidence states are different

Chain status is `draft`, `hypothesis`, `needs-validation`, `decided`, `rejected`, or `deprioritized`.

`decided` records a product/business choice at the current lifecycle stage. It does not mean product truth, PRD/BRD approval, release readiness, or commercial success. A current decided chain requires:

1. all seven nodes validated;
2. a validated linked demand judgment;
3. counter-evidence and at least one alternative explanation;
4. feature acceptance conditions and alternatives;
5. product scope, non-goals, and acceptance criteria;
6. business market boundary, segments, pricing/revenue/cost inputs, unit-economics register, success metrics, and resource gate;
7. prioritization method, owner, date, and rationale.

Legacy six-node chains remain readable; new studies use schema 2.0 and the seven-node flow.

If a PM proceeds despite uncertainty, keep the chain open and record risk acceptance, dissent, and a revisit trigger in `human_review`; do not relabel uncertainty as proof.

Keep orthogonal states in `supporting_states`:

```json
{
  "delivery": {"status": "unplanned", "release_plan_ref": ""},
  "outcome": {"status": "unmeasured", "metric_refs": []},
  "causal": {"status": "not-claimed", "experiment_refs": []}
}
```

Delivery: `unplanned`, `in-progress`, `release-ready`, `rolling-out`, `paused`, `rolled-back`.

Outcome: `unmeasured`, `observing`, `positive-observed`, `no-effect`, `negative`, `inconclusive`.

Causal: `not-claimed`, `supported`, `refuted`, `inconclusive`.

Release states require a release-plan reference. Measured outcome states require metric references. Causal support/refutation requires experiment references. E3 acceptance alone cannot establish release readiness; E5 observed behavior alone cannot establish causality.

## Evidence joins

Join a chain to exactly one demand judgment using `demand_judgment_id`; their `context_key` values must match. A new-style study requires every demand judgment to have one chain. Legacy studies without the product-reasoning contract remain readable, but if a chain file exists it is always validated.

Node references are projections of the judgment ledger:

- scene/user/pain/need ⊆ problem + counter evidence;
- feature ⊆ solution + counter evidence;
- product ⊆ solution + commercial + counter evidence;
- business ⊆ commercial + counter evidence;
- chain counter-evidence ⊆ judgment counter-evidence.

Direct-evidence minima for validated nodes:

- scene/user: semantically appropriate direct records other than E4-;
- pain/need: E1/E2; a validated need additionally requires at least one E2 observed-behavior record (E1 alone stays needs-validation);
- feature/product: E3 acceptance; the original judgment separately requires commercial/behavioral evidence for its own validated status;
- business: E4+ commercial intent or E5 paid/retained/expanded behavior. This supports the current commercial decision, not a claim of sustainable business success, market size, or causal effect.

To add evidence, first add the canonical evidence record, then register it in the demand judgment, then reference it from the chain. Never edit only the chain to bypass evidence gates.

## Rival explanations and human review

Use `assumptions` for conditions that must hold, `alternative_explanations` for rival interpretations or solution paths, and `counter_evidence_ids` for observed rejection, adequate substitutes, absent problems, or contrary behavior.

The CLI can check structure, IDs, context, evidence subsets, and required fields. Humans must still judge:

- whether a solution has been disguised as a need;
- whether the evidence genuinely supports the rationale;
- whether the linked judgment's demand phrasing (`user_role`/`scene`/`task`/`current_substitute`/`friction`/`consequence`) and the chain's node statements contradict each other — the judgment is the canonical demand-side phrasing; a chain statement that rewrites it must stay consistent, because no machine check compares free text;
- whether deviant cases and alternatives were treated fairly;
- whether sampling, ethics, scope, and wording are defensible;
- whether residual risk is acceptable.

`human_review` records `status`, `reviewer`, `notes`, and `risk_acceptance`. It is an attestation field, not proof that a real review occurred. High-risk or high-cost decisions need independent semantic review.

`prioritization` records the method, factors, evidence, owner, date, and rationale; frequency alone is not priority. `change_log` records trigger evidence, affected references, impact, decision, and projection sync. Update the canonical chain and affected items before regenerating MRD/PRD/BRD; a pending projection must be marked stale.

## Working loop

1. Define the decision, options including not acting, owner, deadline, and cost of being wrong.
2. Draft the product chain without inventing unknowns.
3. Identify the most decision-critical, weakly supported node or inference.
4. Choose methods and sources that can answer that specific uncertainty.
5. Collect, describe, code, grade, and seek counter-evidence.
6. Update the evidence ledger, demand judgment, and product chain in that order.
7. Record the product and business choice, then run separate usability, performance, feasibility, safety, commercial, and release checks as applicable.
8. Measure observed outcomes, use an appropriate experiment for causal claims, and feed operations learning back into the same chain.

Discovery and delivery may run in parallel. Launch does not end discovery. These are supporting workflows, not extra nodes in the value narrative.

Projection mapping: **market research/analysis → MRD**, **requirements research/analysis → PRD**, **business analysis → BRD**. These are views of one chain, not three fact stores. Market estimates require population/boundary, time window, unit, formula, source, and inference scope; payment evidence distinguishes list price, stated intent, preorder, paid transaction, and renewal. Unknown values stay null with gaps, never zero.

Business-node support commands: `askovo economics` renders a deterministic unit-economics projection (numeric, unit-matched, source-referenced inputs only; "cost-like" sums are name-based and indicative; arithmetic check, never commercial proof) and `askovo psm --input <csv>` renders a van Westendorp price-sensitivity projection (PMC/OPP/IDP/PME plus the acceptable range). PSM answers are stated intent, not paid behavior; neither output validates the business node by itself. Write findings back into `pricing`/`unit_economics_inputs`/`gaps`; do not create a second business truth in the reports. If `06-report/pricing-psm.md` exists without a `business.pricing` entry citing PSM or a registered E4- record, `askovo check` emits a `pricing_psm_link` warning so the projection cannot silently float outside the chain.

## Role projections

- Product manager: full chain, trade-offs, alternatives, MVP scope, non-goals, acceptance, business gate, residual risk, and final sign-off.
- User researcher: node evidence, warrant, sampling gaps, rival explanations, counter-evidence, semantic review, research-status and audit outputs.
- User operations: scene/user/pain language, behavioral cohort definitions, objections, lifecycle intervention, commercial metrics, outcome tracking, and learning written back to the chain.
- Market research/analysis: market boundary, segments, alternatives, channels, price, sizing method, and MRD.
- Requirements research/analysis: requirement origins, prioritization, acceptance, traceability, change impact, and PRD.
- Business analysis: revenue model, pricing/cost inputs, unit economics, resource gate, risks, and BRD.

For operations, define events, numerator, denominator, time zone, cohort rule/version, observation window, and data completeness. Feedback records are not audience size. Behavioral data shows what happened; interviews and observation help explain why; causal claims need an appropriate design.

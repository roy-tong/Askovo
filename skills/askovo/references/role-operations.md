# Role operations protocol

Use this protocol when a task needs product-innovation role responsibilities,
KPIs, SOPs, deliverables, templates, team composition, or industry-specific
working practices. The role system orchestrates work around the canonical
product/business chain; it does not replace research judgment.

## One spine, four operating layers

1. **Business process — What:** ten lifecycle areas from opportunity discovery
   through delivery and research/design infrastructure.
2. **Role contract — Who:** 80 role families with mission, responsibilities,
   KPI definitions, SOP quality gates, deliverables, handoffs and human
   accountabilities.
3. **Reusable professional practice — How:** interviews, quantitative research,
   business cases, service blueprints, interaction design, requirements,
   verification and other methods remain supporting capabilities.
4. **Industry context — Context:** ten overlays change stakeholders, research
   objects, design inputs, prototype forms, verification layers, claim
   boundaries and accountable professionals.

The canonical product/business semantics remain only in
`04-findings/product-reasoning.json` (`scene → user → pain → need → feature →
product → business`). Demand/commercial evidence eligibility remains in
`04-findings/demand-judgments.json`. Role workplans and templates are
orchestration artifacts, not new findings stores.

## Command surface

```bash
askovo roles list [--lifecycle L02] [--industry ai_native] [--query "Agent"] [--json]
askovo roles show R52 --industry ai_native
askovo roles recommend "AI photography app concept" --stage concept --task design
askovo roles recommend "warehouse robot process and ROI" --task decide --scale lean
askovo roles scaffold ./study --industry ai_native
askovo roles scaffold ./study --task define --scale standard
askovo roles scaffold ./study --role R29 --role R52 --role R72
askovo roles template R52 --deliverable R52-D01 --output agent-interaction-spec.md
askovo deliver ./study --kind role --role R52 --deliverable R52-D01
```

`do` and `route` include an industry context and role recommendation. The five
SURE domain packs still own base-domain method routing. The ten role-industry
overlays do not fork the seven-node schema and do not create ten separate
products or install variants.

## Task-sized selection and adaptive output

Do not treat the 80-role catalog as a team checklist. Infer one task type —
`decide`, `discover`, `define`, `design`, `validate`, `launch`, `operate` or
`review` — from the product, goal, stage and explicit `--task`, then choose the
minimum sufficient team:

1. accountable lead for that task/product;
2. roles triggered by explicit task words;
3. capability-overlay roles such as AI product/interaction when relevant;
4. only the industry roles needed by this task's lifecycle.

`--scale lean|standard|cross_functional` can override automatic sizing. The
result includes selected roles, deferred roles and reasons, real handoff edges,
and `output_plan`.

`output_plan` decides the primary deliverable, at most two supporting outputs,
format, length, audience, tone, required section structure, evidence display,
visual forms, expression prohibitions and industry output exemplars. The
workplan stores this contract. `roles scaffold` generates only the primary and
supporting templates by default; `--all-templates` is an explicit expansion.
Role/lifecycle projections render the same expression contract before canonical
content; formatting never changes evidence boundaries.

The five SURE domain packs still own method routing; role selection never
overrides the routed base domain, risk gate or evidence rules.

## Role IDs and lifecycle areas

- L01 / R01–R08: market, industry and opportunity research.
- L02 / R09–R24: user, consumer and needs research.
- L03 / R25–R35: product strategy, management and requirements planning.
- L04 / R36–R43: concept, innovation, service and business design.
- L05 / R44–R55: digital experience, interaction and experience engineering.
- L06 / R56–R65: industrial design, hardware and engineering definition.
- L07 / R66–R71: formulation, food, sensory, apparel and packaging development.
- L08 / R72–R76: concept, usability, field, engineering and compliance validation.
- L09 / R77–R78: product development delivery and lifecycle management.
- L10 / R79–R80: ResearchOps and DesignOps infrastructure.

L10 is cross-cutting, not a mandatory last step. Any negative result can reopen
an upstream role. A small team may hold several roles, but the accountability
and quality gates remain distinct.

## Industry overlays

| ID | Context | Non-negotiable distinction |
| --- | --- | --- |
| `consumer_software` | Consumer app/software | Behavior, task usability, retention and paid conversion |
| `enterprise_software` | B2B/SaaS | Organization workflow, roles/permissions, integration and ROI |
| `ai_native` | AI/Agent | Capability bounds, evaluation, tool permissions, recovery and cost |
| `smart_hardware` | IoT/smart device | Physical + software interaction, power, BOM, reliability and manufacturing |
| `traditional_hardware` | Durable consumer hardware | ID/CMF, ergonomics, durability, materials, packaging and cost |
| `cpg` | Food/beauty/home care | Formulation, sensory, claims, stability, packaging and repurchase |
| `apparel_home` | Apparel/footwear/home | Trend, textile, fit/size, comfort, SKU architecture and production |
| `industrial_robotics` | Industrial equipment | Process, cycle time, safety, integration, uptime and TCO/ROI |
| `automotive` | Vehicle/mobility | Vehicle integration, HMI, misuse, safety/SOTIF, NVH and regulation |
| `medical_health` | Medical/health device | Intended use/users/environments, use risk, clinical/regulatory/quality evidence |

Use `roles show ROLE --industry ID` to resolve the generic role contract with
its industry-specific practice and gates. A role title never determines the
physical or regulatory profession: software Product Designer, hardware
Industrial Designer and formulation Scientist are different roles.

## KPI contract

Every KPI has a `formula` and a `guardrail`; targets start as `null`, never zero.
The catalog provides measurement definitions, not employee scores or universal
benchmarks. The team must set the target, baseline, window, denominator, owner
and data source before using a KPI.

Do not optimize document counts, meeting counts, raw mentions, evidence volume,
SOP completion or positive-only acceptance. Pair each outcome/flow measure with
a quality guardrail. Examples:

- traceable requirement coverage does not prove the requirements are right;
- verified requirement coverage does not prove user value or release readiness;
- decision lead time does not justify skipping counter-evidence;
- participant recruitment speed does not justify an unrepresentative frame;
- design-system adoption does not justify inaccessible or unsuitable components;
- AI task success requires a task denominator, versioned evaluation set and
  correct business outcome, not merely completed tool calls.

## SOP and handoff contract

Every role SOP step records `input`, `action`, `output` and `gate`. In a study
workbench it also starts with `status: not_started`, empty evidence references
and an unassigned reviewer. Completing a step changes work status only. It does
not assign E0–E5, validate a demand judgment, mark a chain node validated or
approve a release.

A handoff must name:

1. the upstream/downstream role and accountable owner;
2. the exact input artifact and version/configuration;
3. the chain/node or decision it supports;
4. unresolved assumptions, counter-evidence and excluded contexts;
5. acceptance reviewer, acceptance conditions and reopen criteria.

PM, PO and BA are not synonyms. PM owns product value, priorities and business
trade-offs; the Scrum Product Owner maximizes product value and orders the
Product Backlog; BA clarifies business processes, rules, needs and system
relationships. One person may combine them without erasing those distinctions.

## Validation layers stay separate

- **Value:** a role/scene/task needs the offer and may adopt/pay.
- **Experience:** intended users can understand and complete the task.
- **Engineering:** the specified configuration meets measurable requirements.
- **Safety/compliance/clinical:** qualified processes and professionals accept
  the relevant evidence and residual risk.
- **Production/delivery:** the organization can repeatedly deliver the bounded
  offer at the required quality and economics.

Concept acceptance cannot release a product. Engineering verification cannot
prove demand. A user preference cannot prove clinical efficacy. A successful
bench run cannot prove factory cycle time. `decided` remains only a recorded
product/business choice. Delivery, observed outcome and causal states remain
independent.

## Generated workbench boundary

`roles scaffold` requires at least one canonical chain. A single chain is bound
automatically; multi-chain studies require `--chain PRxx`. It builds in a temporary
directory and atomically renames the complete result to
`01-sources/role-workbench/`:

- `workplan.json` — task, scope, output contract, catalog/industry hashes,
  role/SOP/KPI/template references, assignments, bound `PRxx.node/edge` targets,
  separate `work_status`, and null KPI baselines/targets/windows/denominators/
  sources/owners;
- `workplan.md` — readable output contract, RACI, handoffs, SOPs and generated
  deliverable links;
- `templates/Rxx-Dyy.md` — only the primary/supporting output templates by
  default (`--all-templates` expands), with seven-node semantic fields
  `editable=false`.

Reasoning, demand judgments and evidence are compared before/after generation.
Empty chains are rejected, write failures leave no partial workbench, and an
existing stateful workbench cannot be overwritten (including with `--force`).
Commercial KPI targets additionally require a `business_metric_ref` into the
canonical business node's `success_metrics`.

`deliver --kind role --role Rxx` is the formal counterpart to a blank template.
After a fresh full audit it projects only workplan-bound chain/node statements,
rationales, statuses, assumptions and evidence IDs read-only into flat
`06-report/role-Rxx-Dyy.md`. The report opens with the workplan's output contract
(format, length, audience, structure, evidence display, expression limits), then
projects canonical content. Legacy studies without a workplan require one chain
or explicit `--chain`. Template sections are `editable=false` with source
mappings; work notes stay separate. Stale catalog/industry hashes, broken
references, missing KPI measurement contracts, missing role or chain block the
projection instead of letting the template author new findings.

`deliver --kind lifecycle` writes `06-report/lifecycle-board.md`: all ten module
entry/exit contracts, leads/collaborators, actual owners, work states and real
handoff edges. Workplan changes affect report freshness; role-catalog and
industry-asset changes affect only role/lifecycle projections. `review` and full
`audit` validate enabled workplans while legacy studies without one stay compatible.

Detailed engineering, formulation, clinical, regulatory, safety, manufacturing
and certification work requires real experiments, suitable facilities/tools
and accountable qualified professionals. Askovo can structure inputs,
traceability and decision support; it cannot substitute for that work.

## Method anchors

The role model is an Askovo synthesis, not an official occupation taxonomy.
Method anchors include the [2020 Scrum Guide](https://scrumguides.org/scrum-guide.html)
for Product Owner/backlog/Increment accountabilities; [Stage-Gate](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/)
for cross-functional stages and Go/Kill/Hold/Recycle resource gates; [NN/g
contextual inquiry](https://www.nngroup.com/articles/contextual-inquiry/) for
natural-context observation and shared interpretation; [NN/g service
blueprints](https://www.nngroup.com/articles/service-blueprints-definition/)
for customer/frontstage/backstage/process relationships; and the [August 2026
FDA human-factors guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/applying-human-factors-and-usability-engineering-medical-devices)
for intended users, uses, use environments and use-related risk. These sources
inform role practices; none supplies universal KPI targets.

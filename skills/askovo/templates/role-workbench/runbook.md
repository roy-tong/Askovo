# Role workbench and deliverable templates

The 257 role deliverable templates are generated from the single
`assets/role-catalog.json`; do not copy them into per-role static truth files.
Every template has a stable `Rxx-Dyy` ID, purpose, sections with prompts, and
quality checks.

## Choose and render

```bash
askovo roles list --query "Agent" --json
askovo roles show R52 --industry ai_native
askovo roles template R52 --deliverable R52-D01 --output agent-interaction.md
```

Templates are working contracts, not findings. Their seven-node semantic fields
are `editable=false`; professional execution notes may be recorded, but market,
requirements, product and business conclusions must be written only through the
canonical evidence/judgment/chain flow.

## Select a task-sized team and bind a study

```bash
askovo roles recommend "AI camera concept and failure recovery" --task design
askovo roles scaffold ./study --task design --scale standard
askovo roles scaffold ./study --role R29 --role R52 --role R72
# Multi-chain studies:
askovo roles scaffold ./study --chain PR02 --role R29 --role R52
```

Recommendation infers decide/discover/define/design/validate/launch/operate/
review, selects a minimum sufficient team, lists deferred roles and reasons, and
builds an `output_plan`: primary/supporting deliverables, format, length,
audience, sections, evidence display, visuals, expression limits and industry
exemplars. The workbench stores that contract. It writes only the primary and
supporting templates by default; `--all-templates` is an explicit expansion.
It never overwrites an existing stateful workbench. Empty chains are rejected
and write failures leave no partial package.

## Deliver read-only projections

```bash
askovo deliver ./study --kind role --role R52 --deliverable R52-D01
askovo deliver ./study --kind lifecycle
```

Role reports consume workplan bindings and live at `06-report/role-Rxx-Dyy.md`.
The lifecycle board lives at `06-report/lifecycle-board.md`. Both preserve audit,
freshness and professional boundaries. A blank template must never be used to
manufacture a formal role deliverable.

Read `references/role-operations.md` and `docs/role-operating-system.md` for the
full contract.

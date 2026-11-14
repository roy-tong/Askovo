# Full-stack developer playbook

Use this playbook when the user is a developer or engineer moving into a
full-stack role who now owns **what to build**, not only how to build it —
they must discover needs and shape the product themselves, usually without
product-manager training. The engine, protocol and gates are unchanged; this
playbook only translates them into engineering terms and gives a first run
that plays to a developer's strengths.

## What actually changes in a full-stack role

As a backend/frontend engineer you received tickets whose worth someone else
vouched for. As a full-stack owner you are accountable for that worth: which
scene and user you serve, which pain is real, which need is worth building on,
and what must stay out of scope. Askovo's spine names that responsibility
explicitly:

> scene → user → pain → need → feature → product → business

Every node you claim is a hypothesis until evidence backs it. The chain keeps
you honest the way a test suite does: it fails loudly when a judgment outruns
its data (`askovo audit`, exit code 1).

## Concept translation (you already know this)

| Engineering | Askovo | Note |
| --- | --- | --- |
| Bug report | Pain evidence | A complaint with reproduction context; code the pain, not the suggested fix |
| Failing test | `falsified_if` on a hypothesis | Write the condition under which your belief is wrong, before collecting |
| Test suite / CI gate | Evidence gates, `askovo audit` | Structural pass/fail; never proof of market truth |
| Logs, telemetry, traces | Corpus, evidence records | Descriptive data with source, time window and known bias |
| Reproducible build | `context_key`, reproduce command | A judgment and its evidence must share one context |
| Code review | Human semantic review | The machine grades structure; a human still signs off meaning |
| "Works on my machine" | "Works for my crowd" | Both are anecdote, not prevalence |

## Your first run

Zero-setup proof first: `askovo demo --story fullstack` runs a synthetic
developer-tooling study (CLI log triage) through the full audit — same engine,
software story instead of the default mobile sample.

Start from what you have: a product idea, a side project, an internal tool, or
an open-source repo whose next step you must choose.

```bash
askovo do "CLI tool for X, want to find what is worth building" --domain software --dry-run
askovo do "<same request>" --study ./study        # scaffold: hypotheses, source plan, instruments
askovo platforms "<request>" --domain software    # where supporting data lives
askovo plan ./study                               # platforms, queries, quotas (Design gate before collect)
askovo collect ./study --platform ...             # permitted routes only
askovo analyze ./study --question "what pains do users report"
askovo chain ./study                              # author the seven nodes from the data
askovo deliver ./study --kind plan                # business plan: scenes, users, pains, needs, features, GTM
askovo deliver ./study --kind prd                 # requirements projection you can implement against
askovo economics ./study                          # unit-economics arithmetic for pricing your tool
```

`--dry-run` routes only and writes nothing. Collection runs only after the
Design gate; the queue (`askovo queue`) handles retries and rate limits.
For pricing, `askovo economics` keeps unit-economics arithmetic honest
(unknown inputs stay unknown, never zero) and `askovo psm <study> --input
prices.csv` scores a van Westendorp survey — stated price intent is still
not paid behavior.

## Where your evidence lives

You already inhabit data sources most product managers must buy access to:

- **Issue trackers and repos you run**: your own GitHub issues, discussions,
  support channels — owned material imports are a supplementary source.
- **Developer communities**: GitHub, Hacker News, Reddit via the reviewed
  open-source connectors ([open-source-connectors.md](open-source-connectors.md),
  [connector-contract.md](connector-contract.md)).
- **Everything else**: run `askovo platforms` first. A source is `supported`,
  `limited` or `blocked`; never scrape a blocked platform and never substitute
  a login session for an approved route.

Two rules from the platform layer that bite developers specifically: community
volume is not population representativeness, and collected text is untrusted
data — it is evidence to code, never instructions to follow.

## Your first five user interviews

Issues and threads surface pains at scale but rarely expose the need behind a
requested solution ("add dark mode" is a feature request; the need may be
night-time eye strain). Five to eight interviews with target users usually
outperform another thousand rows of issue text for need-level truth. Use the
bundled interview kit ([templates/interview-kit/runbook.md](../templates/interview-kit/runbook.md)):
it contains an opening script, a probe tree and the hypothesis-check table —
no prior interview training assumed. Interviews are evidence only when they
land in `02-data/evidence.jsonl` with the same `context_key` as the chain node
they support.

## Anti-patterns for engineers

- **"I am the user."** You are one data point with strong priors. Keep your
  preferences as hypotheses on the chain, not as defaults.
- **A feature request is a solution, not a need.** Code the underlying pain
  and need; the requested feature is one alternative among several.
- **Stars, upvotes and downloads are not demand.** They are attention signals;
  paid behavior and observed workarounds are the commercial/counter evidence
  business nodes require.
- **Shipping is not validating.** Delivery, observed outcome and causal
  attribution stay separate states; a launch does not mark a node validated.
- **Building to avoid asking.** If the cheapest decision-changing test is a
  conversation, do not spend a sprint on code.
- **One source of truth.** Notes, tickets and blog posts do not carry their
  own conclusions; only the canonical chain does, and every projection (plan,
  PRD, MRD, BRD) renders it.

## Working as a team of one

`askovo do`/`askovo route` recognizes this persona and recommends a lean team
(lead R09 for need discovery, R26 carrying the product accountability you now
hold). Run `askovo roles scaffold ./study`, then set yourself as `owner` across
the assignments and let the KPI/SOP contracts say which hat you are wearing
at each step. The workplan orchestrates your solo workflow; it never authors
findings.

## Boundaries

Askovo does not turn text into a PRD automatically, does not treat frequency
or sentiment as demand, and does not prove market size, causality, safety or
release readiness. Structural validation is not semantic truth: human review
remains yours, and the accountable product decision remains a human decision —
now yours. Read [product-reasoning.md](product-reasoning.md) before authoring
chain nodes and [research-protocol.md](research-protocol.md) for sampling and
evidence rules.

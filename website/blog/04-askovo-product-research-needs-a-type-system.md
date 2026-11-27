# Askovo: product research needs a type system, not a confidence score

*Orthogonal evidence qualification, structural transaction checks, conclusion gates, and hash-bound research handoffs.*

A GitHub API response can confirm that a repository has 220 stars. The same response cannot confirm that 220 people use the product, will pay for it, or made a product decision because of it.

Now imagine a record that labels this observation `E5`, the highest evidence level in the system. A scalar confidence score has no good way to explain the problem. The observation may be perfectly accurate and still be the wrong type for a commercial conclusion.

Askovo handles this by treating evidence qualification as three related but orthogonal dimensions:

```text
measurement_integrity  → is the record itself confirmed, self-reported, unverified, or conflicted?
behavior_kind          → what kind of behavior does the record describe?
claim_eligibility      → which conclusion type may this record support?
```

The first two do not determine the third by themselves. They pass through explicit rules, some of which require human review. This is closer to a type system than a score: a valid observation of one type cannot be coerced into evidence for an unrelated claim just because it is reliable.

## The qualification rules are deliberately non-monotonic

Running `qualify_evidence` on an attention metric with a confirmed source and an asserted E5 level returns:

```json
{
  "measurement_integrity": "confirmed_source",
  "behavior_kind": "attention_metric",
  "claim_eligibility": "descriptive_only",
  "needs_requalification": true,
  "review_required": false
}
```

The original `evidence_level=E5` is not rewritten. Instead, the record is marked for requalification. Preserving that conflict is important: silently changing the level would erase the history of how the mistake entered the study.

The eligibility function is not “higher integrity means higher business evidence.” Its branches include:

| Behavior | Confirmed source | Self-reported | Unverified or conflicted |
| --- | --- | --- | --- |
| `attention_metric` | `descriptive_only` | `none` | `none` |
| `commercial_intent` | `descriptive_only` | `descriptive_only` | `none` |
| `commercial_transaction` | `commercial` | `none` plus review | `none` plus review when applicable |
| `problem_behavior` | `problem` | `problem` | `none` |
| `solution_acceptance` | `solution` | `solution` | `none` |
| Ordinary statement | `descriptive_only` | `none` | `none` |

An exact star count remains useful—as an attention metric. A self-reported intention to buy can describe demand language without becoming a transaction. A claimed payment with no verifiable source does not become commercial evidence merely because the claimant used the word “paid.”

The derivation also consumes source-specific fields. Verified purchase and transaction-linked statuses can confirm a commercial transaction; pledged or adjusted crowdfunding statuses describe commercial intent; tracker, funding, and rating snapshots are attention metrics. This keeps the vocabulary aligned with what the source actually measured.

## Evidence levels still matter, but imports have structural ceilings

Askovo retains E0–E5 grades for the broader research method. The import layer applies a separate ceiling by evidence form:

```python
IMPORT_LEVEL_CAPS = {
    "self_report": "E2",
    "behavior_log": "E2",
    "transaction": "E5",
    "purchase": "E5",
}
```

A self-report or behavior log cannot be imported at E3 acceptance or E4+/E5 commercial levels. The file is rejected if the requested level exceeds the form's cap. A row cannot raise its level above the cap declared for the import, and mixed rows keep per-row derived levels.

Transaction and purchase forms need additional structure before E4-/E4+/E5 is allowed:

```text
counterparty
occurred_at
amount
source_ref
evidence_ref
```

Defaults do not fill these fields. If any is missing, the row is held at E2 and `level_basis` records the rule:

```text
transaction structure incomplete: missing counterparty, amount; E5 held at E2
```

This produces two different failure behaviors that are easy to confuse:

- an imported self-report requesting E5 fails the import policy check;
- a transaction-form row requesting E5 can enter the pipeline, but an incomplete row is downgraded structurally to E2.

The command's `--evidence-form transaction` flag is therefore not a voucher. It only selects the rules that a real transaction record must satisfy. Fifteen import and conclusion-gate tests passed when I ran them for this article, including every missing transaction field, mixed rows, unknown levels, and plain text claiming to be a transaction.

## Source count is not independent-source count

Quantitative research has another coercion problem: 1,000 copied records look larger than one record. Askovo computes independent sources with a separate identity key:

```text
source_url, if present
→ otherwise collection_run_id + source_ref
→ otherwise record_id / normalized_text_hash / object identity fallback
```

The independent-source count is the cardinality of that key set. One URL repeated across 500 records remains one source. This does not make those 500 records useless; frequency, distribution, and text analysis still matter. It prevents record volume from masquerading as independent corroboration.

That distinction is essential in the internal golf-device study often used to illustrate Askovo. It analyzed 109,429 deduplicated comments from eight communities over 24 months and changed the proposed sequence from dedicated camera hardware to validating software and exports first. The corpus was a convenience sample. Its scale supported quantitative analysis of that corpus, not a market-prevalence estimate or 109,429 independent confirmations.

A type-aware reading asks better questions of the same data: which records describe current behavior, which describe acceptance, which are counterexamples, which are merely attention metrics, and which sources are genuinely distinct?

## The formal conclusion gate is separate from node confidence

Askovo exposes six claim categories in its MCP schema: `need`, `acceptance`, `usability`, `performance`, `commercial`, and `safety`. They should not share one acceptance criterion. Interviews may support a need without proving performance; clicks may describe usability without establishing pricing; a vendor assertion cannot establish safety.

The delivery layer adds a final gate for calling something a formal business conclusion:

```text
business node is validated
+ qualifying E4+/E5 commercial evidence is present
+ full audit passes
= formal conclusion
```

Otherwise, the output remains a current judgment with named gaps and a next evidence action. A validated business node without commercial evidence is still gated. A clean commercial record cannot rescue a failed full audit. Multiple chains are evaluated independently, so one well-supported chain cannot lend its status to another.

This gate is stricter than an individual node's display status, and deliberately so. A product team can use a current judgment to decide what to investigate next without presenting it as commercial proof.

## Context export is a type-preserving handoff

The handoff to Growovo introduces a different failure mode: research premises arrive downstream looking like verified facts. Askovo's context exporter maps each of the seven chain nodes to one of three statuses:

```python
if node_status == "validated" and evidence_refs and not unresolved_refs:
    status = "evidence_supported"
elif node_status == "hypothesis":
    status = "hypothesis"
else:
    status = "insufficient_evidence"
```

A validated node with a missing evidence ID is downgraded to `insufficient_evidence`. Rejected and deprioritized nodes also remain non-facts. A node with no external reference gets a `status_record_only` reference to its own reasoning record, which is explicitly not external research evidence.

The export requires three human-defined inputs:

- `--approved-by`, because forwarding research premises is an approval act;
- at least one `--value-event`, because Askovo cannot invent the downstream value metric;
- at least one non-goal, either already declared in product/business nodes or supplied with `--non-goal`.

The command is:

```bash
askovo context export STUDY --out NEW_DIR \
  --approved-by "Product owner" \
  --value-event "A product owner records a decision disposition"
```

It writes two immutable files:

```text
<context_id>.<version>.payload.json  # claims, evidence refs, value events, non-goals
<context_id>.<version>.json         # same payload + source ref + content_sha256
```

The default version is `reasoning-<first 12 hex of the reasoning file SHA-256>`. The payload is serialized with sorted keys, and the envelope's `content_sha256` hashes those exact bytes. Growovo recomputes the payload hash during import, so the two files must remain together at the original path. Re-exporting the same version refuses to overwrite either file; if envelope creation fails, the newly created payload is removed.

I ran the exporter on the synthetic sample, then deliberately changed one product node to `validated` with a nonexistent evidence ID and one business node to `hypothesis`. The resulting projection was:

```text
total:                7
evidence_supported:   5
hypothesis:           1
insufficient_evidence: 1

PR01:product
  status: insufficient_evidence
  unresolved: ["missing-evidence-id"]

PR01:business
  status: hypothesis
```

This is the handoff behavior that matters. The mutated product node still says `validated` in the source, but downstream receives an unresolved evidence gap rather than an upgraded claim.

## A second use should preserve the same distinctions

The second decision or research review is useful only if it retains these type boundaries. A new GitHub metric should remain an attention observation. A new transaction should bring its row-level structure and source. A copied URL should not inflate independent corroboration. A changed evidence reference should produce a new reasoning version and a different handoff hash.

That gives the second-use measurement a concrete shape:

- count new and removed independent sources;
- compare eligibility distributions, not just evidence totals;
- preserve requalification conflicts for human review;
- compare claim statuses in the exported payload;
- record which conclusions remained current judgments;
- record the owner's actual disposition and review minutes.

The engineering tradeoff is that Askovo keeps several notions of “good evidence” visible at once. This is more work than displaying one confidence percentage. It also makes the system harder to misuse as a universal answer generator. The score that is easiest to read is often the one that hides the type error.

### Source and verification links

- [`sure_engine.py`: import ceilings, evidence qualification, and context export](https://github.com/roy-tong/Askovo/blob/main/skills/askovo/scripts/sure_engine.py)
- [Import-level tests](https://github.com/roy-tong/Askovo/blob/main/tests/test_p0_import_levels.py)
- [Delivery conclusion-gate tests](https://github.com/roy-tong/Askovo/blob/main/tests/test_delivery_conclusion_gate.py)
- [Context-export tests](https://github.com/roy-tong/Askovo/blob/main/tests/test_context_export.py)
- [Askovo changelog](https://github.com/roy-tong/Askovo/blob/main/CHANGELOG.md)

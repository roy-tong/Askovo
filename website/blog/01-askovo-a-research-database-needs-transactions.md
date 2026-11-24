# Askovo: a research database needs transaction semantics

*Evidence graphs, immutable decision records, request-scoped snapshots, and a deterministic response to contradiction.*

A report generator can tolerate a stale read. A decision system should not.

Suppose an audit reads version A of a study. Before the final brief is rendered, another process appends counter-evidence and commits version B. If the brief uses A for one section and B for another, every individual input may be valid. The resulting report is still wrong: no such study revision ever existed.

Askovo 2.22 addressed this class of failure by giving research requests snapshot and transaction semantics. The follow-up 2.22.1 release closed two less obvious gaps: request snapshots could interact badly with the old 32-entry parsed-data cache, and two processes could pass an observation identity check before either acquired the append lock.

That work is a useful lens through which to examine the product. Askovo is not trying to make a fluent report the unit of truth. It maintains a versioned relationship among evidence, inference, decisions, and subsequent observations. The database layer is part of the research method.

## The canonical objects are smaller than the reports

A study has several files with deliberately different responsibilities:

```text
study.json                              # question, owner, scope, method
02-data/evidence.jsonl                  # registered evidence and provenance
04-findings/demand-judgments.json       # demand/commercial evidence judgments
04-findings/product-reasoning.json      # live product/business reasoning
01-sources/observations.jsonl           # product-behavior observations
05-audit/                               # generated audit outputs
06-report/                              # generated projections
```

The live reasoning spine is:

```text
scene → user → pain → need → feature → product → business
```

Reports, MRDs, PRDs, BRDs, web pages, and role-specific deliverables are projections of `product-reasoning.json`, not independent conclusions. A chain points to a demand judgment through `demand_judgment_id`; evidence must also share the chain's `context_key`. This prevents a record collected for one market, account, or study context from becoming convenient support for another.

The separation is more than file hygiene. It allows Askovo to reject several different failure modes explicitly:

- a node has an evidence ID, but the evidence belongs to another context;
- an evidence record is authentic, but its type cannot support the claim being made;
- a business node is marked `decided`, but delivery, observed outcome, and causal state have not been established;
- a report contains a conclusion even though the full evidence gate failed.

An imported record cannot simply declare itself E5 transaction evidence. E4+ transaction or purchase claims require a counterparty, timestamp, amount, source reference, and evidence reference. Missing structure holds the record at E2 and preserves the derivation rule. A line of text labeled “transaction” does not thereby become a receipt.

## Product observations carry their own scope

Askovo also accepts product-behavior observations, but their schema makes overgeneralization awkward:

```json
{
  "observation_id": "obs-mobile-001",
  "product_version": "2.22.1",
  "account_permission": "owner",
  "platform": "macos",
  "region": "cn",
  "tested_at": "2026-11-23T10:00:00Z",
  "method": "scripted",
  "claims": [{
    "claim_id": "claim-001",
    "observed_facts": ["The CLI returned STALE_SOURCE after a source rewrite"],
    "inferred_rule": "An active request refuses a mixed study revision",
    "uncovered_conditions": ["Windows file-locking behavior was not exercised"],
    "generalization": "single_case",
    "repeat_count": 1,
    "evidence_level": "E2",
    "basis": "product_behavior_observation"
  }]
}
```

The three generalization values have executable definitions:

| Declaration | Minimum evidence in the record |
| --- | --- |
| `single_case` | Exactly one run; `not_generalizable=true` on export |
| `repeated` | At least two runs |
| `multi_context` | At least two runs and two distinct `(product_version, account_permission, platform, region)` tuples |

There is no `universal` value. Observations are capped at E2, and export into `01-sources/observations.jsonl` does not promote them into the main evidence pool. Named human semantic review is still required.

This is a useful distinction between data collection and claim generation. The schema preserves `observed_facts`, `inferred_rule`, and `uncovered_conditions` in separate fields. A collector cannot turn “I saw this once” into “the product always works” without leaving a visible validation error.

## Request snapshots solve a different problem from an LRU cache

The 2.22 implementation centers on two classes:

- `StudyRepository` owns path containment, byte reads, atomic writes, transactions, and the source-version manifest.
- `StudyContext` owns one request's immutable byte snapshot and parsed-data caches.

The manifest hashes every study-contained file with SHA-256, excluding generated `05-audit/` and `06-report/` outputs. Request activation is equivalent to:

```python
manifest = repository.version_manifest()
assert_write_journal_clean()

yield context  # on successful completion of the request body:
assert_write_journal_clean()
assert repository.version_manifest() == manifest
```

If another process commits a multi-file change during the request, delivery fails with `STALE_SOURCE`. Askovo does not merge the new evidence into half of the output, and it does not silently return the old report as current. The legal next action is to retry audit and delivery against the newly committed revision.

Inside the request, `StudyContext.read_bytes()` memoizes raw bytes in a request-scoped dictionary. Parsed JSON and JSONL reads return deep copies, so a caller mutating a nested claim cannot alter what another projection reads. The JSONL cache key includes the resolved path, a 128-bit BLAKE2b digest of the raw bytes, the parser identity, and strictness.

The older 32-entry LRU still has a compatibility role for parsed data. It is not the request isolation boundary. In 2.22.1, raw request snapshots stopped being subordinate to that capacity limit. This distinction matters: an LRU is a memory-management optimization, while a snapshot is a correctness contract. Replacing one with the other produces the kind of bug that looks like an occasional research inconsistency rather than a storage error.

The repository also rejects paths that resolve outside the study. That is a separate boundary from revision stability: a source reference should not turn a report generator into an arbitrary local-file reader.

## Observation export is idempotent by content, not by metadata

Observation export uses the identity:

```python
(observation_id, claim_id, source_hash)
```

`source_hash` is SHA-256 of the source observation file. The export procedure is:

```python
with repository.transaction("observation export") as txn:
    existing = read_existing_identities(target)
    new_lines = [line for line in projected if identity(line) not in existing]
    if new_lines:
        txn.add(target, append_jsonl(new_lines), mode="append")
        txn.commit()
```

A repeated export of the same bytes returns `added=0`. Editing an observation while preserving its ID and metadata changes the hash, so the export becomes a new revision rather than disappearing as a duplicate. Identity checking and append writing hold the same study transaction lock, closing the two-process window in which both exporters could decide that a claim was absent.

This is a deliberately narrow idempotency contract. It does not say that two observation files with different hashes are semantically different claims. It says the system will not erase a source revision merely because the metadata looks familiar.

The tests cover repeated exports, concurrent export, changed source hashes, corrupt history, interrupted append recovery, invalid stored documents, and preservation of previous bytes after transaction failure. I ran the study-context and observation suites while preparing this article: 29 tests passed.

## A contradiction triggers a state transition, not a new essay

Decision records are append-only snapshots of the canonical chain. Each record carries a version, parent version, decision-maker, chain fingerprint, chain snapshot, original hypothesis, current candidate actions, and supporting state. Ordinary observations do not modify the live recommendation.

An adversarial revision is allowed only under a more demanding contract:

1. An initial `DecisionRecord` must exist.
2. The contradiction ID must be registered in `02-data/evidence.jsonl`.
3. The evidence must share the chain's `context_key`.
4. `evidence_level`, `evidence_basis`, and `source_ref` must be present.
5. A pre-recorded `contradicts` or counter-evidence relation must exist in the evidence stance, chain counter list, linked demand judgment, or loop mappings.

Passing those checks does not invoke an LLM to write a rebuttal. The code applies one deterministic transition:

```python
confidence_scale = ("very-low", "low", "medium", "high")
new_confidence = confidence_scale[max(0, old_index - 1)]

chain.status = "needs-validation"
chain.nodes.product.status = "needs-validation"
chain.nodes.business.status = "needs-validation"
chain.nodes.business.gate.decision = "hold"  # unless a human supplies a replacement
```

The public synthetic regression provides a concrete before/after:

```text
DecisionRecord version:       1 → 2
recommendation_origin:        deterministic_safe_hold
recommendation_code:          hold
confidence:                   low → very-low
chain/product/business:       needs-validation
candidate_evidence_promoted:  false
demand_judgment_changed:      false
causal_status_changed:        false
full audit:                   PASS
```

Two details are especially important. The demand-judgment file remains byte-identical, and the supporting states remain unchanged. The system reopens the decision; it does not rewrite the evidence base to justify the new state. A separate test supplies an evidence ID without a recorded contradiction mapping. The command exits 2 and leaves the canonical reasoning bytes untouched.

A human can provide an explicit replacement recommendation. That produces `recommendation_origin=decision_maker_override`, not a pretend semantic inference by the CLI.

The decision commands are:

```bash
askovo decision record STUDY --chain PR01 --by "Product owner"
askovo decision record STUDY --chain PR01 --by "Product owner" \
  --contradiction EVIDENCE_ID
askovo decision replay STUDY --chain PR01 --json
```

The [public decision-replay page](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html) links to the actual regression. I ran it again for this article; it passed.

## Proof export deliberately produces an incomplete proof

Askovo can project a study into OVO's shared Proof Bundle format:

```bash
askovo proof export STUDY --out NEW_DIR --by NAME
```

The exporter first rebuilds or reads the Decision Brief, removes excerpts and replaces direct source locations with evidence IDs in the safe projection, hashes the canonical inputs, and writes into a staging directory. The output must be outside the source study, and an existing output is never overwritten.

Its checks are intentionally asymmetric:

| Check | Level | Normal status | Reason |
| --- | --- | --- | --- |
| `artifact-readable` | P1 | `PASS`, or `EXPIRED` if the brief is stale | The brief is a readable projection of identified inputs |
| `independent-semantic-review` | P3 | `UNCHECKED` | The exporter cannot approve research semantics |
| `external-decision-adoption` | P4 | `UNCHECKED` | No owner disposition is bundled automatically |
| `replay-readiness` | P1 | `INDETERMINATE` | Private canonical inputs and collection history are not copied |

A normal export therefore has `proof_status=BLOCKED`. That is not an exporter failure. It is the expected consequence of separating “we generated a valid brief” from “an independent reviewer accepted the reasoning” and “the owner actually used it.”

Askovo does have a separate adoption command, but it records a named owner's declaration and supplied receipt text. It does not verify the owner's identity or infer commercial success. A declaration is useful evidence; it is not magically an independent observation.

Privacy and replay pull in opposite directions here. Copying every canonical input would make third-party replay easier and leak the study. The exporter chooses the safer default: keep the proof structurally reviewable and mark full replay unavailable until authorized inputs are supplied.

## What the second use should measure

One internal Askovo study analyzed 109,429 deduplicated comments from eight communities over 24 months. The resulting recommendation changed a golf-device sequence from dedicated camera hardware to validating software and export workflows first. The sample was a convenience sample, so it cannot support a market-prevalence estimate. The useful result was a change in the proposed allocation of product effort.

The equivalent software test is not whether another report can be generated. It is whether a second decision review preserves the original decision, imports new evidence without corrupting the old basis, and reduces unnecessary rework while exposing its human minutes.

A useful second-use record therefore includes:

- the original leaning and alternatives, recorded before the new evidence;
- the new evidence hash and its relationship to earlier claims;
- the owner's actual disposition: maintain, change, defer, or collect evidence;
- review and correction minutes;
- the checks that remained unchecked;
- an independent review, if one occurred.

Replaying the same fixture twice is a determinism test. A second use is a new decision revision or an independent decision with its own context.

## The tradeoffs are visible in the implementation

Askovo's approach has costs. A whole-study manifest requires reading source files at request boundaries; the project does not claim that this is the fastest design for very large studies. JSON and JSONL make the research inspectable and version-control friendly, but they require explicit transaction discipline that a database would otherwise help provide. Snapshot isolation favors a coherent report over immediate incorporation of newly arriving evidence.

The deterministic safe hold is similarly a product choice. It cannot decide whether a contradiction is semantically valid, representative, or important. It only guarantees that a registered, same-context, mapped contradiction cannot be ignored by the current recommendation machinery. Human review remains responsible for the meaning.

Those constraints are preferable to a system that always produces an answer. A research tool should be able to return `STALE_SOURCE`, reject an unsupported evidence grade, preserve an unknown, or reopen a decision. Otherwise its consistency is only typographic.

### Source and verification links

- [`study_context.py`: repository, snapshots, manifests, and request activation](https://github.com/roy-tong/Askovo/blob/main/skills/askovo/scripts/study_context.py)
- [`observation.py`: observation schema and transactional export](https://github.com/roy-tong/Askovo/blob/main/skills/askovo/scripts/observation.py)
- [`decision_review.py`: contradiction validation and deterministic safe hold](https://github.com/roy-tong/Askovo/blob/main/skills/askovo/scripts/decision_review.py)
- [`proof_export.py`: P1/P3/P4 checks and replay boundaries](https://github.com/roy-tong/Askovo/blob/main/skills/askovo/scripts/proof_export.py)
- [Decision-replay example and runnable regression](https://roy-tong.github.io/Askovo/en/examples/decision-replay.html)
- [Askovo changelog](https://github.com/roy-tong/Askovo/blob/main/CHANGELOG.md)

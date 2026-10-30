# Unnamed-experience research (命名前研究)

Use this reference when the studied product or experience is novel enough that users have no settled vocabulary for it — a frontier product, a new sensation, an interaction that has not been productized. Keyword-driven collection assumes the experience already has a name. When it does not, searching product terms finds the already-named adjacent market and silently misses the actual demand. Read [research-protocol.md](research-protocol.md) and [data-contract.md](data-contract.md) first; this phase runs **before** `askovo.py plan` route design and produces the scope boundary and seed lexicon that plan consumes.

This phase is enabled with `askovo.py plan --mode unnamed-experience`.

## Principle

Demand for an unnamed experience leaves evidence that does not depend on product vocabulary: the words users invent, the things they already do to get the experience, the physical dimensions of the stimulus, and what adjacent disciplines have measured. Ground the study in those four signals first; keywords are an **output** of this phase, not an input.

## The four grounding paths

### 1. Edge-language mining (边缘语言挖掘)

Users describing an experience they cannot name reach for proto-words — non-organ, sensory-metaphor terms ("rumbly", "thuddy", "waves", "tingling", "flutter") rather than product language.

Operational steps:

1. Harvest proto-language from open-scene material (open forums, experience threads, sensory communities) where no product is discussed.
2. Record each candidate term in `01-sources/lexicon.csv` with `term_type=proto_word`, `grounding_path=edge_language`, and a source anchor.
3. Quantify each term against the graded corpus: record count, corpus-role spread, and level distribution. The acceptance association proxy is the share of the term's records graded E3+ (explicit acceptance/preference) versus E1/E2 (problem only).
4. Retain terms with both yield and association; drop terms that only co-occur with unrelated topics. Retention and drop reasons stay in the lexicon `status` and `notes` columns.

Claim boundary: a proto-word cluster is an E1 discovery signal. It tells you the experience is being talked about; it does not by itself show acceptance of any solution.

### 2. Substitute-behavior archaeology (替代行为考古)

Users obtain un-productized experiences through DIY and appropriation: repurposed objects, improvised rigs, borrowed devices, compensating habits. Because acting costs more than talking, these behaviors are revealed preference — the hardest "demand fossils" (需求化石).

Operational steps:

1. Search for behavior, not product: how people manufacture the experience today (improvised tools, household-object appropriation, workarounds, ritual hacks).
2. For each behavior record: what experience it produces, what it costs (money, time, privacy, dignity, safety), what fails, and under which scene it is triggered.
3. Map each fossil to the askovo demand unit — the substitute slot is the behavior itself; friction and consequence come from the DIY cost.
4. Treat safety-hazard DIY (mains electricity, restraint, unsanitary improvisation) as elevated-priority evidence and as a design-safety input, not as a marketing signal.

Claim boundary: a substitute fossil is E2 — observed substitute plus friction. It is the strongest pre-market demand signal in this method. It still does not show acceptance of *your* solution; that remains E3.

### 3. Psychophysical dimension mapping (心理物理维度框架)

Define the experience space by the physical dimensions of the stimulus rather than by words: frequency, amplitude, speed, temperature, humidity, trajectory, rhythm, contact area, pressure distribution, and domain-specific axes.

Operational steps:

1. Enumerate the stimulus dimensions in `01-sources/experience-space.csv` with ranges and units.
2. Mark which regions existing products cover (from the direct-solution evidence family) and which regions user behaviors or complaints reach.
3. White space = regions users reach through substitutes or proto-language but no product covers. A white-space claim must cite the evidence records that reach it.
4. Use the map to size and route collection: each untested region becomes a route or a hypothesis, not a conclusion.

Claim boundary: the dimension map frames hypotheses. An uncovered region is E0 context until records place users in it.

### 4. Cross-domain analogy with literature anchors (跨域类比 + 文献锚点)

Adjacent disciplines have already measured parts of the space: CT-discriminating pleasant touch (affective touch literature), vibration pleasantness by frequency, ASMR trigger taxonomies, haptics, thermal comfort. Use them as anchors.

Operational steps:

1. For each analogy, record the anchor claim, the source, and the mapping into this study's dimension space.
2. Convert each anchor into a falsifiable study hypothesis with an explicit bridge ("IF pleasant-touch afferents respond to low-force, low-velocity stroking AND users' DIY behaviors cluster in that regime, THEN ...").
3. Guard the analogy scope: literature describes measured responses, not your users' demand, and sampled populations often differ from the target market.

Claim boundary: literature anchors are E0 external context. They may shape hypotheses and instruments; they are never counted as user-demand evidence, and an analogy is discarded the moment target-market evidence contradicts it.

### 5. First-principles disciplinary derivation (学科推演)

When the space is thin even in adjacent literature, derive from mechanism: the physics/physiology of the stimulus, the perceptual and hedonic machinery, and the economics of provision. The derivation must still terminate in observable, collectable behaviors or expressions — a derivation that cannot name what a user would do or say is not yet researchable.

## Outputs of this phase

1. `01-sources/lexicon.csv` — seed terms from the paths above, each with type, path, definition, source anchor, expected signal, and status. Minimum design gate: at least 5 retained candidate terms across at least 2 grounding paths.
2. `01-sources/experience-space.csv` — stimulus dimensions, ranges, and coverage marks (required when the psychophysical path is used).
3. Scope boundary and prohibited inferences — what is in the experience space, what adjacent-but-different experiences are explicitly excluded, and what the lexicon cannot support claiming.
4. Route design downstream: `plan` quotas and platform routes must draw their queries from the retained lexicon and the uncovered dimension regions, not from generic product words.

## Evidence fields

Evidence records may carry two optional fields produced by this phase:

- `lexicon_terms`: the retained lexicon terms the record instantiates (array of strings).
- `grounding_path`: `edge_language` | `substitute_behavior` | `psychophysical` | `cross_domain` | `discipline`.

`askovo.py lexicon STUDY` computes per-term and per-path yield, level distribution, the acceptance-association proxy, zero-yield terms, and a sufficiency verdict (`--min-per-term N`). Insufficiency (exit code 1) is a research status: it means collect more through the planned routes, not loosen the gate.

## Stock-corpus sufficiency, then sized collection

The grounded flow for a frontier product is:

1. Ground the lexicon and dimension space (this phase).
2. Run `askovo.py lexicon` against the **existing** corpus. Sufficient = every critical term and path passes its minimum yield. Insufficient terms name exactly what the stock data cannot answer.
3. When collecting new data, size intake to the cleaned target, not the raw count. Expect a 3–5× raw-to-claim-eligible reduction from date, completeness, relevance, and dedup filters; `plan` records this estimate. A cleaned corpus in the tens of thousands is a reasonable floor for a decision-grade frontier study; the exact target comes from the decision contract, not from ambition.
4. Produce the report on the full graded corpus; the report keeps the grounding section separate from the demand judgments so readers can see which conclusions rest on fossils and which on named-market evidence.

## Biases specific to this phase

- **Naming bias**: once a proto-word is adopted by the team, every ambiguous record starts looking like an instance. Keep the drop reasons in the lexicon; re-test the term's association after adoption.
- **Fossil survivorship**: DIY posts overrepresent enthusiastic or extreme improvisers. Pair the fossil hunt with control routes where the experience is absent or adequately served.
- **Dimension reification**: the map is a lens, not the space. New dimensions may emerge from the data; add them to the experience-space file with evidence.
- **Analogy overreach**: the anchor literature's population, instrument, and context are not your market's. State the bridge explicitly and let contradicting target-market evidence override it.

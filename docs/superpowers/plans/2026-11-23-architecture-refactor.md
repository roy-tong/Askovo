# Askovo Compatible Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a request-scoped study snapshot, bounded parsing caches and one storage boundary while preserving every CLI/MCP command, canonical file and research verdict.

**Architecture:** Keep `askovo.py` and `sure_engine.py` as compatibility facades. Put file access and cache ownership in `StudyRepository` / `StudyContext`; activate the context with a `ContextVar` for one audit-and-deliver request so existing validators can share it without changing their public signatures.

**Tech Stack:** Python 3.9–3.12 standard library, `unittest`, JSON/JSONL, existing `write_integrity.Transaction`.

## Global Constraints

- Core runtime remains standard-library only and Python 3.9 compatible; no `match` statements.
- `product-reasoning.json`, evidence grades E0–E5 and DecisionRecord semantics remain canonical and unchanged.
- CLI/MCP/Skill behavior stays aligned; malformed evidence never becomes qualified evidence.
- Existing tests and direct path-based module loading remain supported.
- Run `python3 -m unittest discover -s tests` before every release commit.

---

### Task 1: Bounded cache and study snapshot

**Files:**
- Create: `skills/askovo/scripts/study_context.py`
- Test: `tests/test_study_context.py`

**Interfaces:**
- Produces: `BoundedJsonlCache(max_entries=32)`, `StudyRepository(study_dir)`, `StudyContext(repository)`, `current_study_context()`.
- `StudyContext.read_bytes(path)`, `read_json(path)`, `read_jsonl(path, parser, strict=True)` return caller-safe copies while parsing each digest once.

- [ ] **Step 1: Write failing cache/snapshot tests**

```python
cache = BoundedJsonlCache(max_entries=2)
cache.put("a", [1]); cache.put("b", [2]); cache.put("c", [3])
assert len(cache) == 2 and cache.get("a") is None
with StudyContext(StudyRepository(study)).activate():
    first = current_study_context().read_jsonl(evidence, parser)
    evidence.write_text(changed)
    second = current_study_context().read_jsonl(evidence, parser)
assert first == second  # one request, one immutable snapshot
```

- [ ] **Step 2: Run tests and confirm import/behavior failure**

Run: `python3 -m unittest tests.test_study_context -v`
Expected: FAIL because `study_context` does not exist.

- [ ] **Step 3: Implement LRU, repository containment and context activation**

Use `OrderedDict` for LRU eviction, BLAKE2b content digests, a `ContextVar` token reset in `finally`, and deep/shallow copies matching current callers. Strict JSONL errors include the line number; lenient mode returns only object rows for legacy diagnostics.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_study_context tests.test_jsonl_parse_cache -v`
Expected: PASS, including same-size rewrite invalidation and row-annotation isolation.

- [ ] **Step 5: Commit**

```bash
git add skills/askovo/scripts/study_context.py tests/test_study_context.py
git commit -m "refactor: add bounded request-scoped study snapshots"
```

### Task 2: Route CLI and SURE reads through the snapshot

**Files:**
- Modify: `skills/askovo/scripts/askovo.py` (`_load_json`, `_load_jsonl`, `command_deliver`)
- Modify: `skills/askovo/scripts/sure_engine.py` (`load_json`, `_read_jsonl_rows`, `deliver`)
- Test: `tests/test_study_context.py`, `tests/test_jsonl_parse_cache.py`

**Interfaces:**
- Consumes Task 1 context APIs.
- Preserves `_JSONL_PARSE_CACHE.clear()` and `_parse_jsonl_bytes()` for existing callers/tests.

- [ ] **Step 1: Add failing integration assertions**

Wrap `command_deliver` in a test context, patch both JSONL parsers, and assert one parse per digest across `audit_study` plus `sure_engine.deliver`; assert two sequential commands do not share stale snapshots.

- [ ] **Step 2: Verify the new assertion fails**

Run: `python3 -m unittest tests.test_study_context.StudyContextIntegrationTests -v`
Expected: FAIL with multiple parses or missing active context.

- [ ] **Step 3: Implement bounded legacy cache and request activation**

`_load_jsonl` delegates to the active context when present and otherwise uses a module-level `BoundedJsonlCache`. `command_deliver` activates one context around both audit and delivery. SURE readers use the same context only for paths inside its study; catalog/assets remain normal reads.

- [ ] **Step 4: Run evidence/delivery regressions**

Run: `python3 -m unittest tests.test_study_context tests.test_jsonl_parse_cache tests.test_p0_evidence_trust tests.test_delivery_conclusion_gate -v`
Expected: PASS with unchanged evidence gates.

- [ ] **Step 5: Commit**

```bash
git add skills/askovo/scripts/askovo.py skills/askovo/scripts/sure_engine.py tests/test_study_context.py tests/test_jsonl_parse_cache.py
git commit -m "refactor: share one study snapshot across audit and delivery"
```

### Task 3: Make observation export transactional and idempotent

**Files:**
- Modify: `skills/askovo/scripts/study_context.py`
- Modify: `skills/askovo/scripts/observation.py`
- Test: `tests/test_observation.py`

**Interfaces:**
- Produces `StudyRepository.transaction(purpose)` returning `write_integrity.Transaction` and `StudyRepository.atomic_write_text(path, text)` for standalone stores.

- [ ] **Step 1: Add failing repeat-export and interrupted-write tests**

Record one observation, export twice, and assert the second export adds zero duplicate claim lines. Patch `Transaction.commit` to fail and assert the previous observations file remains byte-identical.

- [ ] **Step 2: Run and confirm failure**

Run: `python3 -m unittest tests.test_observation -v`
Expected: FAIL because the current export appends every claim again.

- [ ] **Step 3: Implement transactional append with stable claim identity**

Read existing `(observation_id, claim_id, source_hash)` tuples, stage only new lines with `mode="append"`, and commit through the existing study journal. Standalone observation records use same-directory atomic replacement.

- [ ] **Step 4: Run observation and transaction suites**

Run: `python3 -m unittest tests.test_observation tests.test_issue_write_integrity -v`
Expected: PASS; reviewed/exported source observations remain immutable.

- [ ] **Step 5: Commit**

```bash
git add skills/askovo/scripts/study_context.py skills/askovo/scripts/observation.py tests/test_observation.py
git commit -m "fix: make observation export atomic and idempotent"
```

### Task 4: Runtime import and documentation compatibility

**Files:**
- Modify: `skills/askovo/scripts/sure_engine.py`
- Modify: `docs/sure-engine.md`, `AGENTS.md`
- Test: `tests/test_askovo_import_isolation.py`

**Interfaces:**
- Preserves public SURE names while replacing repeated custom fallback blocks with standard sibling imports after a non-shadowing script-path append.

- [ ] **Step 1: Write a failing isolation test**

Load the thin `askovo` package and direct `sure_engine` in both orders in fresh subprocesses; assert package identity and one instance of each sibling module.

- [ ] **Step 2: Confirm the old loader cannot satisfy the single-instance assertion**

Run: `python3 -m unittest tests.test_askovo_import_isolation -v`
Expected: FAIL on duplicate module identity or residual custom loader behavior.

- [ ] **Step 3: Implement non-shadowing imports and document ownership**

Append the script directory only when absent, import siblings normally, and keep the CDP lazy loader as one explicit runtime boundary. Document `StudyContext` and repository responsibilities in `docs/sure-engine.md` and `AGENTS.md`.

- [ ] **Step 4: Run import, CLI and MCP regressions**

Run: `python3 -m unittest tests.test_askovo_import_isolation tests.test_askovo_cli tests.test_askovo_mcp -v`
Expected: PASS with identical commands and tool results.

- [ ] **Step 5: Commit**

```bash
git add skills/askovo/scripts/sure_engine.py docs/sure-engine.md AGENTS.md tests/test_askovo_import_isolation.py
git commit -m "refactor: isolate Askovo runtime imports"
```

### Task 5: Full verification and release

**Files:**
- Modify: `VERSION`, `CHANGELOG.md`, `docs/feature-status.md`, release notes as required by `RELEASING.md`.

- [ ] **Step 1: Run the complete suite and website checks**

Run: `python3 -m unittest discover -s tests && python3 scripts/seo_check.py`
Expected: all tests and zero SEO errors.

- [ ] **Step 2: Build and install the wheel outside the checkout**

Run the packaging workflow commands from `RELEASING.md`; execute `askovo doctor`, `askovo demo`, one `proof export`, and one audit-and-deliver sample from the installed artifact.

- [ ] **Step 3: Commit the release**

Bump one patch/minor version according to the final public behavior, document the refactor and performance changes, then commit all verified files.

- [ ] **Step 4: Merge, push, tag and verify deployment**

Push the refactor branch, merge it into `main` with a fast-forward or explicit merge commit, push `main`, create the repository's prescribed release tag, and verify the GitHub Release/PyPI/Pages workflows and public URLs.

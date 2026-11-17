# Platform field notes — experienced restrictions and solutions

The multi-platform campaign (2026-11, ≈110k records) kept hitting the same
platform limits, and every limit came with a channel that worked. That experience
now lives in one machine-readable registry:
[`../assets/platform-field-notes.json`](../assets/platform-field-notes.json).

Planning, `askovo doctor`, the platform radar and every projection read the same
registry, so field knowledge cannot drift into a prose document sitting beside the
catalog.

**A field note is not an approval.** Access permission stays in
`assets/platform-catalog.json` (`access_modes`, `decision`, `cdp`, `bulk`) plus the
study's `scope.allowed_sources`, the adapter switch, the Design gate, human
`--ack-terms` and an approved visible URL. A note records what happened in the
field and which channel worked; it never turns a blocked route into a collectable
one, and it never authorizes a challenge bypass or a credential shortcut.

## Registry schema

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable note id (`<platform>-<restriction>`), unique |
| `platform` | yes | Catalog platform id, a declared `source_types` key, or `*` for cross-platform practice |
| `channel` | yes | The channel the note is about (`arctic_shift_archive_api`, `cdp_visible_page`, `cdp_user_session`, `multi_channel`, …) |
| `restriction` | yes | The platform limit in one sentence |
| `symptom` | yes | What the operator observes when the limit hits |
| `detector` | no | How to confirm it is this restriction and not a script bug |
| `solution` | yes | The field-verified way through (bounded, passive, honest) |
| `artifact` | yes | Repo-relative path of the code or reference that implements it |
| `helper` | no | `module.attr` under `skills/askovo/scripts/` that encodes the mechanism |
| `verification` | yes | `{status, date, evidence}` — status from the legend, evidence is what was actually run |
| `cdp` | yes | Whether the note is about a CDP channel; must match the platform catalog for catalog platforms |

## Verification legend

| Status | Means |
|---|---|
| `verified` | Run end-to-end at scale in the field |
| `partially_verified` | Channel works and extraction started; the run did not finish |
| `login_verified` | Session/login works; collection not started |
| `channel_verified` | Page renders over the channel; the run was not executed |

Never upgrade a status without a run to point at. `partially_verified` and
`login_verified` are honest states here — X / Instagram / TikTok methods are
documented and deliberately have no collector.

## How the engine consumes it

```bash
# Known traps for the platforms the radar recommends
askovo platforms "Discord 社区和 Kickstarter 众筹评论里的用户抱怨" --field-notes

# One platform, full table (catalog platform or a source type such as vertical_forum)
askovo platforms "Kickstarter 众筹评论" --platform kickstarter --field-notes

# Machine-readable: every ranked entry carries field_notes, plus top-level field_notes
askovo platforms "Kickstarter 众筹评论" --json

# Registry consistency gate (required fields, artifacts, helper refs, cdp ⇔ catalog)
askovo doctor
```

`platform_fit` attaches the notes of the recommended platforms (cross-platform
practice included) to each entry; `platform_markdown` renders a
"known restrictions and solutions" section; `askovo doctor` fails when an artifact
or helper reference rots or a note's `cdp` flag contradicts the catalog.

## Runtime helpers

The registry points at the code that encodes each reusable mechanism:

| Helper | Implements |
|---|---|
| `connectors.common.classify_backoff` | 429/403 reset-header waits, 422 "slow down" exponential retry, permanent-status stop |
| `connectors.common.single_writer_state` | Exclusive pid lock on a state file (stale-owner reclaim, live-owner stop) |
| `connectors.common.parse_relative_time` | "10 months ago" / "3小时前" / "2일 전" / "5 分前" → approximate UTC + `date_precision` |
| `connectors.common.atomic_write_json` | Persist after every round through a sibling temp file |
| `connectors.cdp_runtime.wait_for_challenge_clear` | Passive challenge polling; interactive = hard stop |
| `connectors.cdp_runtime.wheel_scroll` | Real `Input.dispatchMouseEvent` wheel after a mouse move |
| `connectors.cdp_runtime.rebind_tab` | Re-list tabs and re-bind by stable id (URL patterns rot) |
| `connectors.cdp_runtime.bounded_load_more` | Capped burst-click expansion until the list stops growing |
| `connectors.cdp_runtime.run_lanes` | Parallel lanes, isolated failures, one tab per site |
| `connectors.rotation.RotationScheduler` | Multi-platform rotation: per-site cadence, classified cooldown, session gate, daily quota, resume |

`python3 skills/askovo/scripts/connectors/cdp_runtime.py --selftest` checks the
pure helpers offline.

## Cross-platform strategies

Restrictions are per platform; some of the strongest lessons are about how to
combine platforms so that **no site ever sees a higher request frequency**. Those
live in the same registry under `strategies`, each with an explicit `invariant`
(the constraint that must not break) and the runtime helper that enforces it:

| Strategy | Platforms | Invariant | Mechanism | Verification |
|---|---|---|---|---|
| **Platform rotation (one round per platform, then switch)** (`platform-rotation`) | * | Per-site request cadence never rises. Total throughput comes from overlapping different sites, never from hammering one. | Run one round per platform, then switch. Each site only sees its own tab's sequential requests, so its observed interval stays flat while another site's render wait is overlapped (field: Instagram ×1 ∥ GolfWRX ×2 per cell). | verified（2026-11-17） |
| **One tab per site (the frequency invariant)** (`per-site-frequency-invariant`) | * | A site must never see two tabs' worth of requests. Two tabs on one site double its rate — that is risk-control pressure, not parallelism. | Assign each lane a distinct site; the lane runner rejects duplicate site keys. Spend the scarce logged-in browser across different sites, not within one. | verified（2026-11-17） |
| **One writer per archive provider, hand quota to the higher-yield lane** (`single-writer-quota`) | reddit | One client per provider per IP. A duplicate client multiplies 422 storms and starves both, so neither throttle diagnosis is trustworthy. | ps → kill duplicates → resume the survivor from its state file → then judge provider load. Pause the low-yield lane to hand the quota to the high-yield one (field: golf-main paused so equipment keywords got the whole archive quota). | verified（2026-11-17） |
| **Pivot channels, never identities** (`backup-channel-pivot`) | reddit, vertical_forum | No account, proxy, key or identity rotation: a blocked channel is recorded as a gap and the run switches to another authorized channel. | PullPush commercial wall → stop planning it as a backup; keep a single arctic client with backoff, and move volume to a browser-visible forum channel in the same vertical (GolfWRX). | verified（2026-11-17） |
| **Windowed search (time buckets instead of deep pagination)** (`windowed-search`) | x | No scroll past the stall and no request-rate ramp: history is rebuilt by time windows, deduped by post id across windows. | Drive the logged-in search page with since:/until: half-year windows; collect each window with real wheel events; dedupe by status id and keep the window tag for traceability (field: 7 windows back to 2023, ~25–30 mentions each). | verified（2026-11-17） |
| **Session health, cooldown, human re-login** (`session-health-cooldown`) | discord, x, instagram, tiktok | A dropped session is re-authenticated by the human, never by the agent; the platform cools down before any retry, and other platforms keep working meanwhile. | Detect the drop → put the platform in cooldown (default 30 min) → human re-login → re-verify the session → resume. Rotate to another platform while one cools down; never rapid re-auth. | verified（2026-11-17） |
| **Batch auto-relay (no idle quota gap)** (`batch-auto-relay`) | reddit, youtube | The next batch starts when the current process exits; state files checkpoint every batch; goal counting stays nominal + deduped so a relay never inflates the target. | Queue batches, chain them on process exit, keep one state file per route, and recompute the goal counter across files after each batch. | verified（2026-11-17） |
| **Multilingual query routes (avoid an English-biased corpus)** (`multilingual-routing`) | youtube, x, instagram | Locale coverage is a sampling decision, recorded per route; it is never inferred from an English query's yield. | Issue the same scene/equipment queries in each target language, tag routes per locale (yt-equip-kr / yt-equip-jp), and report yield per locale so a thin locale is visible as a gap. | verified（2026-11-17） |
| **Blank-render triage (200 + empty body is not a challenge)** (`blank-render-triage`) | vertical_forum | 200 + empty innerText = unsupported stack; never 'fix' it with more automation or a different identity. | Probe body innerText length and title; if both are empty after a render wait, mark the stack unsupported and pivot to another forum in the same vertical (GolfWRX vBulletin5 rendered; MyGolfSpy/Invision stayed blank). | channel_verified（2026-11-17） |
| **Cell budget headroom** (`cell-budget-headroom`) | * | A timeout must never tear an input event stream mid-dispatch — that signature reads as automation. | Leave ~30% headroom on every cell budget, prefer collecting less, and persist after each round; a torn cell is a stop signal, not a retry signal. | verified（2026-11-17） |
| **Nominal vs deduped goal counting** (`goal-counter-dedupe`) | * | Acceptance uses the deduped count; nominal counts stay visible only as a running estimate. | Recompute the counter across all output files after each batch: nominal per file, deduped total by record id, and per-route/locale breakdown so a thin route cannot hide behind a fat one. | verified（2026-11-17） |

How the engine surfaces them:

```bash
askovo platforms "<need>" --strategies    # the rotation plan for the recommended platforms
askovo platforms "<need>" --json          # plan-level strategies[] (field_notes stay per entry)
```

`platform_fit` attaches the applicable strategies (cross-platform practice
included) to the plan and to each recommended entry; `askovo doctor` gates the
strategy layer (required fields, platform ids, artifacts, helper references,
verification legend). The scheduler itself is importable:
`connectors/rotation.py` (`RotationScheduler`, `--selftest`, `--plan`).

A strategy is still experience, not permission: rotation lowers the frequency
each site observes, it never bypasses a platform limit, a challenge page, or a
login wall, and identities/proxies are never rotated.

## Index by platform

| Platform | Notes | Verification | Primary artifact |
|---|---|---|---|
| `reddit` | 4 | verified | `skills/askovo/references/reddit-research.md`<br>`skills/askovo/scripts/connectors/collect_arctic_windows.py` |
| `youtube` | 4 | verified | `skills/askovo/references/youtube-research.md`<br>`skills/askovo/scripts/connectors/collect_youtube_innertube.py` |
| `kickstarter` | 3 | verified | `skills/askovo/scripts/connectors/collect_cdp_kickstarter.py` |
| `discord` | 5 | verified | `skills/askovo/scripts/connectors/collect_cdp_discord.py` |
| `x` | 3 | partially_verified, verified | `skills/askovo/references/cdp-collection-playbook.md`<br>`skills/askovo/references/x-research.md` |
| `instagram` | 3 | partially_verified | `skills/askovo/references/social-media-source-adapters.md` |
| `tiktok` | 1 | login_verified | `skills/askovo/references/cdp-collection-playbook.md` |
| `vertical_forum` | 2 | channel_verified | `skills/askovo/references/cdp-collection-playbook.md` |
| `*` | 4 | verified | `skills/askovo/references/cdp-collection-playbook.md`<br>`skills/askovo/scripts/connectors/collect_arctic_windows.py` |

## Coverage boundary

Only channels this campaign exercised are recorded. The pre-existing CDP entries (amazon / bilibili / weibo) predate the campaign and carry no field note here; absence of a note is not evidence that the channel works or fails.

## How to add a note

1. Run it in the field first — a note needs an actual run, not a guess.
2. Keep one restriction per note; put the general lesson in a `*` note.
3. Point `artifact` at the repo-relative file that implements it and `helper` at the
   function that encodes it (both are validated).
4. Set `cdp` to match the platform catalog exactly; a mismatch fails `askovo doctor`.
5. Record the honest `verification.status` and evidence — partial runs stay partial.
6. Update `generated_at`, then run `askovo doctor` and the suite.

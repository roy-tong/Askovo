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

`python3 skills/askovo/scripts/connectors/cdp_runtime.py --selftest` checks the
pure helpers offline.

## Index by platform

| Platform | Notes | Verification | Primary artifact |
|---|---|---|---|
| `reddit` | 2 | verified | `skills/askovo/scripts/connectors/collect_arctic_windows.py` |
| `youtube` | 3 | verified | `skills/askovo/scripts/connectors/collect_youtube_innertube.py` |
| `kickstarter` | 3 | verified | `skills/askovo/scripts/connectors/collect_cdp_kickstarter.py` |
| `discord` | 5 | verified | `skills/askovo/scripts/connectors/collect_cdp_discord.py` |
| `x` | 2 | partially_verified | `skills/askovo/references/cdp-collection-playbook.md` |
| `instagram` | 3 | partially_verified | `skills/askovo/references/social-media-source-adapters.md` |
| `tiktok` | 1 | login_verified | `skills/askovo/references/cdp-collection-playbook.md` |
| `vertical_forum` | 1 | channel_verified | `skills/askovo/references/cdp-collection-playbook.md` |
| `*` | 4 | verified | `skills/askovo/references/cdp-collection-playbook.md` |

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

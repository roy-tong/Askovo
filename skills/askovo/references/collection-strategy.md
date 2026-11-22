# Collection strategy — access, budget, signals, breakers, output

This is the collection-side policy layer. It answers four questions for every run:
**may we touch this source at all**, **how hard may a run touch it**, **which signals
force a stop**, and **when does the output count as usable**.

The layers, in order of authority:

| Layer | File | Decides |
|---|---|---|
| Access | [`../assets/platform-catalog.json`](../assets/platform-catalog.json) | Whether a channel is `supported`, `limited` or `blocked`; allowed `access_modes`; `cdp` eligibility |
| Study scope | `study.json` → `scope.allowed_sources` | Whether this particular study may use that channel |
| Policy (this file) | [`../assets/platform-field-notes.json`](../assets/platform-field-notes.json) → `collection_policies` | Budget, signals, stop rules, output criteria |
| Runtime | `scripts/connectors/cdp_strategy.py`, `rotation.py` | Enforces the budget numbers mechanically |

**A policy is not an approval.** It never turns a blocked route into a collectable
one, never authorizes a challenge bypass, an identity rotation, a proxy pool or a
credential shortcut, and never overrides the catalog or the study scope. Where this
document and the catalog disagree, the catalog wins and the run stops.

Evidence grades used below:

- `official` — read in the platform's own terms, documentation or announcement.
- `craft` — consistent across several independent secondary reports; the primary
  page was not readable from here.
- `lead` — single source or operator experience; never gates an automated run.

The machine-readable form is `collection_policies` in
[`../assets/platform-field-notes.json`](../assets/platform-field-notes.json);
`askovo platforms "<need>" --collection-policies` renders it for the ranked set and
`askovo doctor` fails when it drifts from the catalog or the runtime budgets.

## 1. Access — what may be collected

Order of preference, always: **official API → authorized export / licensed dataset →
authorized visible page (`cdp: true` only) → nothing**. A missing route is recorded as
a gap, not filled with a workaround.

### Reddit

- **Allowed today:** OAuth Data API with an approved app; historical archive
  (Arctic Shift) as a supplement with source and snapshot time recorded.
- **Data API Terms (last revised 2026-07-20, `official`):** §2.4 forbids using User
  Content to train machine-learning or AI models without Reddit's permission; §2.8
  forbids misrepresenting your user agent or OAuth identity; §2.9 lets Reddit set and
  enforce request limits; §3.1 requires a separate agreement for commercial use or
  research beyond the free tier; §3.2 forbids circumventing limits.
- **2026 change (`craft`):** unauthenticated API requests returned 403 from
  mid-2026; the 2026-09-30 r/redditdev timeline ends free public API access —
  2026-10-31 last day for new app requests, 2027-01-12 unregistered apps cut,
  **2027-03 public API closed**, RSS retired 2026-11-13. Devvit is an in-platform
  app surface, not an external collection route.
- **Exit path:** historical archive (Arctic Shift) plus the study's own authorized
  export. PullPush sits behind a commercial wall and is not a backup plan.
- **Never:** HTML scraping of reddit.com, identity rotation after a ban, or training
  on collected text.

### Amazon

- **Allowed today:** Amazon Reviews 2023 dataset (review text), seller APIs (own
  catalog), and the Associates/Creators route for product metadata.
- **2026 change:** PA-API 5.0 was deprecated 2026-04-30 and shut down 2026-05-15;
  the successor Creators API uses OAuth and, per secondary reports, needs 30-day
  sales activity and starts around 1 request/second (`craft` for the quota details).
- **Never:** scraping product or review pages; review text is not bulk-available
  from the live site, and the ToS forbids automated collection.
- **Boundary:** seller/associate credentials are the account owner's; Askovo never
  asks for them, stores them or reads them from disk.

### Kickstarter

- **Allowed today:** authorized visible campaign/comment pages via CDP (`cdp: true`),
  historical datasets as background only.
- **Field reality (`verified`):** direct fetch returns 403 behind Cloudflare, comment
  sections are JS-rendered, and the GraphQL search endpoint is 403 to plain clients.
- **Never:** solving or farming Cloudflare challenges, rotating IPs, or driving the
  page faster than a human reading it. A challenge page means passive wait or a
  human; otherwise the run ends.
- **Open item:** whether the 2026 Terms of Use changed the automation clause was not
  readable as a diff; treat as `lead`.

### Instagram

- **Allowed today:** authorized creator/business export; Meta Content Library for
  eligible research; authorized visible pages via CDP for a logged-in session the
  user opened by hand.
- **2026 change:** the Basic Display API was fully deprecated on 2024-12-04;
  Graph API remains Business/Creator only at roughly 200 calls per user per hour
  (`official` for deprecation, `craft` for the rate figure); a commercial-terms
  pause was reported on 2026-11-20 (`craft`).
- **Never:** hashtag scraping, session-cookie export, or automation that Meta's
  terms treat as unauthorized collection. CDP is a transport for a page the operator
  may already read, not a scraping license.

### YouTube

- **Allowed today:** Data API v3 (10,000 units/day; `search` costs 100 units per
  call — `official`), the innertube connector for the public comment corpus, and
  authorized visible pages via the catalog-gated CDP exception after Design review.
- **Never:** unauthorized browser automation, stream downloading, or transcript
  extraction without rights confirmation. yt-dlp's default clients trip PO-token
  checks; the connector uses innertube instead.
- **Boundary:** quota is shared by the API key/project; one study cannot spend the
  operator's whole day.

### GitHub, X, TikTok, Bilibili, Weibo, Zhihu, Xiaohongshu, Discord

- **GitHub:** REST 5,000 requests/hour with a token, Search 30/minute (`official`
  limits). No bypass scenario exists; abuse detection reacts to spam-shaped traffic.
- **X:** prefer the official API for programmatic reads. The separate authorized
  visible-page CDP exception still requires catalog eligibility, Design review,
  human acknowledgement and an approved URL; it is not API authorization.
  Pay-per-use pricing started 2026-02 (`craft`).
- **TikTok / Bilibili / Weibo / Zhihu / Xiaohongshu:** prefer official or authorized
  channels; where no API exists, only authorized visible pages on `cdp: true`
  platforms (Bilibili, Weibo, TikTok) with the budget below. Zhihu and Xiaohongshu
  have no `cdp` grant in the catalog — treat them as manual/export sources.
- **Discord:** membership is not access; only channels the operator can already read,
  with `join-is-not-access` enforced.

## 2. Budget — how hard a run may touch a source

Numbers live in `runtime_policies.platforms`; `collection_policies` may only make
them **stricter**, never looser (`askovo doctor` enforces this). Defaults: 3.0 s
between page actions on one site, 60-minute session, 30-minute cooldown, 70% of the
cell budget, one `goto` per cell, no reloads.

| Platform | Cadence | Session cap | Budget fraction | Source of the number |
|---|---|---|---|---|
| reddit | 3.0 s | 60 min | 70% | default (API-bound, not page-bound) |
| youtube | 3.0 s | 60 min | 70% | default; quota-bound instead |
| github | 3.0 s | 60 min | 70% | default; token/hour bound |
| amazon | 3.0 s | 90 min | 70% | runtime policy |
| kickstarter | 8.0 s | 120 min | 70% | runtime policy (Cloudflare-sensitive) |
| instagram | 10.0 s | 40 min | 60% | runtime policy |
| x | 10.0 s | 45 min | 60% | runtime policy |
| tiktok | 15.0 s | 40 min | 60% | runtime policy |
| bilibili | 5.0 s | 60 min | 70% | runtime policy |
| weibo | 10.0 s | 45 min | 70% | runtime policy |
| discord | 20.0 s | 40 min | 60% | runtime policy |
| zhihu / xiaohongshu | 3.0 s | 60 min | 70% | default; manual/export only |

Invariants that no run may break:

1. **One site, one cadence.** Rotation lowers the frequency one site sees; it never
   raises a platform's own budget.
2. **One `goto` per cell.** Navigate → verify → collect inside one cell; `reload()`
   stays off.
3. **Session time-box.** Logged-in collection stops at the cap; the next segment
   starts after the cooldown, with a human re-login if the session dropped.
4. **Budget headroom.** Spend at most the fraction, not the ceiling; a run that would
   need the last 30% stops and reports.
5. **No cadence escalation after a success.** A fast run is not evidence that faster
   is safe.
6. **Quota is shared.** API keys, tokens and accounts are per-operator; two studies
   do not double the daily ceiling.

### 2.1 Observed limits (craft evidence)

Official docs state ceilings. They do not state where the platform **actually**
starts reacting, and they never state it for page collection. Those numbers exist
only in operators' failure reports. This subsection records them under a stricter
rule than the rest of this reference.

**The rule: craft numbers may only lower a budget, never raise it.**

```
adopted = min( lowest_credible_breakpoint / 3 , lowest_credible_recommendation )
```

and never above the runtime policy. Three reasons, one per term:

- **Divide by 3, not 2.** A reported breakpoint is an *upper* bound — the reporter
  found the wall at that value and never tested below it. Halving it gives a number
  that is safe for one platform in isolation; two concurrent runs at half the
  breakpoint are not safe. A third leaves room for the overlap.
- **Take the lower of breakpoint and recommendation.** Practitioner recommendations
  usually already contain a discount. If theirs is more conservative, use theirs.
- **Never above runtime policy.** A craft number is evidence, not an authorization.

Why not divide by 10: an over-conservative budget gets bypassed in practice, and a
loose rule that is followed beats a strict rule that is worked around.

What makes a report admissible: **a specific number, a date within 12 months, and a
described failure.** Anything missing one of the three stays in `unverified` and
never reaches a breaker. Platform contracts change silently — Bilibili added a
cookie requirement in 2025-11 with no announcement, Instagram revoked a `doc_id`
globally — so a number older than a year is treated as expired regardless of how
good it was.

| Platform | Mechanism | Lowest credible | Adopted | Confidence |
|---|---|---|---|---|
| reddit | OAuth read | 100 QPM / client, 10-min rolling | 30 QPM, headers win | high |
| reddit | write, new/low-karma account | 1 action / 15 min | 1 action / 45 min | high |
| reddit | subreddit gate (50k–500k) | 200–500 combined karma | read-only until 200 karma + 30 d | high |
| reddit | anonymous `.json` | 403 `blocked by network security` | not enabled | high |
| amazon | PA-API | 1 TPS, 8640/day | 0.5 TPS, 4000/day | high |
| amazon | page fetch | ~20 req/min sustained → CAPTCHA | 1 req/min | medium |
| kickstarter | public pages | no hard number; 1–3 s advised | 8 s ±2 s | low |
| instagram | Graph API | 200 calls/user/hour | 60/hour | high |
| instagram | follow / unfollow | 15–20/hour (new) | 5/hour, 10/day | medium |
| instagram | like | 20/hour | 6/hour | medium |
| youtube | Data API | 10,000 units/day; search 100 units | 3,000 units/day; 30 searches | high |
| x | read endpoints | endpoint caps, 15-min + 24-h windows | 70% of documented | high |
| tiktok | page fetch | unquantified; soft-fail only | 15 s, 60 pages/session | medium |
| bilibili | API | frequency-dependent 412 / `-509` | 5 s; stop 30 min on `-509` | medium |
| discord | REST | 50 req/s global, per-route buckets | 10 req/s, read the headers | high |
| github | REST secondary | 900 points/min, 403 not 429 | 300 points/min | high |
| weibo | page fetch | 200 requests without sleep → temp IP limit | 60 requests, then 10-min sleep | medium |

Infrastructure-level findings that no single number captures:

1. **A failure on the very first request is identity, not rate.** Amazon, YouTube
   and Instagram all independently produce this. The action is stop-for-the-day, not
   slow down — throttling does nothing against a reputation decision, and retrying
   deepens the mark.
2. **HTTP 200 is not success.** TikTok returns a login wall, Weibo returns a
   "访问过于频繁" page, Reddit puts the limit in `json.errors`, GitHub uses 403 for
   rate limiting. A collector that classifies by status code silently produces empty
   data and records it as coverage.
3. **Restarting the process resets the local quota assumption, not the platform's.**
   Instaloader states this in its own troubleshooting guide: the rate controller
   assumes a full budget at startup. On a throttled platform, restarting is an
   escalation.
4. **Retrying immediately after a 429 moves the window.** Consecutive probes push
   the reset further out; the reset is never reached. Wait a full window, not until
   the timestamp.
5. **Read and write are separate budgets**, as are account, client and IP quotas.
   Spending less on reads never buys an extra write, and a second API key is a
   second identity, not a second allowance.

Each of these is stored as a platform-level `observed[]` entry, not as prose:
`id`, `claim`, `threshold`, `window_seconds`, `suggested_cadence_seconds`,
`confidence` (`high`/`medium`/`low`) and dated `source_urls`. The engine enforces
direction, not magnitude: a suggestion slower than the budget is advisory, a
suggestion faster than the budget is a validation error, and a `low` entry never
reaches an automatic breaker.

## 3. Signals — what the platform tells you before it blocks you

Read a signal as: **detect → classify → act**. `block` stops the channel, `throttle`
lowers rate and extends cooldown, `watch` records and continues.

| Signal | Level | Detect | Action |
|---|---|---|---|
| `http-403-unauthenticated` | block | 403 with no OAuth token / expired token on an API call | Stop; re-check app registration; do not retry with a browser |
| `http-429-rate-limit` | throttle | 429 plus `x-ratelimit-remaining: 0` or `retry-after` | Honor the reset, double the cadence for the rest of the session |
| `challenge-page` | block | Interstitial, CAPTCHA, "verify you are human", Cloudflare 1020 | Passive wait only; then human; otherwise end the run |
| `login-wall` | block | Redirect to login or "session expired" | Human re-login; never enter credentials or export cookies |
| `blank-render` | block | 200 with empty title and empty body after render | Unsupported stack; switch source, do not retry the same URL |
| `partial-render` | watch | Expected item count collapses between two windows | Record `coverage_gap`; do not extrapolate |
| `content-removed` | watch | `[removed]`, `[deleted]`, tombstone markers | Count as missing, never as absence of the pain |
| `quota-exhausted` | block | API quota error / `quotaExceeded` | Stop until the documented reset; no second key to continue |
| `redirect-to-consent` | watch | Consent/age gate between request and content | Manual acceptance by the operator; not automated |
| `shadow-removal` | watch | Own test post invisible in a logged-out view | Stop that account's use for 14 days; no replacement account |

Platform-specific signals worth naming:

- **Reddit:** 403 on `/api/*` without a token is the shutdown preview, not a script
  bug. A commercial-use clause hit is a legal stop, not a rate problem.
- **Amazon:** PA-API `InvalidParameterValue`/410 after 2026-05-15 means the endpoint
  is gone; there is no retry, only the dataset or Creators route.
- **Kickstarter:** a Cloudflare 403 with `cf-mitigated: challenge` is the challenge
  signal; a plain 403 on GraphQL is the endpoint refusing non-browser clients.
- **Instagram:** Graph API `(#4) Application request limit reached` is a hard
  throttle; `(#10)` is a permission error, not a rate error.
- **YouTube:** `quotaExceeded` is per-project and resets at midnight Pacific;
  `commentsDisabled` is a content state, not a failure.

## 4. Circuit breakers — when the run must end

Global rules, applied by `cdp_strategy.SessionGuard` and the collectors:

1. **Any timeout is a breaker.** Do not diagnose, screenshot or retry; stop touching
   the platform for the timeout cooldown (15 min). A torn input stream is itself an
   automation signature.
2. **Three strikes per class.** Three consecutive failures of the same class
   (timeout, challenge, blank render) end the run for that platform, not just the
   cell.
3. **Two platforms, one identity.** A challenge on one platform pauses the whole
   browser session; do not "try another site" with the same session.
4. **Session drop = human.** A logged-out state ends collection; no automatic
   re-login, no cookie replay.
5. **Budget ceiling = stop.** Hitting the session cap or the budget fraction ends
   the run even if the last page looked healthy.
6. **Stop rules are data.** Each platform's `stop_rules` travels into the runtime
   policy and session journal. Numeric session/cadence/headroom rules are enforced
   mechanically; route-specific textual rules remain operator and audit constraints,
   never an excuse to claim a check that has no executable detector.

## 5. Output criteria — when a run counts as usable

A run produces evidence only when all of these hold; otherwise it produces a
recorded gap.

1. **Provenance:** every record carries source URL/id, channel, collection time and
   the access basis (API, export, dataset, authorized page).
2. **Field preservation:** raw envelope + normalized record are both kept; a
   normalized schema that drops a field loses the field, it does not silently
   rename it.
3. **Date honesty:** relative timestamps are marked `date_precision=approximate`;
   a missing date is null, never "today".
4. **Dedupe:** stable id first, content hash second; cross-window duplicates are
   counted, not appended.
5. **Coverage statement:** window, query, platform, and the known gap (removed
   content, unrendered replies, quota-truncated tail) are written next to the data.
6. **Sample sanity:** the marginal-new-theme curve is flat before scaling; a single
   window or a single subreddit/creator is a pilot, not a sample.
7. **No truth claim:** counts describe the collected corpus, not the population.
   Platform bias is recorded with the records.

## 6. Priority dossiers

### Reddit

- `official` (2026-07-20 terms): §2.4 no ML/AI training on User Content; §2.8 no
  identity/UA misrepresentation; §2.9 platform-set limits; §3.1 separate agreement
  for commercial/over-limit research; §3.2 no circumvention.
- `craft` (2026-09-30 timeline): 2026-10-31 new app requests close; 2027-01-12
  unregistered apps cut; 2027-03 public API closed; RSS retired 2026-11-13.
- **Decision:** keep the OAuth adapter while it lives; migrate historical windows to
  Arctic Shift before 2027-01; treat the study's own authorized export as the only
  durable fresh-data path.

### Amazon

- `official`: PA-API 5.0 deprecated 2026-04-30, shut 2026-05-15; ToS forbids scraping.
- `craft`: Creators API OAuth, 30-day sales activity, ~1 req/s start.
- **Decision:** review text from the Reviews 2023 dataset only; product metadata via
  seller/associate credentials owned by the operator, never collected by Askovo.

### Kickstarter

- `verified` (field): Cloudflare 403, JS-rendered comments, GraphQL 403.
- **Decision:** CDP visible page only, 8 s cadence, 120-minute session, passive
  challenge wait; deep "load previous replies" stays a recorded gap.

### Instagram

- `official`: Basic Display deprecated 2024-12-04. `craft`: Graph API ~200 calls per
  user per hour; 2026-11-20 commercial-terms pause.
- **Decision:** authorized export or eligible research API first; CDP only for a
  page the operator can already read, 10 s cadence, 40-minute session, 60% budget.

### YouTube

- `official`: 10,000 units/day, `search` 100 units/call.
- **Decision:** API + innertube first; authorized visible-page CDP is available only
  through the shared exception. Comments via continuation tokens where supported;
  collapsed replies and unknown relative dates stay recorded gaps; transcripts only
  with rights.

## 7. Review schedule

- `generated_at`: 2026-11-21. `review_by`: 2027-02-21.
- Highest-priority watch item: **Reddit public API closure (2027-03)** — the adapter
  must be re-pointed at the archive/export path before 2027-01-12.
- Next in line: Amazon Creators API quota terms, Instagram commercial-terms pause,
  Kickstarter 2026 ToS diff.

Unverified items carried forward: Kickstarter 2026 Terms of Use change; Zhihu 2026
community规范; Douyin convention text; the WeChat public-platform rule page behind
its login wall; Instagram per-endpoint quotas; Hacker News guide page unreachable
this round; the original 2026-09-30 Reddit announcement post (only secondary
transcriptions were readable).

## 8. Deliberately out of scope

Askovo does not implement, document as a recipe, or accept as a study setting:

- CAPTCHA solving or challenge bypass;
- browser-fingerprint spoofing or anti-detection patching;
- proxy pools or IP rotation to evade limits;
- sock-puppet accounts, account warming or ban-evasion re-registration;
- "humanizing" automation to defeat detection.

These are not engineering gaps to close later; they are the boundary that makes the
collected data defensible.

# Multi-Platform Collection Playbook (channel selection, CDP operations, crawler engineering)

Field-verified methods collected from the golf-device research campaign
(2026-11, ~110k records across Reddit / YouTube / Kickstarter / Discord / X /
Instagram in one day). This playbook answers three questions a study hits the
moment plain HTTP collectors stop working: **which channel fits this platform**,
**how to drive a real browser without tripping anti-automation**, and **which
engineering rules keep a multi-hour collection honest and resumable**.

Governance first: nothing here overrides the platform catalog. CDP routes exist
only for platforms whose catalog entry sets `cdp: true`; challenges are never
actively bypassed; login sessions are user-operated only.

## 1. Channel decision tree — probe, then commit

For each platform, try channels top-down and stop at the first that works. The
field matrix below records where each probe landed in Nov 2026.

```
1. No-login public API / archive        (Reddit via Arctic Shift, YouTube via innertube)
2. Real browser over CDP, no login      (Kickstarter comments, vertical forums behind Cloudflare)
3. Real browser over CDP, user session  (Discord, X, TikTok, Instagram)
4. Page copy-paste                      (fallback when DOM extraction breaks)
5. Screenshot + OCR                     (last resort when copy is disabled)
```

Lessons that shaped this order:

- **Probing is cheap, assuming is expensive.** yt-dlp's default clients were
  blocked by PO-token detection ("page needs to be reloaded") — the innertube
  `search`/`next` endpoints still worked login-free, so the collector stayed on
  tier 1 instead of dropping to a browser.
- **A 403 on plain HTTP does not mean the data is unreachable.** Kickstarter,
  GolfWRX and MyGolfSpy all reject script fetches from behind Cloudflare but
  render fully in a real browser; the CDP tier is exactly for this gap.
- **Copy-paste and OCR are fallbacks, not defaults.** Structured DOM
  extraction is cleaner than pasted text and cheaper than OCR; the field runs
  needed them zero times once CDP extraction worked.

### Field matrix (Nov 2026)

| Platform | Channel that worked | Login | Anti-bot observed | Status | Output shape |
| --- | --- | --- | --- | --- | --- |
| Reddit | Arctic Shift archive API, windowed backfill (`collect_arctic_windows.py`) | none | 422 "slow down", 429 with reset headers | verified at scale (≈3.9k windows) | corpus envelope JSONL |
| YouTube | innertube search/next/continuation (`collect_youtube_innertube.py`) | none | PO-token blocks yt-dlp defaults; comment payloads moved to `commentEntityPayload` | verified (2.7k comments) | corpus envelope JSONL, `date_precision=approximate` |
| Kickstarter | CDP visible page, "load more" expansion (`collect_cdp_kickstarter.py`) | none | Cloudflare on direct fetch; passive auto-clear observed | verified (4 campaigns, ≈2k comments) | raw JSON `{project, n, comments}` |
| Discord | CDP user session, real wheel events (`collect_cdp_discord.py`) | user logs in by hand | storage sandbox kills internal APIs; anti-automation drops sessions | verified (16 channels + forums, ≈4k msgs) | raw JSON `{guild, server, channels, forums}` |
| X | CDP user session, live search `since:/until:` quarterly windows | user logs in by hand | infinite scroll stalls on search pages (`dom_cua` wheel helps); reply density low | partially verified (165 mentions, 7 windows) | raw JSON `{queries, windows, replies}` |
| Instagram | CDP user session, post modal + scroll-loaded comments | user logs in by hand | comments lazy-load on scroll | partially verified (first posts) | raw JSON `{profile, posts}` |
| TikTok | CDP user session | user logs in by hand | — | login verified, collection pending | — |
| Vertical forums (GolfWRX/MyGolfSpy) | CDP visible page | none | Cloudflare 403 on scripts | channel verified, not yet run | — |

## 2. CDP operation patterns

### Login collaboration (agent opens, human logs in)

1. Agent opens the login pages in the CDP browser, one tab per platform.
2. The human completes login (passwords, 2FA) — the agent never types
   credentials and never reads stored ones.
3. Agent verifies session state per platform before collecting (URL landed,
   logged-in marker visible), and re-verifies after any interruption.
4. Expect remote-login checks ("was this you?") — the human confirms them.
5. Do not drive the browser while the human is typing; wait for an explicit
   "logged in" before switching tabs or navigating. A URL that has not
   refreshed is not evidence either way — verify the logged-in marker.

### Challenge pages: wait passively or stop

A Cloudflare interstitial in a real browser often clears by itself within
seconds. The correct behavior is **poll until it clears, then proceed**; if it
demands interaction, stop and let the human finish it, then rerun. Never
solve, spoof, or proxy around a challenge. (`collect_cdp_kickstarter.py`
implements exactly this with `--challenge-wait`.)

### Lazy loading: real input events, not property writes

- **Discord history only loads on real wheel events.** Setting
  `scrollTop = 0` programmatically produces no event stream — the list goes
  stale. Dispatch `Input.dispatchMouseEvent {type: "mouseWheel", deltaY:
  -N}` instead (see `wheel_up` in `collect_cdp_discord.py`).
- **"Load more" buttons need bounded click loops.** Click in small bursts,
  re-extract after each burst, stop when the row count stops growing or the
  button disappears; cap total clicks.
- **Move the mouse before scrolling.** A short `mouseMoved` before wheel
  events keeps the input stream human-shaped.

### Anti-automation post-mortem (Discord, four drops in one day)

Four session drops on 2026-11-17 produced a sharper signal than the old
"rapid hops + steady scrolling" story. Three drops were preceded within minutes
by a timed-out or aborted operation (a `cuaScroll` timeout, a cell abort
mid-input, a navigation timeout) and then **continued driving**. Control
periods of equally fast but timeout-free navigation (a full ~50-cell forum
crawl) never dropped. A fourth drop arrived ~40 minutes after the last
operation with zero browser contact in between: enforcement can be delayed, and
an hours-idle session in an embedded webview can also fail token rotation on
its own.

**Corrected protocol (a circuit breaker, not a slower metronome):**

1. **Treat any timeout on Discord as a stop signal.** Leave the platform alone
   for >= 15 minutes: no diagnostics, no snapshots, no retries. A timeout tears
   an input event stream mid-dispatch, and that signature reads as automation.
   Fast navigation alone did not drop the session; timeout-then-continue did,
   every time.
2. **One goto per automation cell**, cell budget <= 60% of the cap, no
   `reload()`. Navigate → verify → collect stays in one cell.
3. **Never mix invite joins and channel crawling in one session stretch.** One
   run, one mode; log out and start a fresh stretch for the other.
4. **Time-box the session**: fresh login, collect within 30–40 minutes, then log
   out deliberately. Never leave a Discord session idle-open for hours as a
   standing channel.
5. Persist after every round regardless, and never let a cell timeout be the
   thing that persists for you — an un-persisted round is a lost round.

These numbers are not prose: they are `runtime_policies.discord` in the
field-notes registry, enforced by `connectors/cdp_strategy.py` (`SessionGuard`).
The generic rule for every CDP platform: any timeout opens the circuit for the
policy's cooldown, a challenge page is a passive wait or a human stop, and a
blank 200 is an unsupported stack. The collectors persist the best harvest and
exit 2 instead of retrying.

### Parallel lanes: overlap waits, never per-site rate

Collection time is mostly waiting for pages to render, so the throughput lever
is **overlapping waits, not raising per-site frequency**. Three lanes ran at
once in the field:

- **Lane A — background processes** for no-login channels (Arctic Shift
  windows, YouTube innertube waves). Archives are happy to run unattended;
  start them, then forget them.
- **Lane B + C — two tabs in one browser** for logged-in sites (Instagram and
  GolfWRX in the field run). A CDP `goto` resolves once navigation commits;
  the page keeps rendering in its own renderer process afterwards. Fire both
  navigations without awaiting the first, then harvest while the other page
  finishes painting.

The invariant that makes this safe: **each site only ever sees its own tab's
sequential requests**, so per-site cadence is unchanged — the waits of
different sites simply overlap. Two tabs on the *same* site would double its
rate and is not a lane.

Per-cell protocol (one cell = two rounds, ~55 s in the field run):

1. Pick the next target per lane from its queue (unharvested posts/threads).
2. Fire both `goto` calls concurrently; await both renders.
3. Harvest alternately — extract lane B, extract lane C, each with its own
   extractor and its own persisted store.
4. Persist both stores per cell; a cell that times out must not tear the input
   event stream or lose the other lane's harvest.

Field result: one cell = 2 Instagram posts (28 comments) + 2 GolfWRX threads
(87 posts) in 55 s — about double the single-tab rate with no extra
per-site risk. Keep tab bindings by stable tab id (URL patterns rot); one tab
per site per run.

A browser lane is driven by an agent turn, not a daemon: it stops when the turn
ends, while background archive jobs keep running. Do not compare rates across
lanes, or plan a deadline, as if the browser lane were continuous.

### Multi-platform rotation: stay under every site's radar

The rotation strategy is a *frequency* argument, not a parallelism trick: a site
can only measure its own request stream, so alternating between sites lowers
every site's observed cadence while total throughput stays flat (or rises, when
render waits overlap).

Rules that make it safe to automate:

1. **Per-site minimum interval** — never hit the same site again before its
   cadence elapses; spend the wait on a different site.
2. **One tab per site** — two tabs on one host double that host's rate; that is
   risk-control pressure, not parallelism (`run_lanes` rejects duplicate sites).
3. **One writer per provider** — a duplicate archive client multiplies 422
   storms and starves both; hand the quota to the higher-yield lane.
4. **Classified cooldown** — 429/403 wait for the reset header, 422 backs off,
   permanent statuses stop the platform; rotate while it cools.
5. **Session health** — a dropped login session is a human re-login, never an
   agent re-auth; cooldown the platform (default 30 min) and keep rotating.
6. **Daily quota + resume** — a capped platform returns tomorrow; the rotation
   state is JSON so a restarted run does not re-hit hot platforms.

`connectors/rotation.py` (`RotationScheduler`) implements the rules; the
machine-readable strategy table — with invariants and verification status — is
in [platform-field-notes.md](platform-field-notes.md#cross-platform-strategies)
(`askovo platforms "<need>" --strategies`).

### Runtime policy: the invariants compiled into code

The registry also carries `runtime_policies`: defaults plus per-platform
budgets (cadence, session time-box, timeout/session cooldown, max goto per
cell, budget headroom, exclusive modes) and `guards`, which bind every
runtime-enforced strategy to the helper that enforces it. `connectors/
cdp_strategy.py` turns those numbers into `RuntimePolicy` + `SessionGuard`, so
capture, collect and both CDP collectors apply one policy instead of each
re-deriving it. `askovo platforms "<need>" --policies` renders the table and
`askovo doctor`'s `cdp-runtime-policies` check fails when the registry and the
runtime drift apart. Strategies marked `enforcement: operator` (windowed
search, batch relay, multilingual routes, channel pivot, deduped goal
counting) are planning decisions a loop cannot enforce; the rest are runtime
guards.

### Platform quirks worth remembering

- **X search**: `since:/until:` operators make Reddit-style time-window
  sampling work on X (quarterly windows back to product launch). Infinite
  scroll on search pages stalls; the `dom_cua`-style real wheel keeps it
  moving. Reply threads cost a page load each and yield ~1.6 replies/post —
  treat them as a background task, not the main course.
- **Instagram comments**: lazy-loaded; the comment row is an unclassed `DIV`
  five levels above the `time` element (handle | text | time). Crawl up the
  ancestor chain from `time` — class selectors will not find it.
- **Instagram captions break on reels and modals**: the caption/author
  selectors that work on a post page return empty on a reel. Fall back to the
  `og:description` meta tag — it carries `"<handle> on Instagram: <caption>"`,
  and the trailing `"<n> likes"` fragment has to be stripped from the caption.
- **Instagram keyword grids are locale-dependent**: the same query returns
  dozens of posts in Korean but only a handful in English/Japanese. Run one
  queue per (term × locale), do not assume paraphrase parity across languages,
  and switch to hashtag/tag URLs when a keyword grid comes back thin.
- **Discord forum channels** (feature-requests / bug-reports): thread cards
  already carry title + author + body (in `div[class*="messageContent"]`), so
  the card list is the corpus — no need to open threads. Exclude the
  `#channels` sidebar when selecting card headers (it uses `h3` too).
- **Discord server discovery**: official invite links rot. Grep your own
  corpus (`discord.gg/`) for codes users posted, rank by frequency, verify the
  surrounding context before joining — the official community is sometimes a
  Facebook group, not Discord, and the valuable server is the one users
  recommend to each other.
- **Joining a server is not reading it**: a large Discord server can accept
  the invite and show its channel list while the history pane stays gated
  behind membership verification. Record `membership_gated` (server id, member
  count, gate type) as a coverage gap; never attempt verification roles, bots,
  impersonation or gate workarounds. SGT (40,967 members) behaved exactly like
  this for a fresh member.
- **Name the channels before scanning them**: blind channel-by-channel scans
  burn cells on rules/welcome/empty rooms. Snapshot the sidebar once, rank by
  real name (help/support/competitor brands), then target the high-value
  channels. Empty rooms are a finding, not a failed extraction.
- **Instagram's profile page is the slow surface; keyword search is the
  channel**: `/explore/search/keyword/?q=` returns 3–8 posts per query and keeps
  producing, while profile cells timed out at two posts. Build queues per term,
  process one or two posts per cell with per-post persistence, and treat the
  profile as discovery only. On Instagram the risk is account-level (24–72 h
  action block), so the conservative cadence is the price, not a tuning
  parameter.
- **Time-window sampling is platform-specific**: X supports `since:/until:`;
  Discord exposes channel history by scrolling; YouTube innertube has no
  native time window (layer queries by topic and keep approximate timestamps);
  Instagram has no public time search (per-post only). Do not promise a
  Reddit-style backfill on every platform.
- **A handle match is not the official community**: `@XbotGo` was a Japanese
  sub-account (151 followers) while the real conversation lived in search
  mentions. Check the account's market, followers and post history before
  treating its replies as the brand's customer voice.
- **Word choice beats locale labels**: a generic Japanese term returned ~3
  posts while `ゴルフスイング` returned 42 in the same language. Retry a better
  term before recording a locale gap or blaming the grid.
- **App Store RSS is retired**: the customer-reviews RSS/XML endpoint returns
  zero entries. Do not plan it; the remaining route is the browser-visible
  store page's in-page comments API, which must be verified before promising
  volume.
- **vB5 forums mix sidebar cross-links into a section list**: collect thread
  links from the main content container, dedupe by canonical href, and tag the
  section id — sidebar "latest posts" belong to other sections.
- **Tab bindings rot too**: a `tabs.find()` on URL patterns breaks after
  redirects or reloads. Re-list tabs, re-bind by stable tab id, and keep
  navigate→verify→collect in one cell so a wrong page can't silently produce
  zero rows.
- **Silent extractor failures**: a thrown grab script can look like an empty
  page. When a selector returns zero, dump one card's raw HTML and isolate the
  script error before concluding the page is empty.

## 3. Crawler engineering rules

| Rule | Field origin |
| --- | --- |
| Classified backoff: 429/403 wait for `X-RateLimit-Reset`; 422 ("slow down") retries with exponential wait; budget-bound, then stop the window honestly | Arctic Shift runs |
| Resume via state file + rebuilding the `seen` set from the output file; stream-append, never buffer to the end | 10-hour multi-window runs |
| Bounded collection everywhere: per-window caps, global record caps, max clicks/scroll rounds | all connectors |
| Empty-window honesty: an archive window with zero rows is usually a real gap (community too small that era) — verify one window interactively before burning a plan | r/GolfEquipment 2021–23 |
| Relative timestamps ("10 months ago") → approximate dates, always marked `date_precision=approximate` | YouTube innertube |
| Two-layer output: platform-faithful raw JSON first, corpus envelope via `clean_screen_corpus.py` second | Kickstarter/Discord runs |
| Persist after every round — an un-persisted round is a lost round | Discord session drop |
| One writer per provider, state file **and derived output**: before restarting a collector or a cleaning job, confirm the old process is actually dead (`ps` + `kill`) and use one managed background job (no nohup residue); duplicate clients double the request rate, duplicate cleaners silently overwrite the better output | golf-main restart (two live processes); clean4 still writing when clean5 started |
| Overlap waits, not rates: no-login archives run in background processes while two logged-in tabs on different sites render in parallel; per-site cadence stays flat | dual-tab pipeline, ≈55 s/cell |
| Rotate platforms to keep per-platform cadence low without losing throughput | post-rate-limit protocol |
| Run no-login channels (APIs, archives) in background processes; the logged-in browser is the scarce resource — spend it on what needs it | YouTube wave 3 alongside browser work |
| One slow page per cell (X search, IG profile); two posts per cell only when each post persists independently; rotate a timed-out cell instead of retrying it in place | X/IG timeout loops |
| A page-level timeout is not automatically a challenge page: retry one post once, then skip it and rotate; only a challenge/data-loss signature justifies a platform stop | GolfWRX single-topic timeout |
| A 0% field rate is a pipeline bug until proven otherwise: compare one golden raw record with its normalized counterpart before concluding the source lacks the field | Amazon dates 0/16,226; author_hash dropped by clean_merge |
| Convert by named field, never by positional order; assert identity/time/url non-empty rates after every schema change and re-run the analysis, never patch the derived result | author_hash positional mismatch |
| Reconcile raw → deduped → cleaned → classified totals and bucket shares; a source family that contributes 0 to every bucket is a coverage gap, not zero | Rapsodo/FlightScope 5,863 records outside every goal bucket |
| Verify a background launch with `ps` and absolute paths: `cmd & tail …` backgrounds the `cd` too, so the log path and the job state can lie | three repeated `&` precedence mistakes |
| Amazon review timestamps in the McAuley dump are Unix milliseconds; parse numerically, never slice a year out of the string | Amazon date repair |

### Data pipeline hygiene

The campaign's worst data bugs were not extraction failures; they were silent
normalization losses. Three rules catch almost all of them:

1. **Preserve the join keys.** A unified schema must keep identity, time and
   URL fields. `author_hash` was dropped by a positional argument mismatch and
   the persona analysis collapsed while row counts looked healthy.
2. **Reconcile the buckets.** Count raw rows, deduped rows, cleaned rows and
   classified rows per file. Rapsodo/FlightScope (5,863 records) fell outside
   every goal bucket; the "gap" was partly a classifier bug, not missing data.
3. **Keep nominal, deduped and cleaned counts visible together.** Acceptance
   uses the cleaned, classified total; the nominal count is a running estimate,
   and an unclassified family is a gap.

## 4. Where the code lives

- `scripts/connectors/collect_arctic_windows.py` — windowed archive backfill
- `scripts/connectors/collect_youtube_innertube.py` — login-free YouTube comments
- `scripts/connectors/collect_cdp_kickstarter.py` — CDP visible pages, no login
- `scripts/connectors/collect_cdp_discord.py` — CDP user session, real wheel events
- `scripts/connectors/README.md` §4b — CDP collector usage, boundaries, envelope conversion
- X / Instagram / TikTok methods above are documented here only; connectors
  land when their extraction paths are verified end-to-end.
- The parallel-lane pattern (background archives + dual-tab pipeline) is an
  operating method, not a script: it composes whatever collectors a study
  already has, and each lane keeps its own extractor and its own persisted
  store. A generic `cdp_parallel_pipeline.py` only earns its place once two
  extractors can be driven from one config without forking them.
- The reusable mechanisms behind these methods are imported, not re-derived:
  `scripts/connectors/common.py` (classified backoff, single-writer state lock,
  relative-time parsing, atomic JSON persist), `scripts/connectors/
  cdp_runtime.py` (passive challenge wait, real wheel events, tab re-binding,
  bounded load-more, parallel lanes) and `scripts/connectors/cdp_strategy.py`
  (per-platform runtime policy, page triage, session guard). The engine's
  `CDPClient` adds a per-call timeout and refuses to read on after a torn
  stream (`CDPTimeout` / `CDPTransportError`), so a timeout cannot silently
  become a retry. Restricted pages, the same methods in machine-readable form
  and the verification legend: see [platform-field-notes.md](platform-field-notes.md)
  and `askovo platforms "<need>" --field-notes --policies`.

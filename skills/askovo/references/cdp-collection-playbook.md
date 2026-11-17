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

### Anti-automation post-mortem (Discord, twice observed)

Two session drops shared the same signature: 6–10 rapid channel jumps
(5–15 s apart), a cell timeout tearing an input event stream mid-dispatch,
then 30–40 minutes of metronome-steady scrolling with no organic signals.
Discord's detection keys on exactly that: many channels in a short window,
websocket behaviour with no typing/movement, abnormal disconnects.

**Corrected protocol (baked into the connectors):**

1. Leave ~30% headroom on every cell budget — never let a timeout abort
   mid-event; prefer collecting less.
2. 20–40 s between channel navigations; mouse move before scrolling; one page
   per run.
3. Rotate platforms instead of hammering one: a round per platform, then
   switch. Per-platform cadence drops, total throughput does not.
4. No `reload()`, no rapid hops. Persist after every round regardless.

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
| One writer per state file: before restarting a collector, confirm the old process is actually dead (`ps` + `kill`); two processes on one state file double the request rate, corrupt resume state and starve each other | golf-main restart (two live processes from one morning) |
| Overlap waits, not rates: no-login archives run in background processes while two logged-in tabs on different sites render in parallel; per-site cadence stays flat | dual-tab pipeline, ≈55 s/cell |
| Rotate platforms to keep per-platform cadence low without losing throughput | post-rate-limit protocol |
| Run no-login channels (APIs, archives) in background processes; the logged-in browser is the scarce resource — spend it on what needs it | YouTube wave 3 alongside browser work |

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

# Reddit research

Use this reference when Reddit is in the source plan. Read [social-media-source-adapters.md](social-media-source-adapters.md), [open-source-connectors.md](open-source-connectors.md), and [connector-contract.md](connector-contract.md) first.

## Approved OSS route

The default reviewed connector is [PRAW](https://github.com/praw-dev/praw), a BSD-2-Clause Python wrapper for Reddit's Data API. The registry pins revision `855f48e075935a052b1d71243e60e41cbc260ced`.

PRAW is a client, not permission. The study still needs approved API credentials, an identifiable user agent, permitted purpose and scale, and a retention/deletion plan. Reddit's [Data API Terms](https://redditinc.com/policies/data-api-terms) state that commercial use, research beyond permitted limits, or unapproved use may require a separate agreement. Reddit's current User Agreement also prohibits scraping without prior written consent except permitted crawling under `robots.txt`.

Do not replace unavailable API access with page scraping, browser automation, rotating accounts, or a generic GitHub scraper.

## 2026 access transition

Reddit's 2026 announcement on the [future of the public Data API](https://www.reddit.com/r/redditdev/comments/1vgbm9c/our_plans_for_the_future_of_reddits_public_data/) changed the access picture while leaving PRAW usable for studies that already hold approved access:

- Existing Data API apps must be registered by **2026-09-30** to remain in good standing. Confirm the study's app registration before any collection run.
- New self-service API access is closed under the Responsible Builder Policy; new access requires an approval request, so a study without existing approved credentials cannot assume Reddit is available — treat it as an access gap in the source plan, not a reason to switch tools.
- The stated long-term direction is migration to the Reddit Developer Platform (Devvit), with a [migration guide](https://developers.reddit.com/docs/guides/migrate/public-api) published and migration-program participants committing by 2026-12-31.

The registry pins `recheck_by: 2026-09-30` for this connector. Do not read "PRAW still works today" as "anyone can obtain access today", and do not let the transition push the study toward a blocked non-API route.

## Adapter config

```json
{
  "reddit": {
    "enabled": true,
    "researcher_role": "external_third_party",
    "connector_id": "reddit-praw",
    "connector_revision": "855f48e075935a052b1d71243e60e41cbc260ced",
    "connector_license": "BSD-2-Clause",
    "collection_mode": "historical_search",
    "access_basis": "official_api",
    "policy_status": "approved_for_study",
    "terms_reviewed_at": "YYYY-MM-DD",
    "data_rights_reviewed_at": "YYYY-MM-DD",
    "data_rights_basis": "Approved use, retention, and deletion basis",
    "retention_rule": "Exact rule",
    "min_unique_subreddits": 3,
    "min_unique_threads": 20,
    "max_subreddit_share": 0.5,
    "max_thread_share": 0.15,
    "require_original_source": true,
    "treat_ai_summaries_as_discovery_only": true
  }
}
```

The thresholds are study parameters, not universal standards.

## Design routes around evidence roles

Use separate routes for:

1. direct product/category response;
2. open task and problem language without product terms;
3. workarounds and substitutes;
4. rejection, return, churn, and “good enough” alternatives;
5. solution requests and conditional acceptance;
6. price or purchase language;
7. post-purchase setup, reliability, maintenance, and retained use;
8. control cases where the problem or proposed product is absent.

Each route records:

```text
route_id × corpus_role × subreddit × query × sort × time_filter × post/comment × target × cap
```

Use multiple sorts deliberately. `new` is closer to a recent baseline; `relevance` reflects search ranking; `top` overweights engagement. Keep each as a separate route.

## Preserve the hierarchy

The independence unit is usually the thread or unique author-thread combination, not each comment. A long thread can contain useful disagreement, but fifty comments under one post are not fifty independent market confirmations.

Required Reddit provenance in every askovo evidence record:

```text
collection_run_id
connector_id
connector_revision
source_platform
source_channel
source_url
thread_id
reddit_item_id
source_content_type
source_query
source_sort
source_time_filter
created_at
collected_at
content_status
```

Store comment parent ID, route IDs, sampling frame, score, edited/deleted state, and language when available. Avoid raw usernames unless the decision genuinely requires them and the study has a lawful basis.

## Collection manifest

For each PRAW run, record the query route, OAuth application identity category without secrets, requested/reached/written counts, pagination state, observed rate limits, deleted or bodyless items, start/end timestamps, and stop reason. Use synthetic fixtures for connector tests; do not commit Reddit content to the repository.

Stop on authentication failure, 403, 429, platform challenge, or unclear permission. PRAW's rate handling does not authorize unlimited collection.

## Pilot and concentration checks

Before scaling, report:

- records reached, written, and claim eligible;
- unique subreddits and threads;
- dominant subreddit and thread share;
- post/comment and historical/live distribution;
- missing, deleted, or truncated content;
- normalized duplicates and crossposts;
- E2, E3, E4+/E4−, E5, and counter-evidence yield;
- time/event concentration and new-theme yield.

Scale only when the route supplies the evidence role assigned to it. A large complaint community with no rejection, acceptance, commercial, or post-purchase evidence remains a partial source.

## Historical and live frames

Historical search and prospective monitoring answer different questions. Keep `sampling_frame=reddit_historical_search` and `sampling_frame=reddit_live_monitoring` separate. An alert-like prospective feed cannot be presented as complete history.

## Claim boundary

- Upvotes, awards, comment count, and subreddit size are E0 attention/context.
- Explicit problem/task language may support E1.
- A workaround or failed substitute may support E2.
- Direct acceptance of the studied solution may support E3.
- Direct price/purchase language may support E4+; rejection/cancellation may support E4−.
- Claimed ownership or continued use requires careful context and independent validation before E5 is relied upon.

Repeated Reddit patterns can justify `hypothesis` or `needs-validation`. A `validated` judgment still needs linked problem, solution, commercial/behavioral, and counter-evidence for the same role, scene, and task.


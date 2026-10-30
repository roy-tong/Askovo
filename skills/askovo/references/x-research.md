# X research

Use this reference when X is in the source plan. Read [social-media-source-adapters.md](social-media-source-adapters.md), [open-source-connectors.md](open-source-connectors.md), and [connector-contract.md](connector-contract.md) first.

## Approved OSS route

The reviewed connector is [Tweepy](https://github.com/tweepy/tweepy), an MIT-licensed Python client for the official X API. The registry pins revision `c1978d643ecce491929084e4290b35f57e4921ad`.

The X API tier determines available search window, endpoints, quota, and redistribution limits. [X's current developer guidelines](https://docs.x.com/developer-guidelines) require official API access and prohibit scraping and browser automation. They also impose deletion, redistribution, privacy, sensitive-use, and model-training restrictions.

askovo therefore blocks:

- [snscrape](https://github.com/JustAnotherArchivist/snscrape), a non-API scraper whose X path is also stale;
- [twikit](https://github.com/d60/twikit), which uses X's internal API without an official API key.

Their code licenses do not make their access mechanisms acceptable.

## Adapter config

```json
{
  "x": {
    "enabled": true,
    "researcher_role": "external_third_party",
    "connector_id": "x-tweepy",
    "connector_revision": "c1978d643ecce491929084e4290b35f57e4921ad",
    "connector_license": "MIT",
    "collection_mode": "historical_search",
    "access_basis": "official_api",
    "policy_status": "approved_for_study",
    "terms_reviewed_at": "YYYY-MM-DD",
    "data_rights_reviewed_at": "YYYY-MM-DD",
    "data_rights_basis": "Approved use, retention, deletion, and redistribution basis",
    "retention_rule": "Exact rule",
    "min_unique_conversations": 20,
    "min_unique_days": 7,
    "max_conversation_share": 0.15,
    "max_repost_share": 0.25,
    "max_single_day_share": 0.35,
    "require_original_source": true,
    "treat_ai_summaries_as_discovery_only": true
  }
}
```

## Route design

Separate routes for problem/consequence, workaround/substitute, rejection/churn, solution request/acceptance, commercial language, post-purchase behavior, and controls.

Each route records:

```text
route_id × corpus_role × query × recent/full_archive × start/end × language × included post types × exclusions × cap
```

Preserve the exact Boolean query submitted to X. Do not turn a manually edited screenshot of Advanced Search into a purported reproducible bulk route.

Keep background, event, and prospective frames separate:

- background window: ordinary conversation over a defined period;
- event window: launch, outage, controversy, regulation, or campaign;
- live frame: new posts after a declared activation time.

## Preserve conversation and post type

Required provenance:

```text
collection_run_id
connector_id
connector_revision
source_platform
source_url
x_post_id
conversation_id
x_post_type
source_query
source_search_mode
created_at
collected_at
last_verified_at
content_status
```

Use `x_post_type=original`, `reply`, `quote`, or `repost`. A repost without new text is E0 only. A quote may contain evidence only in its added text. Preserve referenced-post IDs and author IDs only to the minimum extent allowed by the study's data-handling plan.

## Pilot and concentration checks

Report requested/reached/written records, unique conversations and days, repost share, dominant conversation/day share, event/background mix, inaccessible or deleted content, E-level yield, counter-evidence yield, and quota/rate stops.

A launch day can create thousands of reposts from one announcement. It is one event signal, not thousands of independent unmet needs.

## Claim boundary

- impressions, likes, reposts, followers, and account visibility are E0;
- an explicit problem may support E1;
- a described workaround/failure may support E2;
- an explicit conditional product preference may support E3;
- price/purchase language may support E4+; explicit rejection/cancellation may support E4−;
- claimed ownership or repeated use requires context and independent validation before it carries decision weight as E5.

Do not infer verified profession, residence, age, demographics, or sensitive traits from bio text, language, network position, or model classification. Do not enrich or track individuals across platforms.


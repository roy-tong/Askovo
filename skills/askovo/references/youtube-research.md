# YouTube research

Use this reference when YouTube is in the source plan. Read [social-media-source-adapters.md](social-media-source-adapters.md), [open-source-connectors.md](open-source-connectors.md), and [connector-contract.md](connector-contract.md) first.

## Approved OSS route

The reviewed connector is [googleapis/google-api-python-client](https://github.com/googleapis/google-api-python-client), the Apache-2.0 official Python client for Google's discovery APIs. The registry pins revision `b0089df6768a806c3d837f71b5ba7eca79934e5a` and uses it with the YouTube Data API.

The Data API can support video search, channel/video metadata, comment threads, and replies. It is not a general public transcript-download API.

[YouTube's Developer Policies](https://developers.google.com/youtube/terms/developer-policies) prohibit directly or indirectly scraping YouTube applications or obtaining scraped YouTube data. Askovo therefore blocks:

- [youtube-comment-downloader](https://github.com/egbertbouman/youtube-comment-downloader), despite its active maintenance and MIT license;
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api), despite its useful interface and MIT license.

Do not use either project as a fallback for API quota or transcript access. A maintained repository can still fail the access gate.

## Adapter config

```json
{
  "youtube": {
    "enabled": true,
    "researcher_role": "external_third_party",
    "connector_id": "youtube-google-api-python-client",
    "connector_revision": "b0089df6768a806c3d837f71b5ba7eca79934e5a",
    "connector_license": "Apache-2.0",
    "collection_mode": "historical_search",
    "access_basis": "official_api",
    "policy_status": "approved_for_study",
    "terms_reviewed_at": "YYYY-MM-DD",
    "data_rights_reviewed_at": "YYYY-MM-DD",
    "data_rights_basis": "Approved API-data storage, refresh, deletion, and display basis",
    "retention_rule": "Exact refresh and deletion rule",
    "min_unique_channels": 3,
    "min_unique_videos": 10,
    "max_channel_share": 0.5,
    "max_video_share": 0.2,
    "require_original_source": true,
    "treat_ai_summaries_as_discovery_only": true
  }
}
```

Do not shard Google Cloud projects or API keys to bypass quota. Reduce scope, request an appropriate quota, or block the route.

## Sample videos before comments

Create channel/video strata such as:

1. product reviews and comparisons;
2. task or professional demonstrations without product language;
3. alternatives, criticism, and return stories;
4. setup, deployment, support, and long-term reviews;
5. mainstream workflows and no-problem controls.

Within each group, vary channel, date, language, video format, view band, and stance. Then cap records per video. Pulling thousands of comments under one viral review is still one-video sampling.

Each route records:

```text
route_id × corpus_role × channel_group × video_query × video_order × window × comment_order × reply policy × target videos × per-video cap
```

## Preserve comment hierarchy and stance target

Required provenance:

```text
collection_run_id
connector_id
connector_revision
source_platform
source_channel
source_url
youtube_video_id
youtube_item_id
youtube_content_type
source_query
source_order
created_at
collected_at
last_verified_at
refresh_due_at
content_status
```

Top-level comments also need `comment_thread_id`; replies need `comment_thread_id` and `parent_comment_id`.

Add `stance_target`: product, task/workflow, creator/presenter, video production, another comment, or unclear. “Great video” generally evaluates the content/creator and is E0 for product research.

## Comments and replies

The official [`commentThreads.list`](https://developers.google.com/youtube/v3/docs/commentThreads/list) endpoint supports `time` or `relevance` ordering and up to 100 results per page. Preserve which order was used. A returned thread may not include every reply; fetch replies through the applicable official endpoint when the route requires complete thread context.

## Transcript boundary

Use transcripts only when the study has an explicitly authorized source, such as creator-supplied captions or a participant-provided file with a clear reuse basis. Store each segment's source and timestamp. Do not label unofficial transcript extraction as `official_api`.

## Pilot and concentration checks

Report unique channels/videos, dominant channel/video share, top-level/reply mix, `time`/`relevance` mix, stance targets, inaccessible/deleted content, expired refresh dates, E-level yield, counter-evidence, quota cost, and stop reason.

The CLI fails expired `refresh_due_at`, missing comment hierarchy, connector mismatch, and configured concentration violations. A pass does not imply complete comments, representative viewers, verified identities, or population demand.


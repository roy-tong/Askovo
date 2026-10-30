# Open-source connector registry

Use this reference before choosing any GitHub project for Reddit, X, YouTube, Amazon, JD, Taobao/Tmall, or Kickstarter research. The machine-readable registry is [open-source-connectors.json](../assets/open-source-connectors.json).

The registry covers acquisition code, not research conclusions. A repository may be open source while its acquisition method is disallowed, its output is stale, or its data cannot be reused for the intended study.

## Four gates, in order

| Gate | Question | Pass condition |
| --- | --- | --- |
| Code | Can we inspect, fork, and redistribute the code? | Recognized license, pinned revision, understandable dependencies |
| Access | Does the project use a permitted platform surface? | Official API or another explicitly authorized route; no login simulation, internal endpoint, CAPTCHA bypass, or rate-limit bypass |
| Data | May this study retain and use the returned data? | Platform terms, dataset terms, privacy, deletion, and redistribution rules reviewed for this use |
| Research | Can the output support the intended claim? | Required fields, source hierarchy, time range, counter-evidence, and concentration controls are available |

Failure at an earlier gate ends the review. Do not compensate for a failed access gate with a stronger parser or a permissive code license.

## Reviewed projects as of 2026-08-27

| Platform | Repository | Registry decision | What it means for askovo |
| --- | --- | --- | --- |
| Reddit | [praw-dev/praw](https://github.com/praw-dev/praw) | `supported` | Default OSS client when the study has approved Reddit Data API access; register the API app by 2026-09-30 and re-review after the Devvit transition |
| X | [tweepy/tweepy](https://github.com/tweepy/tweepy) | `supported` | Default OSS client for the official X API |
| YouTube | [googleapis/google-api-python-client](https://github.com/googleapis/google-api-python-client) | `supported` | Default OSS client for YouTube Data API search, metadata, and comment threads |
| Amazon | [hyp1231/AmazonReviews2023](https://github.com/hyp1231/AmazonReviews2023) | `historical_only` | Historical review analysis through September 2023; no current live signal |
| Amazon | [ae9is/amazon-reviews](https://github.com/ae9is/amazon-reviews) | `historical_only` | Self-hosted GraphQL layer over the same historical dataset; AGPL review required |
| X | [JustAnotherArchivist/snscrape](https://github.com/JustAnotherArchivist/snscrape) | `blocked` | Non-API scraper; incompatible with current X guidance and stale for current X behavior |
| X | [d60/twikit](https://github.com/d60/twikit) | `blocked` | Uses an internal API without an official API key; maintained code does not make the route permitted |
| YouTube | [egbertbouman/youtube-comment-downloader](https://github.com/egbertbouman/youtube-comment-downloader) | `blocked` | Comment scraping without the YouTube Data API; current YouTube policy prohibits scraped YouTube data |
| YouTube | [jdepoix/youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | `blocked` | Useful codebase, but the retrieval route is outside the official Data API and is not an askovo default |
| JD | [2274900/JD_comment_spider](https://github.com/2274900/JD_comment_spider) | `blocked` | Old direct-endpoint scraper, not a maintained or policy-compatible current connector |
| Taobao/Tmall | [l010306/taobao-review-playwright](https://github.com/l010306/taobao-review-playwright) | `blocked` | Automates QR login and saves session state; current platform rules prohibit unauthorized crawling and simulated use |
| Kickstarter | [ImWhiteRabbit/KSInsights](https://github.com/ImWhiteRabbit/KSInsights) | `blocked` | Historical snapshots exist, but the feed stopped in 2025 and was produced by a crawler that conflicts with current Kickstarter terms |

`blocked` does not mean the code is poor. It means this project cannot be selected as an askovo acquisition connector under the reviewed conditions. Keeping negative reviews in the registry prevents another Agent from rediscovering the repository and treating GitHub availability as permission.

## Current platform conclusion

### Stable default routes

- Reddit: PRAW on approved Reddit Data API access.
- X: Tweepy on the official X API.
- YouTube: Google's Python API client on the YouTube Data API.

These clients solve transport and object handling. They do not solve route design, representativeness, retention, deletion, or evidence coding.

Reddit's 2026 [public Data API plan](https://www.reddit.com/r/redditdev/comments/1vgbm9c/our_plans_for_the_future_of_reddits_public_data/) keeps PRAW valid for studies that already hold approved access, but existing apps must be registered by 2026-09-30, new self-service access is closed pending approval, and the long-term direction is the Developer Platform (Devvit). A study without approved Reddit credentials records a Reddit access gap; it does not downgrade to a blocked non-API route. Re-review the Reddit entry after 2026-09-30.

### Historical route

Amazon Reviews 2023 is useful for developing parsers, codebooks, variant-aware sampling, and historical category hypotheses. It ends in September 2023. Use `source_period_end=2023-09`, label every conclusion historical, and confirm the dataset reuse basis separately from the GitHub code license.

### No supported live OSS connector found

At this review date, the registry has no supported live third-party connector for Amazon reviews, JD reviews, Taobao/Tmall reviews, or Kickstarter. For these platforms:

1. do not silently switch to a seller API, commercial provider, login session, internal endpoint, or browser automation;
2. record the route as blocked;
3. use a lawful historical dataset when one passes the data-rights gate;
4. use small manual public examples only as discovery material where permitted, not as a disguised bulk collector;
5. move validation to interviews, user-supplied records, field observation, or another authorized source family.

This negative result is part of the method. A platform is not an available evidence source merely because a GitHub search returns a scraper.

## CLI usage

List selectable connectors:

```bash
python3 scripts/askovo.py connectors
python3 scripts/askovo.py connectors --platform amazon
```

Include rejected projects and their reasons:

```bash
python3 scripts/askovo.py connectors --platform x --include-blocked
```

When a platform adapter is enabled, `askovo.py check` verifies that:

- `connector_id` exists in the bundled registry;
- the connector belongs to the selected platform;
- the pinned revision and code license match the reviewed entry;
- the connector is not blocked;
- historical-only connectors use `access_basis=historical_dataset`;
- platform terms and dataset rights were reviewed for this study.

## Forking or adding a connector

Do not overwrite an existing registry entry with a fork. Add a new entry with a new ID and complete this review:

1. pin a commit, not a floating branch;
2. record the SPDX code license and all dependency licenses that affect redistribution;
3. describe the actual acquisition mechanism by reading the code;
4. search for login automation, saved cookies, internal endpoints, proxy rotation, CAPTCHA handling, and 403/429 bypass;
5. review the current platform terms and the intended study use;
6. review dataset/content rights separately from the code license;
7. map output to the [connector contract](connector-contract.md);
8. run a small fixture test and a blocked-route test;
9. set `decision=supported` or `historical_only` only when all earlier gates pass;
10. preserve the negative review if it remains blocked.

Never copy GPL/AGPL code into the MIT askovo codebase without a license-compatible plan. A separate process or service boundary may still carry obligations and needs review.


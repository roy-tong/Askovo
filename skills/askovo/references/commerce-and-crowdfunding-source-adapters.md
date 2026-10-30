# Commerce and crowdfunding source adapters

Use this reference for Amazon, JD.com, Taobao/Tmall, or Kickstarter. Read [open-source-connectors.md](open-source-connectors.md) and [connector-contract.md](connector-contract.md) before selecting code.

The scope is independent third-party research. Seller Central, Vendor Central, 京东商智, 生意参谋, merchant exports, Kickstarter Creator Dashboard, and private Backer Reports are not default routes. Every enabled adapter uses `researcher_role=external_third_party`.

## Current open-source conclusion

The review on 2026-08-27 did not find a supported live OSS connector for these four platform families.

| Platform | GitHub project reviewed | askovo decision | What is still usable |
| --- | --- | --- | --- |
| Amazon | [AmazonReviews2023](https://github.com/hyp1231/AmazonReviews2023) | `historical_only` | Historical reviews and metadata through September 2023 after a separate dataset-rights review |
| Amazon | [amazon-reviews GraphQL](https://github.com/ae9is/amazon-reviews) | `historical_only` | A self-hosted query layer over the same dataset; AGPL obligations apply |
| JD.com | [JD_comment_spider](https://github.com/2274900/JD_comment_spider) | `blocked` | Parser ideas and synthetic fixtures only; no live collection |
| Taobao/Tmall | [taobao-review-playwright](https://github.com/l010306/taobao-review-playwright) | `blocked` | Architecture review only; do not use its QR-login/browser-automation route |
| Kickstarter | [KSInsights](https://github.com/ImWhiteRabbit/KSInsights) | `blocked` | Schema ideas only; snapshots stopped in 2025 and were produced by a crawler |

This result must not be repaired by switching to a commercial provider, a seller API, a merchant account, an internal endpoint, or login automation. Mark the route blocked and move the validation to an authorized source family.

## Why GitHub availability is not enough

Review four separate permissions:

| Layer | Example question |
| --- | --- |
| Code license | May we fork and modify this repository? |
| Platform access | Does the code use an official or otherwise authorized surface? |
| Data rights | May this study retain and reuse reviews, identifiers, or campaign data? |
| Claim eligibility | Does the record contain enough context for the intended askovo evidence level? |

The Taobao candidate is MIT licensed but automates QR login and saves session cookies. That passes a code-license check and fails the access check. AmazonReviews2023 provides MIT-licensed processing code, but the dataset reuse basis still requires a separate decision.

## Natural hierarchies and distortions

| Source | Natural hierarchy | Potential signal | Main distortion |
| --- | --- | --- | --- |
| Amazon | marketplace/category → parent ASIN → child ASIN → review | Review text, rating, verified-purchase label, historical item metadata | Historical cutoff, merged variants, review participation, product/brand concentration |
| JD.com | category → brand/store → SPU → SKU → review/follow-up | Product and post-purchase language when lawfully obtained | Incentives, default evaluations, service/logistics mixed with product, store concentration |
| Taobao/Tmall | category → shop → item → SKU → review/follow-up | Variant and follow-up language when lawfully obtained | Login dependency, anonymous/default evaluations, shop/item concentration |
| Kickstarter | category → creator → campaign → funding state/update/comment | Conditional backing, aggregate funding, delivery discussion when authorized | Marketing copy, reversible pledges, one viral campaign, creator claims mistaken for user evidence |

Multiple products or campaigns improve within-platform coverage. They do not replace interviews, observation, support records, prototype tests, or realized post-purchase behavior.

## Signal boundaries

- A review is a feedback record, not automatically a unique buyer or active user.
- Star rating without text is E0.
- `verified_purchase` supports transaction provenance; it does not prove satisfaction, retention, or current use.
- A complaint about returning does not prove a completed return.
- Product descriptions, seller replies, creator updates, and campaign pages are supply-side context.
- A Kickstarter pledge or public funding total is conditional commercial behavior, not E5 realized use.
- Historic Amazon reviews cannot support claims about the current market, current product generation, current price, or current platform behavior.

## Amazon historical route

When `amazon-reviews-2023` is selected:

1. use `collection_mode=historical_search` and `access_basis=historical_dataset`;
2. pin the connector revision in `study.json` and the run manifest;
3. record a data cutoff no later than `2023-09`;
4. map `asin` and `parent_asin` separately;
5. retain `rating`, `verified_purchase`, `timestamp`, and `helpful_vote` as source fields;
6. sample across categories, parent/child ASINs, rating bands, and time periods;
7. state that the findings are historical in every demand judgment;
8. validate current relevance through interviews, current user-supplied records, field observation, or another authorized source.

The bundled Amazon route template contains only fields available from this historical dataset. It does not invent questions, return records, or current review topics.

## Blocked-route workflow for JD, Taobao, and Kickstarter

The route templates remain in the Skill to define the evidence that would be useful. Their `connector_id` is `NO_SUPPORTED_CONNECTOR` and `access_basis` is `blocked`.

For a blocked route:

1. preserve the intended category, product/campaign set, corpus role, and decision use;
2. record the repository reviewed and the exact failure gate;
3. do not collect through that repository;
4. choose interviews, participant-provided records, field observation, lawful public documents, or a different platform family;
5. keep the resulting evidence gap visible in the final audit.

Absence of a supported connector means “this route is unavailable under the current rules.” It does not mean users have no problem or no demand.

## Evidence fields

Marketplace records add:

```text
collection_run_id
connector_id
connector_revision
source_platform
source_url
commerce_product_id
commerce_variant_id
commerce_store_id
commerce_brand
commerce_record_id
commerce_content_type
commerce_transaction_status
source_completeness
source_query
created_at
collected_at
content_status
```

Kickstarter records add campaign, creator, content type, campaign status, commercial status, privacy status, query, and timestamps to the same connector provenance.

Use stable IDs, not titles, as keys. Do not place credentials, cookies, raw names, emails, addresses, payment information, private messages, or unnecessary personal text in the evidence workspace.

## Adding a future fork

If a new connector or user-maintained fork becomes viable, add a new ID to the registry. Pin a commit, record the code license, read the actual acquisition code, review current platform and data terms, map output to the connector contract, add synthetic transformation tests, and preserve any blocked predecessor as a negative review.


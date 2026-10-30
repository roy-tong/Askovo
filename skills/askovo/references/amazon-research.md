# Amazon research

Use this reference when an independent third party studies historical Amazon reviews. Read [commerce-and-crowdfunding-source-adapters.md](commerce-and-crowdfunding-source-adapters.md), [open-source-connectors.md](open-source-connectors.md), and [connector-contract.md](connector-contract.md) first.

## No supported live OSS connector

The 2026-08-27 review did not find a maintained, licensed, policy-compatible GitHub connector for live third-party Amazon review research. Askovo does not replace this gap with a seller API, commercial provider, proxy service, CAPTCHA bypass, or browser scraper.

The supported open-source route is historical only:

- [AmazonReviews2023](https://github.com/hyp1231/AmazonReviews2023), MIT-licensed processing code for the McAuley Lab dataset;
- optionally [ae9is/amazon-reviews](https://github.com/ae9is/amazon-reviews), an AGPL-3.0 self-hosted GraphQL layer over the same dataset.

The dataset contains reviews and metadata through September 2023. It does not provide current reviews, questions, returns, current price, current catalog state, or current competitive response. The processing code's MIT license is separate from the dataset/content reuse basis; review both.

## Adapter config

```json
{
  "amazon": {
    "enabled": true,
    "researcher_role": "external_third_party",
    "connector_id": "amazon-reviews-2023",
    "connector_revision": "b18fdf54bd46013d60799684f7a4eb80d8501d1a",
    "connector_license": "MIT",
    "collection_mode": "historical_search",
    "access_basis": "historical_dataset",
    "policy_status": "historical_data_only",
    "terms_reviewed_at": "YYYY-MM-DD",
    "data_rights_reviewed_at": "YYYY-MM-DD",
    "data_rights_basis": "Exact dataset and study reuse basis",
    "retention_rule": "Exact rule",
    "min_unique_products": 5,
    "min_unique_stores": 3,
    "min_unique_brands": 3,
    "max_product_share": 0.25,
    "max_store_share": 0.5,
    "max_brand_share": 0.5,
    "max_single_month_share": 0.4,
    "require_variant_id": true,
    "require_original_source": true,
    "treat_ai_summaries_as_discovery_only": true
  }
}
```

## Available fields and mapping

The published dataset includes review fields such as `rating`, `title`, `text`, `images`, `asin`, `parent_asin`, `user_id`, `timestamp`, `helpful_vote`, and `verified_purchase`, plus item metadata.

Map them without inventing missing signals:

| Dataset field | Askovo use |
| --- | --- |
| `asin` | `commerce_variant_id`; preserve the exact reviewed item |
| `parent_asin` | `commerce_product_id`; use for product-family grouping |
| `rating`, `title`, `text` | Source content and rating stratum |
| `verified_purchase` | `verified_purchase` or `unverified` provenance; never automatic E5 |
| `timestamp` | `created_at`; the latest permissible value is September 2023 |
| `helpful_vote` | E0 engagement only |
| item store/brand metadata | Concentration and product mapping when present |

Create a stable `commerce_record_id` from the source record identity. Do not use a text hash as the primary source ID.

## Sampling design

Sample across category, parent ASIN, child ASIN, brand/store, rating band, verified/unverified status, and month/year. Keep direct products, open task-adjacent products, alternatives/rejectors, long-term/support language, and positive/no-problem controls in separate route rows.

Do not sample only one-star reviews or bestsellers. Low-star filtering helps find failure modes and exaggerates severe failure prevalence. Helpful-vote sorting amplifies older and more visible reviews.

## Evidence boundary

- Rating only: E0.
- Review text with explicit task/problem: up to E1.
- Review text with workaround, failure, or switching cost: up to E2.
- Explicit acceptance of the studied solution: up to E3 when the target is clear.
- A verified-purchase label alone is not E4+ or E5.
- A stated purchase/price anchor may support E4+; a stated return intention does not prove E4− completion.
- Claimed long-term ownership may be candidate E5 evidence, but current retained use requires independent verification.

Every demand judgment must say `historical evidence through 2023-09`. Use interviews, participant-provided current records, support data, or field observation to test whether the pattern still exists.

## Required provenance

Every selected record includes `collection_run_id`, `connector_id`, `connector_revision`, product/variant/store/brand IDs, source record ID, content type, transaction status, completeness, source query, timestamps, content status, and a stable source reference permitted by the data-use plan.

The CLI audits product/store/brand/month concentration, variant presence, connector selection, and evidence limits. It cannot certify the dataset's legal reuse for a particular organization or make historical data current.


# Kickstarter research

Use this reference when Kickstarter is proposed as a third-party research source. Read [commerce-and-crowdfunding-source-adapters.md](commerce-and-crowdfunding-source-adapters.md) and [open-source-connectors.md](open-source-connectors.md) first.

## Current decision: no supported connector

The reviewed [ImWhiteRabbit/KSInsights](https://github.com/ImWhiteRabbit/KSInsights) repository is MIT licensed and publishes structured campaign snapshots. Its files include campaign, creator, category, funding, backer-count, launch/deadline, location, and status fields. The latest snapshot found in the repository is from August 2025, despite the README's weekly-update description.

The README also says the data is produced by a Kickstarter scraper. Kickstarter's current [Terms of Use](https://legal.kickstarter.com/policies/en/?name=terms-of-use) prohibit software or devices from crawling or spidering the site. The repository's MIT license does not resolve the collection route or platform-data reuse rights.

The registry decision is `blocked`. Do not treat the repository as a current feed or copy its scraper into Askovo.

## What the repository can still contribute

- a campaign snapshot schema;
- examples of category, creator, campaign, funding-state, and time-window fields;
- synthetic fixtures for funding-snapshot transformations;
- a negative test for stale feeds and scraped-data provenance.

Do not reuse the bundled real campaign snapshots without a separate data-rights decision.

## Keep the intended route visible

The route template preserves direct-solution, open-scene, rejection, post-purchase, and control questions but sets:

```text
connector_id=NO_SUPPORTED_CONNECTOR
access_basis=blocked
```

Campaign pages and creator updates are supply-side context. Public funding totals are aggregate conditional behavior. A campaign's success or failure does not reveal one backer's role, scene, task, acceptance condition, or cancellation reason.

## Commercial evidence boundary

- campaign page, FAQ, and creator update: E0;
- public funding snapshot: E0 or aggregate E4+ context, never E5;
- a pledge is conditional and may change;
- a charged pledge is a realized transaction but not fulfilled use;
- refund and fulfillment records require authorized, deidentified, or aggregate data;
- private backer names, emails, addresses, payment data, and messages do not belong in Askovo evidence.

## Replacement sources

Use creator/backer interviews, participant-provided pledge or delivery records with consent, public press or project documents as E0 context, direct concept/preorder tests, or a different authorized source family. Do not use creator credentials, private Backer Reports, commercial trackers, or an unreviewed crawler to fill the gap.

## If a future OSS connector appears

Add a new registry ID only after confirming a permitted acquisition surface, code and data licenses, freshness, campaign identity, pagination, deletion/retention rules, privacy minimization, stop behavior, and the [connector contract](connector-contract.md). Keep the KSInsights review as a blocked historical entry.


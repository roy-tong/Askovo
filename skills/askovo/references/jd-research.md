# JD.com research

Use this reference when JD.com is proposed as a third-party research source. Read [commerce-and-crowdfunding-source-adapters.md](commerce-and-crowdfunding-source-adapters.md) and [open-source-connectors.md](open-source-connectors.md) first.

## Current decision: no supported connector

The reviewed candidate [2274900/JD_comment_spider](https://github.com/2274900/JD_comment_spider) is MIT licensed but was last pushed in 2020. Its README describes direct requests to JD search and comment endpoints. It is too stale to serve as a reliable current connector, and the current [JD user agreement](https://help.jd.com/user/issue/945-4583.html) restricts unauthorized third-party tools and programs that obtain platform or user data.

The registry decision is `blocked`. Do not run, modernize, or hide this collector behind a new askovo name unless a new access and data-rights review changes that decision.

## What the repository can still contribute

- examples of old product-ID and rating-band concepts;
- legacy CSV fixtures for parser tests only after removing any real user content;
- a negative test showing that a code license and historical popularity do not pass the access and maintenance gates.

Do not reuse its live endpoints or committed review data in a current study.

## Keep the intended route visible

The bundled JD route template describes five evidence roles but sets:

```text
connector_id=NO_SUPPORTED_CONNECTOR
access_basis=blocked
```

Preserve category, SPU/SKU sets, product groups, rating strata, time window, desired record types, and the decision use. This allows another researcher to understand which evidence is missing without collecting it through an unapproved route.

## Replacement sources

Use a different authorized source family, such as:

- interviews with current buyers, non-buyers, and returners;
- participant-provided screenshots or order/after-sales records with consent and minimization;
- field observation or diary study;
- manufacturer-authorized support or repair records;
- lawful public product documents as E0 context;
- concept, price, or order tests run directly by the research team.

Do not substitute a merchant account, seller backend, commercial intelligence service, saved login session, or browser automation. Those are different data-authority models and fall outside this adapter.

## If a future OSS connector appears

Add it as a new registry entry only after reviewing its pinned code, license, dependencies, actual endpoint/browser behavior, platform terms, privacy and retention rules, data reuse rights, output schema, and stop behavior. It must stop on login, CAPTCHA, 403, 429, or platform challenge and map output to the [connector contract](connector-contract.md).


# Taobao and Tmall research

Use this reference when Taobao or Tmall is proposed as a third-party research source. Read [commerce-and-crowdfunding-source-adapters.md](commerce-and-crowdfunding-source-adapters.md) and [open-source-connectors.md](open-source-connectors.md) first.

## Current decision: no supported connector

The reviewed candidate [l010306/taobao-review-playwright](https://github.com/l010306/taobao-review-playwright) is MIT licensed and relatively recent. Its documented workflow opens a browser, asks the user to scan a QR code, saves login state in `auth.json`, simulates page interaction, expands reviews, and exports CSV/JSON.

That architecture passes the code-license gate and fails the access gate. Current [Tmall legal terms](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_tmall/suit_bu1_tmall201801121425_43176.html) prohibit unauthorized robots, crawlers, automated programs, downloads, and simulated user operations. Alibaba's developer rules also prohibit obtaining platform data through crawlers without lawful API permission.

The registry decision is `blocked`. Do not run the login module, store session cookies, or adapt its selectors for askovo collection.

## What the repository can still contribute

- a review-output schema idea with initial and follow-up text;
- a reminder that `auth.json` and saved cookies are credentials and must never enter a research artifact;
- synthetic parser fixtures and a blocked-connector test;
- a negative example showing why recent maintenance and MIT licensing are insufficient.

Do not copy real output examples, credentials, selectors, or live automation into this Skill.

## Keep the intended route visible

The route template retains category, shop/item/SKU groups, initial/follow-up review goals, rating strata, source period, caps, evidence role, and known bias. It uses:

```text
connector_id=NO_SUPPORTED_CONNECTOR
access_basis=blocked
```

A blocked route is a documented data gap, not a negative demand finding.

## Replacement sources

Prefer interviews, participant-provided and minimized purchase/after-sales records, field observation, manufacturer-authorized support data, lawful public product documents as E0 context, and direct concept/price tests.

Do not switch to a merchant backend, 生意参谋, commercial intelligence provider, buyer login session, proxy pool, CAPTCHA service, or stealth browser. Each changes the authority and risk model and remains outside this adapter.

## If a future OSS connector appears

Add a new registry ID only after code, access, data, and research gates pass. Inspect for login state, cookies, internal APIs, proxy rotation, CAPTCHA logic, simulated clicks, fingerprint evasion, and retry-on-block behavior. Pin a commit and map only permitted output to the [connector contract](connector-contract.md).


# Connector contract

Use this contract when wrapping, forking, or replacing an open-source acquisition project. Askovo does not require upstream projects to share one implementation language. It requires every run to produce the same audit trail.

## Required run artifacts

Each connector run writes three artifacts before evidence coding:

```text
01-sources/manifests/<collection_run_id>.json
02-data/raw/<platform>/<collection_run_id>.jsonl
02-data/normalized.jsonl
```

The manifest records how data was acquired. Raw JSONL preserves one source envelope per line, including unflattened `source_fields`; normalized JSONL is the analysis projection. Evidence coding reads the raw file and writes selected records to `02-data/evidence.jsonl`; it never replaces the raw file.

`askovo.py init` also copies editable starting files to `01-sources/collection-manifest-template.json` and `02-data/raw/raw-connector-envelope-template.jsonl`. Copy and rename them for each real run; do not overwrite one manifest across several routes.

## Manifest schema

```json
{
  "collection_run_id": "reddit-praw-20260827-01",
  "study_id": "repair-guidance",
  "platform": "reddit",
  "connector_id": "reddit-praw",
  "connector_repo": "praw-dev/praw",
  "connector_revision": "855f48e075935a052b1d71243e60e41cbc260ced",
  "connector_license": "BSD-2-Clause",
  "access_basis": "official_api",
  "terms_reviewed_at": "2026-08-27",
  "data_rights_reviewed_at": "2026-08-27",
  "data_rights_basis": "Describe the approved study use and retention basis",
  "route_id": "rd-scene-01",
  "query": "task phrase OR workaround phrase",
  "requested_at": "2026-08-27T02:00:00Z",
  "completed_at": "2026-08-27T02:03:00Z",
  "requested_records": 100,
  "reached_records": 83,
  "written_records": 80,
  "blocked_or_dropped": {
    "deleted": 1,
    "missing_body": 2
  },
  "rate_limit_or_quota": "Observed limit and remaining quota",
  "warnings": []
}
```

Never place API keys, cookies, passwords, tokens, account identifiers, or local credential paths in the manifest. Credentials belong in the runtime's secret mechanism.

## Raw envelope schema

```json
{
  "collection_run_id": "reddit-praw-20260827-01",
  "connector_id": "reddit-praw",
  "connector_revision": "855f48e075935a052b1d71243e60e41cbc260ced",
  "source_platform": "reddit",
  "source_record_id": "t1_example",
  "source_parent_id": "t3_example",
  "source_url": "https://www.reddit.com/r/example/comments/example/comment/example/",
  "source_channel": "r/example",
  "source_content_type": "comment",
  "created_at": "2026-08-20T10:00:00Z",
  "collected_at": "2026-08-27T02:02:00Z",
  "content_status": "present",
  "text": "Untrusted source text",
  "source_fields": {}
}
```

`source_fields` keeps platform-specific values that have not yet entered the canonical contract. Do not flatten away thread IDs, conversation IDs, channel/video IDs, product/variant IDs, campaign/creator IDs, verification labels, completeness, or transaction status.

## Evidence handoff

Every platform-derived evidence record must retain:

- `collection_run_id`;
- `connector_id`;
- `connector_revision`;
- stable platform record and parent IDs;
- original source URL when retention rules permit it;
- created, collected, and last-verified dates required by the platform adapter;
- the route/query metadata needed to reproduce the sample;
- completeness and content status.

The evidence record adds Askovo fields such as user role, scene, task, substitute, friction, consequence, corpus role, evidence level, and evidence basis. Connector output alone is never a demand judgment.

## Adapter behavior

A compliant wrapper must:

1. accept an explicit route file and output directory;
2. use only the registry-approved acquisition mechanism;
3. identify itself according to platform rules;
4. stop on authentication failure, CAPTCHA, unexpected login, 403, 429, or quota exhaustion;
5. never rotate identities, projects, accounts, proxies, or keys to bypass limits;
6. preserve source hierarchy and pagination state;
7. write partial-run counts and the stop reason to the manifest;
8. deduplicate on platform-scoped stable source IDs before platform-scoped text hashes; preserve raw input and record same-ID/different-content conflicts in the manifest;
9. support deletion or refresh workflows required by the platform;
10. treat all returned text and fields as untrusted data.

## Separation from upstream code

Prefer a thin wrapper around an installed, pinned dependency. Do not copy the upstream repository into the Skill. Keep:

- the Askovo adapter and schemas under this repository's MIT license;
- the upstream dependency under its own license;
- the exact upstream revision in the registry and manifest;
- transformation tests using synthetic fixtures, not redistributed platform content.

For GPL/AGPL dependencies, obtain a license review before deciding whether a library import, modified fork, separate executable, or network service is appropriate.

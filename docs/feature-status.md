# Askovo: implementation status

Reviewed 2026-10-31 against the repository implementation. Available means local implementation, not production validation on every platform.

| Feature | Scope | Status |
|---|---|---|
| A01–A02 | Business brief, reasoning chain, agent-authored action planning | Available; planning depends on the host Agent |
| A03–A05 | Source routing, authorization and bounded collection | Available for supported connectors; interrupted actions require review |
| A06 | Local PDF/Office/image document intake | Optional Docling adapter via `askovo document`, with SHA-256 provenance and unreviewed status; not a validated research claim |
| A07–A09 | Study workspace, descriptive analysis, evidence audit | Available; human semantic validation remains required |
| A10–A11 | Active follow-up research and option comparison | Comparison available; autonomous resampling loop remains planned |
| A12 | Reports, MRD/PRD/BRD and decision package | Available; refreshed audit guards delivery |
| A13–A15 | Continuous validation, evaluation and industry packs | Existing tests/domain packs; continuous research is not shipped |

Build: SURE reasoning, evidence contracts, authorization, acceptance and delivery. Reuse: existing source connectors; evaluate Crawl4AI/Scrapy for collection and Docling for documents only as optional adapters. Core remains standard-library-only. New document ingestion uses an optional Docling installation; no vendored fork or mandatory core dependency.

Recovery: completed actions are checkpointed before analysis; an interrupted `running` action blocks replay. Inspect collected files and provenance before preparing a replacement plan. Never reset blindly. Execution is serialized using an OS file lock on macOS/Linux. Authorization binds the actual action fields, not just a stored digest.

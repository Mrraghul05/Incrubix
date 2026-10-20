# Engineering report — current implementation

## Approach

The initial repository was empty apart from the assessment. The baseline uses FastAPI/Pydantic for HTTP validation and SQLite for durable destinations, idempotency records, posts, jobs and certification evidence. A connector registry implements a shared set of methods; platform instances are data records, so a second forum can be configured without another adapter. Posting rules run before connector publish. Certification is a background job which validates, publishes, checks status, deletes and stores each step.

## What works in this version

The service has six connector keys and YAML manifests, deterministic simulation publishing, an assisted pack, a signed webhook HTTP adapter tested against a local HMAC-checking mock, persistent idempotency across service restarts, field-level content/rule errors, weekly frequency checks, health/readiness, structured correlation logs, an API job endpoint, a batch runner, and a pytest suite. Results explicitly identify simulation and include an output manifest with no invented provider or cost.

## Limitations

The Discourse, Lemmy, Dev.to and Ghost adapters do not yet call real provider APIs. The signed webhook adapter is HTTP-capable but has only been tested with a local mock. Compose starts only the service and SQLite volume; local Lemmy and Ghost are not configured. S3-compatible storage, upload/URL artifact ingest, scheduled 429 retry, multi-process idempotency locks, callbacks and native platform certification remain incomplete. Therefore no destination is certified as native, and no live demo URL exists. Assisted certification is not presented as machine-published content. The Excel submission workbook was not supplied.

## Measurements and evidence

Seven deterministic core unit tests pass; source compilation, OpenAPI/manifests YAML parsing, and Docker Compose configuration validation also pass. The full HTTP suite did not complete because this sandbox's bundled Windows Python hangs when starting asyncio, and Docker end-to-end could not run because the Docker Desktop Linux engine is unavailable. Evidence is recorded under `artifacts/test-results.md`. A simulation certification records a successful workflow but deliberately keeps `certified: false`; no destination has native certification evidence. No reliability, latency, import throughput, precision, or cost-per-1,000-publications performance number is claimed before measurement.

## Next steps

First run/fix the automated suite and verify compose startup. Then add native API clients with mock HTTP servers, transactional cross-process idempotency, live local Lemmy/Ghost compose, S3-compatible evidence storage, and final review evidence. Deploy only after a hosting target and access policy are available.

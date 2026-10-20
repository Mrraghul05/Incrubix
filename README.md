# IncuBrix Long-Tail Connector Service

Python/FastAPI baseline for the Assessment 4 connector contract. It provides six connector keys, a configurable destination catalogue, content/rules validation, persistent SQLite idempotency and frequency history, asynchronous certification jobs, evidence records, HMAC verification, and deterministic simulation.

> **Implementation status:** Discourse, Lemmy, Dev.to and Ghost use local simulation. The signed webhook connector supports an opt-in HTTP adapter using HMAC-SHA256; it has only been verified against a local mock transport, not a partner endpoint. A successful simulation certification proves the service workflow only. Local Lemmy/Ghost services and their native adapters are not included. Assisted publishing always requires a human.

## Start and test

```powershell
Copy-Item .env.example .env
docker compose up --build
```

In another terminal:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[test]'
pytest
```

The API docs are at `http://localhost:8000/docs`. Health: `/health`, readiness: `/ready`.

## Demo publish

```powershell
$body = @{ destination_id = "lemmy-local"; rendition = @{ title = "A demo"; text = "Simulation only" } } | ConvertTo-Json -Depth 4
Invoke-RestMethod -Uri http://localhost:8000/api/v1/publish -Method Post -Headers @{ "Idempotency-Key" = "demo-001" } -ContentType "application/json" -Body $body
```

The result includes `simulation: true`, a deterministic ID, live URL-shaped simulation reference, and output manifest. Certification runs return HTTP 202 with `job_id`; poll `GET /api/v1/jobs/{job_id}` and use the result link to retrieve stored evidence.

## Configuration and connectors

Edit `config/destinations.yaml` to add another instance; no connector code change is needed. API `POST /api/v1/destinations` can add/update a row. Do not put credentials in this file; resolve them from environment variables. For `signed_webhook`, set `mode: native`, `endpoint_url`, `status_url`, `delete_url`, and `secret_env` (an environment variable name, never its value). The partner must accept the documented JSON request and return `platform_post_id`, `live_url`, and deletion confirmation. Connector manifests live under `manifests/`. The runtime contract is `POST /connector/v1/{connector_key}/{method}` and supports validate, publish, get_status, delete, fetch_metrics and assisted build_assist_pack.

`POST /api/v1/publish` requires `Idempotency-Key`; reuse with the same request returns the saved result, while changed payload returns `IDEMPOTENCY_KEY_REUSED`. The SQLite database persists jobs, posts, certifications and keys across restarts. Current serialization is process-local; production multi-worker publishing needs a shared database transaction/unique-key claim around the provider call.

## Error codes

`DEST_SPEC_VIOLATION`, `DEST_RULE_FREQUENCY_CAP`, `DEST_RULE_SELF_PROMOTION`, `DEST_RULE_LINKS`, `DEST_RULE_AI_DISCLOSURE`, `CONNECTION_AUTH_EXPIRED`, `PLATFORM_RATE_LIMIT`, `PLATFORM_QUOTA_EXHAUSTED`, `PLATFORM_CONTENT_REJECTED`, `PLATFORM_UNAVAILABLE`, `CONNECTOR_DISABLED`, `CONNECTOR_ASSISTED_ONLY`, `IDEMPOTENCY_KEY_REUSED`.

Errors use `{ "error": { "code", "message", "retryable", "details" } }`. Rate-limit simulation returns retry details but timed backoff and live HTTP 429 mapping remain to be implemented.

## Batch runner

Place JSON requests (`destination_id`, `rendition`, optional `connection`) in a file or folder and run:

```powershell
python tools/batch_runner.py ./examples/requests --output ./artifacts/batch
```

Each input gets a `.result.json` and the output directory gets `index.json`.

## Data, storage and licensing

SQLite is the persistent database. Evidence is stored in the database and fetched by API; S3/MinIO file storage is not implemented yet. Default-path dependencies are FastAPI (MIT), Pydantic (MIT), HTTPX (BSD-3-Clause), PyYAML (MIT), Uvicorn (BSD-3-Clause), pytest (MIT), and Python standard library (PSF). No AI model/provider is used. See `SOURCES.md` and `AI_USE.md`.

Use only owned, public-domain, consented, or commercially licensed media and data. Do not contact or publish to real communities, prospects, or partners, or publish as IncuBrix; use simulation, local test instances, or a partner-agreed sandbox only. Example content is synthetic and uses reserved `.invalid` URLs.

## Submission limitations

No Excel Submission Form was present in the workspace. No public demo is deployed, and no live credentials are supplied. These are not represented as complete. See `PROJECT_STATUS.md` and `REPORT.md` for current measured status and evidence gaps.

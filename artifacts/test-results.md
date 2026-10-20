# Test and validation results

These results record only commands actually run in this workspace.

## Submission-readiness verification (2026-10-20)

| Check | Result | Evidence / limitation |
|---|---|---|
| `python -m pytest -q tests/test_core.py --basetemp .pytest-hard-cases-final` | Passed: 18 tests | Includes rules/limits, simulation error mapping, frequency caps, deleted certification cleanup, signed webhook HMAC, partner error mapping, and lost-response retry with the same idempotency key. Full output: `artifacts/test-run-logs/pytest-hard-cases-final.txt`. |
| README command `.venv\\Scripts\\python.exe -m pytest` | Failed: 6 passed, 7 errors | Pytest could not create its default temp directory under the sandbox temp path. Full output: `artifacts/test-run-logs/pytest-readme-default.txt`. |
| `python -m pytest -q tests/test_core.py --basetemp .pytest-submit-core` | Passed: 7 tests | Full output: `artifacts/test-run-logs/pytest-core-local-temp.txt`. |
| Full suite with workspace `--basetemp` | Interrupted after ~60 seconds | Seven tests printed as completed; then no output while entering API tests. Interrupted; no final summary. Do not count as a suite pass. |
| `docker compose ps -a` | Failed: Docker daemon unavailable | Docker Desktop Linux engine named pipe is missing. Output: `artifacts/test-run-logs/docker-compose-ps.txt`. No container startup or live demo was verified. |

| Check | Result | Evidence / limitation |
|---|---|---|
| `python -m compileall -q app tests tools` | Passed | All current Python source compiled. |
| YAML parsing | Passed | `openapi.yaml` parsed as OpenAPI 3.1.0; all six connector manifests parsed. |
| `docker compose config` | Passed | Compose configuration rendered successfully. |
| `pytest tests/test_core.py` (earlier run) | Passed: 7 tests | Earlier coverage: field rules and limits, content types, rate-limit mapping, manifest cost, fingerprints, URL validation, persistent frequency caps, and HMAC-signed webhook publish/status/delete against a mock transport. See the latest 18-test run above. |
| HTTP/API pytest suite | Not completed | Default run fails during pytest temp-directory setup; workspace-local temp run printed seven completed tests then stalled in API tests and was interrupted. A clean API suite run remains necessary. |
| Docker end-to-end | Not run | `docker compose ps -a` confirms Docker Desktop Linux engine pipe is unavailable. |

The latest passing core suite is not the complete PDF test plan. Connector API tests still stall in this Windows Python environment, and native Lemmy/Ghost end-to-end checks have not run because Docker is unavailable. Do not treat simulation tests as proof of native platform connectivity or destination certification.

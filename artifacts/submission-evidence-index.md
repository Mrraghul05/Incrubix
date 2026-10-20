# Submission evidence index (partial)

This index points to current project evidence for IncuBrix Assessment 4. It distinguishes recorded results from test source code. The required separately supplied Excel form was not in this workspace; `outputs/01a15789-9cd6-74f2-a962-77fdab82c54b/Submission_Form_Draft.xlsx` is an explicitly labeled draft, not the official form.

| Claim area | Evidence | Evidence type | Limits / missing material |
|---|---|---|---|
| API contract, routes, error codes | `openapi.yaml`, `app/main.py`, `README.md` | Source and specification | Exact OpenAPI-to-running-service parity has not been verified. |
| Connector manifests | `manifests/*.yaml` | Configuration source | Manifests do not prove native platform connectivity. |
| Destination configuration | `config/destinations.yaml`, `tests/test_service.py` | Configuration and test source | Reviewer clean-machine add-instance run is not recorded. |
| Posting rules and caps | `app/core.py`, `tests/test_core.py`, `tests/test_service.py` | Implementation and test source | Aggregate rule-test results are not recorded. |
| Idempotency and conflict behavior | `app/`, `tests/test_service.py` | Implementation and test source | Forced timeout/retry evidence is missing. |
| Signed webhook HMAC | `tests/test_core.py` | Test source | Existing test results report the mock transport test passed; no partner endpoint is certified. |
| Simulation certification workflow | `tests/test_service.py` | Test source | No native destination certification, live URL, screenshot, or deletion record is included. |
| Recorded automated checks | `artifacts/test-results.md`; `artifacts/test-run-logs/pytest-hard-cases-final.txt`; `artifacts/test-run-logs/pytest-readme-default.txt`; `artifacts/test-run-logs/pytest-core-local-temp.txt`; `artifacts/test-run-logs/docker-compose-ps.txt` | Results summary and captured command logs | Latest core suite passes 18 tests. Default README test command fails on sandbox temp permissions; full suite stalls in API tests; Docker daemon unavailable. |
| Batch runner | `tools/batch_runner.py`, `examples/requests/demo.json` | Source and sample input | A captured complete batch output folder is missing. |
| Runtime configuration / secret handling | `.env.example`, `.gitignore`, `README.md` | Configuration and documentation | Run a final repository/log secret scan before submission. |
| Architecture, limitations, measurements | `README.md`, `REPORT.md`, `PROJECT_STATUS.md` | Documentation | Several performance and reliability metrics remain unmeasured; simulation is not native certification. |
| Sources and AI disclosure | `SOURCES.md`, `AI_USE.md` | Disclosure documents | Candidate should review and confirm completeness before submitting. |

## Test pack contents still required

- Archive every input used, including hard-case inputs.
- Capture all outputs, including failures, and sanitized structured application logs from actual runs. Current command logs cover the latest limited verification only.
- Record command, environment, date, and result for each run.
- For each claimed certification, include the run record, live URL or API response, screenshot, and deletion confirmation.
- Link each submission-form claim to the exact evidence file and relevant section or line.
- Record the unedited demo video and its run evidence.

Do not treat test source code or simulation workflow results as proof of native certification.

## Key-rules review

- **Individual work / AI disclosure:** `AI_USE.md` discloses OpenAI Codex assistance and identifies GPT-6 for this preparation session. Model identifiers for earlier implementation sessions are not recorded; the candidate must confirm them, review, and explain the work.
- **Commercial-use licensing:** `SOURCES.md` records the resolved Windows environment's direct and transitive package versions and license metadata. Full clearance remains **partial** because dependency ranges are not locked and the exact Linux image/OS package SBOM has not been generated.
- **Media/data rights:** no media files or external datasets were found in the project; test content is synthetic. Continue using only owned, public-domain, consented, or properly licensed materials.
- **No real-world outreach or posting:** included examples are simulation/mock based. Use only local instances or a partner-agreed sandbox; no real community or partner was contacted during this review.
- **Evidence honesty:** the submission workbook distinguishes implementation/test source from recorded results. Do not upgrade Partial/No statuses without new evidence.
- **Reviewer access:** **not verified**. No GitHub remote, commits, deployed URL, access policy, or upload target exists in this workspace, so reviewer access cannot yet be granted or checked.
- **README reproduction:** instructions are documented, but full Docker + test startup is not verified; Docker E2E and the HTTP/API suite remain incomplete per `artifacts/test-results.md`.
- **Must-haves:** **not met**; see `outputs/01a15789-9cd6-74f2-a962-77fdab82c54b/Submission_Form_Draft.xlsx` and `PROJECT_STATUS.md`.
- **Live evaluation readiness:** candidate review and a supported environment run are required before claiming the solution can be explained, modified, and reproduced live.

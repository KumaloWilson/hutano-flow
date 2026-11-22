# Verification evidence — 22 November 2026

Current report for commit `9982310` plus the 22 November changes (readable fictional
clinic, evaluation browser test, host environment fix, presenter conveniences). Earlier reports:
[26 October](TEST_EVIDENCE_20261026.md), [25 October](TEST_EVIDENCE_20261025.md),
[28 October research depth](RESEARCH_DEPTH_EVIDENCE.md).

These checks verify a **synthetic research prototype**. They do not show clinical
validity, approval for patient care or readiness for public production.

Environment: Linux, Docker Compose, PostgreSQL 17, Python 3.12.8 (API image) and 3.12.14 (host
`.venv`), Node 22.23.4, Google Chrome.

## Executed checks

| Check | Result | Command |
|---|---|---|
| Backend unit/API/integration, including real PostgreSQL | **150 passed, 0 skipped** (116 s) | API image, `TEST_POSTGRES_URL` → disposable `postgres:17` container |
| Backend on host | **143 passed, 7 skipped** (PostgreSQL-only, no database URL) | `make test-local` |
| Frontend unit tests | **22 passed** (8 files) | `npm test` |
| TypeScript | PASS, no errors | `npm run typecheck` |
| Full-stack browser workflows | **14 passed, 0 skipped** (96 s), including one that performs the whole defence script and one that checks the waiting-room display speaks each call; [summary](evidence/browser-enhanced.json) | `python3 scripts/verify_browser.py` |
| Clean boot, reset and backup/restore | PASS: two fresh boot cycles; fictional clinic prepared at start-up and its admin signs in; restricted runtime inserted journeys; actual backup/restore commands restored visits and private dataset hashes | `python3 scripts/verify_clean_boot.py` |
| OpenAPI drift | PASS: spec and TypeScript contracts regenerated for the new preparation endpoint (103 schemas) | `python -m app.cli openapi`; `node scripts/generate-contracts.mjs` |

The browser suite runs in a uniquely named disposable Compose project with its own
PostgreSQL volume, migrations, durable worker, 300 generated research visits and the
prepared fictional clinic. The project and its volumes are removed afterwards; the main
demo is not touched. The one remaining warning is the upstream Starlette notice about a
future `httpx2` test client; it is not a test failure.

### New since 26 October

- **Evaluation and calibration in the browser** ([evaluation.spec.ts](../apps/web/tests/e2e/evaluation.spec.ts)).
  A researcher runs a baseline-calibrated simulation from the seeded synthetic
  time-and-motion baseline. The test checks that the baseline-reproduction verdict and paired comparison
  appear. It opens the Evaluation view (objectives O1–O4, research questions, limitations)
  and records one consented usability session with SUS and TAM. It checks the score
  (SUS 75, PU 6, PEOU 5) reaches the O4 evidence. Screenshots:
  [calibrated simulation](evidence/calibrated-simulation.png), [evaluation](evidence/evaluation-objectives.png).
- **Readable fictional clinic** ([ADR-037](DECISIONS.md), [demo_cast.py](../services/api/app/demo_cast.py)).
  `test_cast_is_coherent_and_supports_the_advisory` checks sex and age consistency,
  the sex mix, tokens rising with arrival time, that only returning patients have
  earlier visits, enough recorded vitals for the advisory on every triaged case, and that
  seeded text contains no diagnoses or prescriptions. The clinic browser test opens a
  returning patient's record by name. Screenshots: [overview](evidence/clinic-overview.png),
  [patient history](evidence/clinic-patient-history.png).
- **Presenter conveniences** ([ADR-038](DECISIONS.md)). Start-up prepares the fictional clinic, and the clean boot checks it.
  An administrator prepares a fresh rehearsal from the Demo guide. Readiness of research jobs and advisory status
  update on their own. A clinic-hours note appears when preparation happens outside the clinic day. An optional,
  clearly labelled scripted advisory review is available. A one-step demo-role switcher appears only in the
  fictional clinic. [presenter.spec.ts](../apps/web/tests/e2e/presenter.spec.ts) covers fresh preparation with the
  scripted review, waiting for results, switching to triage and getting a real advisory answer. Backend tests cover
  refresh-only-when-stale, admin-only and fictional-clinic-only preparation, and the review applying only when asked.
  Screenshots: [demo guide](evidence/demo-guide-ready.png), [triage advisory](evidence/triage-advisory.png).
- **Host environment.** The previous `.venv` pointed to an interpreter under `/tmp`, which a reboot
  removed, so `make test-local` failed. `make venv` now rebuilds it from the lock file with a
  persistent Python 3.12. `make test-local` reports a broken environment clearly.

## Acceptance mapping (specification §16)

PASS means demonstrated today for this local, synthetic-only prototype. Research figures
are not re-derived here; they are the recorded outputs linked below.

| Criterion | Result | Evidence |
|---|---|---|
| F1 Boots from documented commands with PostgreSQL | PASS | Clean-boot run above; [README](../README.md) |
| F2 Demo accounts work; unauthorised operations fail server-side | PASS | [security tests](../services/api/tests/test_security_and_queue.py), [hardening](../services/api/tests/test_hardening.py); browser logins for each role |
| F3 Walk-in registration → triage → consultation → pharmacy → complete with timestamps | PASS | [workflow.spec.ts](../apps/web/tests/e2e/workflow.spec.ts); [completed journey](evidence/completed-journey.png) |
| F4 Concurrent patients, deterministic ordering, visible wait ages | PASS | [queue engine](../services/api/app/services/queue.py), [invariants](../services/api/tests/test_invariants.py); seeded consultation queue orders P2 → P3 (45, 31 min) → P4 → P5 |
| F5 View/accept/reject/override recommendation with audit | PASS | [ML tests](../services/api/tests/test_ml_and_baseline.py), [intelligence tests](../services/api/tests/test_intelligence.py) |
| F6 AI unavailable → manual workflow continues | PASS | Browser journey with no active model; no invented urgency |
| F7 Service-point outage keeps state | PASS | `test_outage_blocks_calls_without_removing_queue`; clinic browser test resumes a paused room |
| F8 Dashboards update without reload | PASS | Second-tab assertions in [workflow.spec.ts](../apps/web/tests/e2e/workflow.spec.ts); [live-stream report](evidence/live-streams.json) |
| F9 Token reveals only own status; not cheaply enumerable | PASS | Guessed-token browser test; [private status](evidence/patient-mobile.png) |
| F10 FCFS / urgency / hybrid in simulator only | PASS | [simulation tests](../services/api/tests/test_research.py); live queue never re-ranks across confirmed categories |
| R1 ≥ 300 reproducible synthetic visits | PASS | Browser setup generated 300 with seed 2026; repeated runs insert zero |
| R2 Baseline formulas | PASS | [baseline tests](../services/api/tests/test_ml_and_baseline.py), [definitions](RESEARCH_EVALUATION.md) |
| R3 Same scenarios per policy; reproducible exports with seeds | PASS | Paired runs with shared input hashes; [reproducibility](evidence/simulation-reproducibility.json) |
| R4 Mean, P90, low-urgency warnings; no blanket benefit claim | PASS | [standard run](evidence/simulation-standard.json); recorded hybrid − FCFS **+4.43 min** (interval crosses zero) and [no-improvement control](evidence/simulation-no-improvement.json) |
| R5 Label provenance and limitations | PASS | [model evaluation](evidence/model-evaluation.json); only synthetic labels; macro-F1 recorded against synthetic labels, not diagnostic accuracy |
| R6 Provenance, model/policy version, explanatory factors | PASS | Versioned model/policy/dataset hashes in exports and queue rows |
| E1 Unit, API/integration and E2E pass locally | PASS | 150 backend + 22 frontend + 14 browser, above |
| E2 No duplicate allocations from concurrency or repeats | PASS | [PostgreSQL race tests](../services/api/tests/test_postgres.py) (7/7), idempotency keys, stale versions |
| E3 Facility scoping, token leakage, RBAC, audit integrity tested | PASS | Cross-facility, role and immutable-audit tests; clinic snapshot hides names from researchers |
| E4 No PHI/secrets committed; `.env.example` placeholders | PASS | Repository scan finds no `.env`, keys or credentials; all people fictional |
| E5 Error/loading/empty/offline flows | PASS | Browser invalid-login, guessed-token, offline/reconnect assertions |
| E6 Seed/reset, backup/restore, README on a clean machine | PASS on fresh Docker volumes | Clean-boot run above; separate physical machine not claimed |
| E7 OpenAPI generated; frontend types match | PASS | Drift check above; TypeScript check |
| E8 Working demo script/screenshots with completed timeline | PASS | [Clinic walkthrough](CLINIC_DEMO.md), [demo script](DEMO_SCRIPT.md), screenshots in [evidence/](evidence/) |

## Outside the software

These remain outside the software, as the [Evaluation view](../apps/web/src/components/Evaluation.tsx) also states:
fieldwork baseline at a real facility, ethics and facility approval, recruited usability
participants, independent clinician labels, and any clinical validation of the advisory.

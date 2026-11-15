# Verification evidence

Verified locally on 25 October 2026 with Python 3.12, Node 22.23.4, PostgreSQL 17.2 and Google Chrome. This is software verification using synthetic data, **not clinical validation or approval for patient care**.

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Backend unit/API/research/privacy suite including real PostgreSQL | PASS: 52 tests both on host and in Docker | [JUnit](evidence/pytest.xml); [tests](../services/api/tests/) |
| Additional upgrade → downgrade → upgrade on an isolated PostgreSQL schema | PASS: all 3 PostgreSQL tests | `tests/test_postgres.py` |
| Frontend unit tests | PASS: 7 tests on host and in dedicated Docker test image | `npm test`; retry keys, offline blocking, roles, timestamp display |
| Generated API types and TypeScript | PASS | `npm run typecheck`; [OpenAPI](API_OPENAPI.json), `src/lib/generated.ts` |
| Optimised frontend build | PASS | `npm run build` |
| Real browser workflows against the complete Docker stack | PASS: 4 tests, 25.4 seconds | [browser tests](../apps/web/tests/e2e/workflow.spec.ts) |
| Python dependency audit | PASS: no known vulnerabilities reported | [Audit](evidence/python-dependency-audit.json) |
| npm dependency audit including development tools | PASS: zero reported vulnerabilities | `npm audit --audit-level=low` |
| Schema drift | PASS: no new upgrade operations detected | `alembic check` against migrated PostgreSQL |
| Synthetic generator | PASS: 300 inserted; repeat inserted 0 | `app.cli synthetic --count 300 --seed 2026` |
| Durable-worker simulation and reproducibility | PASS | [Reproducibility](evidence/simulation-reproducibility.json) |
| Backup/restore into a disposable database | PASS: counts and integrity digests match; temporary database removed | [Restore report](evidence/backup-restore.json) |
| Complete updated Docker Compose rebuild and integrated startup | PASS: API/database healthy; web/worker running; migrations completed | `docker compose build api worker migrate web`; `docker compose up -d --no-build --wait` |
| Fresh-volume boot, reset and actual backup/restore commands | PASS: two fresh boots, private dataset hashes match after restore | [Clean-boot report](evidence/clean-boot-reset.json); [verification script](../scripts/verify_clean_boot.py) |
| Concurrent live dashboards | PASS: 20 SSE streams held open while health and authenticated reads continue | [Live-stream report](evidence/live-streams.json); [verification script](../scripts/verify_live_streams.py) |
| All six seeded demonstration accounts | PASS: HTTP 200 login for each | `app.seed.DEMO_USERS`, checked against running Docker API |

The recorded backend run has one upstream Starlette warning about future `httpx2` test-client migration. It is not a failed test. Dependency audits are point-in-time checks, not penetration tests or container-OS audits.

## Demonstrated workflows

- Reception creates a patient and visit, receives a private token and completes registration.
- An already-open clinician tab observes the new visit without reload. Clinician confirms P2 while AI is unavailable, records a pin with a reason, calls, starts and completes consultation, and routes to pharmacy.
- A separately authenticated pharmacist completes the final stage. The patient's mobile status page updates automatically and reveals neither identity nor urgency. All four episode timestamps remain in the completed timeline.
- Offline clinical controls are disabled; reconnect requires a successful refresh. Failed authentication and guessed tokens show explicit errors.
- A researcher runs a real durable simulation job and trains an actual selected dataset. The resulting model is experimental and **inactive**; the UI shows its confusion matrix and limitations.
- Tests exercise actual synthetic-model inference and clinician ACCEPT, REJECT and OVERRIDE. Neither inference nor standalone review applies an authoritative urgency; only explicit triage confirmation does. A mismatched ACCEPT is rejected.
- API regressions cover clinician-only authority, object/facility scoping, CSRF, session revocation, rate limiting, duplicate commands, stale versions, escalation resolution, pauses, timestamp corrections, outages and concurrent calls.
- PostgreSQL blocks update/delete of append-only audit history and alteration of completed episodes. SSE excludes stored clinical payloads, respects role/facility boundaries, resumes beyond a 100-event same-timestamp page and stops after session revocation.

## Actual research outputs

The default synthetic simulation used 300 patients × 10 paired replications, seed 2026. Hybrid minus FCFS mean total outpatient waiting time was **+4.4319 minutes** (95% paired interval **−2.9026 to +11.7665**). This run did **not** demonstrate an improvement. The same-category control produced exactly zero difference; zero consultation capacity left all 300 patients unserved per replication.

The included trained model's holdout macro F1 is **0.4046 against synthetic labels**. This is not diagnostic accuracy, clinical under-triage performance, or evidence of real-world benefit. See [model evaluation](evidence/model-evaluation.json), [simulation report](evidence/simulation-standard.json), [CSV](evidence/simulation-standard.csv), [SVG](evidence/simulation-standard.svg), and [synthetic flow metrics](evidence/analytics-synthetic.json).

## Acceptance mapping (specification §16)

PASS below means demonstrated for this local, synthetic-only research prototype. It is not clinical approval or an internet-production readiness assertion. Clean-start verification used newly created Compose networks/volumes and rebuilt images on this machine, not a separately provisioned physical machine. No Git repository was supplied in the workspace, so no remote clone or hosted CI run is claimed.

| Criterion | Result and implementation/evidence |
|---|---|
| F1: documented PostgreSQL startup | PASS — fresh volumes, migrations, restricted role, web shell; clean-boot report above |
| F2: accounts and server-side role enforcement | PASS — six real account logins; [security tests](../services/api/tests/test_security_and_queue.py), [workflow tests](../services/api/tests/test_workflow.py) |
| F3: complete walk-in with timestamps | PASS — real browser workflow and [completed timeline](evidence/completed-journey.png) |
| F4: concurrent queues, deterministic order, wait ages | PASS — [queue engine](../services/api/app/services/queue.py), ordering/pin tests in [invariants](../services/api/tests/test_invariants.py) |
| F5: explainable recommendation, clinician decisions and audit | PASS — real inference with all three decisions in [ML tests](../services/api/tests/test_ml_and_baseline.py); audit assertions |
| F6: AI-unavailable manual fallback | PASS — complete browser journey uses the disabled model; no invented urgency |
| F7: outage without losing queue state | PASS — `test_outage_blocks_calls_without_removing_queue` |
| F8: live dashboards | PASS — already-open second browser tab; role-filtered SSE and 20-stream connection check |
| F9: private, non-enumerable status | PASS — [mobile screenshot](evidence/patient-mobile.png), minimal-response/guess/rate-limit tests; private token never in URL |
| F10: FCFS/urgency/hybrid comparators | PASS — [simulation tests](../services/api/tests/test_research.py), paired exported reports; only confirmed/synthetic input labels |
| R1: reproducible 300 synthetic visits | PASS — initial 300 insertions, repeated seed inserts zero; [generator](../services/api/app/cli.py) |
| R2: baseline timing formulas | PASS — exact timestamp fixtures in [baseline tests](../services/api/tests/test_ml_and_baseline.py); [definitions](RESEARCH_EVALUATION.md) |
| R3: identical scenarios and reproducible exports | PASS — shared input hashes, seeds, repeated worker runs, CSV/JSON/SVG |
| R4: mean/P90 and low-urgency long waits, no promised benefit | PASS — [actual report](evidence/simulation-standard.json), zero-benefit and zero-capacity controls |
| R5: explicit label provenance and limitations | PASS — only SYNTHETIC accepted; genuine/proxy labels not represented as available or validated; [model report](evidence/model-evaluation.json) |
| R6: model/policy/data provenance and factors | PASS — versioned runtime/dataset identity, exact logit contribution checks, exported policy/input hashes |
| E1: unit/API/E2E suites | PASS — 52 backend, 7 frontend unit, 4 real browser tests |
| E2: no duplicate service allocation/commands | PASS — [real PostgreSQL races](../services/api/tests/test_postgres.py), idempotency and stale-version tests |
| E3: facility, token, RBAC and audit boundaries | PASS — cross-facility tests, restricted-role database triggers, scoped-event tests |
| E4: no production data/secrets in deliverable | PASS for supplied source — synthetic fixtures, ignored `.env`/artifacts/backups; [.env.example](../.env.example) contains placeholders |
| E5: visible error/loading/empty/offline states | PASS — [workflow UI](../apps/web/src/components/Workflows.tsx), browser failure/offline/reconnect assertions |
| E6: seed/reset/backup/restore and setup | PASS in fresh Docker volumes — actual scripts restore two visits and matching private dataset hashes; main DB restore verified separately without replacing it |
| E7: OpenAPI and frontend types | PASS — [OpenAPI](API_OPENAPI.json), 40 generated schemas, TypeScript check |
| E8: working demonstration evidence | PASS — [demo script](DEMO_SCRIPT.md), five browser screenshots, completed journey |

## Reproduction commands and recorded output

From the repository root, with the documented `.env` and running stack:

```text
docker compose build api worker migrate web
docker compose up -d --no-build --wait --wait-timeout 90
docker compose run --rm --no-deps -e TEST_POSTGRES_URL=<local-owner-test-URI> api pytest -q
  52 passed, 1 warning in 41.32s
make test-web
  Test Files 2 passed; Tests 7 passed
npm --prefix apps/web run test:e2e
  4 passed (25.4s)
python scripts/verify_clean_boot.py
  PASS: fresh boot cycle 1 ...
  PASS: fresh boot cycle 2 ...
  PASS: actual backup/restore commands; two visits and private dataset hashes restored
python scripts/verify_live_streams.py
  PASS: 20 simultaneous idle SSE streams; database-backed health remains responsive
python scripts/verify_backup_restore.py
  PASS: restored counts and integrity digests match; disposable database removed
```

Use the locked Python environment for scripts and the README's Node version for browser tests. The owner test URI is **only for isolated PostgreSQL test schemas**, never the normal API runtime. The separately recorded host JUnit run passed the same 52 tests in 38.70 seconds. The Docker browser run was repeated after repairing an SSE event-loop/pool starvation defect; earlier failing runs are not represented as passing. The dedicated Docker test entrypoint was also repaired with an explicit pytest import path.

## Deliberate limits

The core local research-prototype acceptance above is verified. Deployment is loopback-only Docker, not a public hosted service. The optional extensions and clinical/governance approvals below are not claimed complete.

Operational historic utilisation is unavailable rather than inferred from present capacity. Neutral P1–P5 labels are fixed; no local clinical protocol is claimed. Operating hours are informational. The optional FHIR adapter is not implemented. Only synthetic uploads are allowed. True offline editing, distributed rate limiting, public hosting, TLS termination, encrypted backups, clinical validation and real-data approval are outside this demonstrated local build. See [decisions](DECISIONS.md).

The primary specification's broader qualitative criteria are supported by the listed evidence, not by a fabricated percentage-complete score. Browser tests do not exhaustively exercise every administrator form or every possible research configuration. The GitHub Actions workflow is supplied but has not been executed remotely.

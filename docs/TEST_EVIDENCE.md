# Verification evidence

Historical 26 October report. See [28 October research-depth verification](RESEARCH_DEPTH_EVIDENCE.md) for the current 105-test backend, expanded browser/frontend suites and research results. Shared `docs/evidence` exports are refreshed by verification scripts; their own timestamps identify the latest run.

Verified locally on **26 October 2026** with Python 3.12, Node 22.23.4, PostgreSQL 17.2 and Google Chrome. These results verify a synthetic research prototype, **not clinical validity, patient-care approval or public-production readiness**.

## Executed checks

| Check | Result | Evidence |
|---|---|---|
| Backend API/security/research suite, including real PostgreSQL | **67 passed** on host (56.22 s) and in Docker (63.90 s) | [JUnit](evidence/pytest-enhanced.xml), [tests](../services/api/tests/) |
| PostgreSQL-specific checks | **5 passed**, included above | Concurrent calls and room approvals, active-reservation uniqueness, immutable records, migration round-trip and model/schema parity |
| Frontend unit tests | **10 passed** on host and in the dedicated Docker test image | Safe command client, permissions, dialog submission/cancel/Escape/focus |
| Full-stack browser workflows | **6 passed**, 58.4 s | [Machine-readable summary](evidence/browser-enhanced.json), [browser tests](../apps/web/tests/e2e/), local HTML report in `apps/web/playwright-report/index.html` |
| TypeScript and optimised Next.js build | PASS | `npm run typecheck`; Docker production build |
| Generated API contracts | PASS: **76 schemas** | [OpenAPI](API_OPENAPI.json), generated browser types; structured tuple support |
| Migration and schema drift | PASS: revision `20261025_0003`; no new upgrade operations detected | `alembic check`; isolated upgrade → downgrade → upgrade test |
| Main Docker deployment | PASS: database/API healthy, web/worker running, migration completed | Loopback web :3000, API :8000, database :55432 |
| Fresh-volume boot and actual restore commands | PASS: two fresh boots, reset of only disposable volumes, matching restored private dataset hashes | [Clean-boot report](evidence/clean-boot-reset.json) |
| Repeated busy-clinic worker experiments | PASS: complete results and traces exactly equal across two runs | [Reproducibility report](evidence/enhancement-demo.json), [JSON](evidence/busy-clinic.json), [CSV](evidence/busy-clinic.csv), [SVG](evidence/busy-clinic.svg) |
| Operational model training and evaluation | PASS: real durable worker, private artifact, temporal holdout and baseline comparison | [Evaluation](evidence/operational-prediction.json) |
| Backup/restore | PASS: counts and digests match after restore into a disposable database, including new research/workspace tables | [Restore report](evidence/backup-restore.json) |
| Live connections | PASS: 20 simultaneous SSE streams with responsive database-backed reads | [Live-stream report](evidence/live-streams.json) |

The final browser run used a uniquely named disposable Compose project, its own PostgreSQL/model volumes, 300 generated histories and the real durable worker. The test project and volumes were removed after verification; the main demonstration was preserved. Earlier attempts exposed ambiguous daily-token test targeting and exact-label selectors; these were corrected and the complete suite rerun. Two visits created by the interrupted checks in the main demo were explicitly cancelled with audit reasons, retaining their history. No pre-existing visit was cancelled.

The backend run retains one upstream Starlette warning about a future `httpx2` test-client migration; it is not a failed test. Dependency versions were not changed by this enhancement. Point-in-time dependency audit results from 25 October are retained in the [earlier verification record](TEST_EVIDENCE_20261025.md); no new penetration test or container-OS audit is claimed.

## Connected workflows demonstrated

- Reception → clinician assessment → consultation → pharmacy → completed visit, with private mobile status, second-tab updates, clinician override and offline/reconnect safeguards.
- Patient search, append-only observations with units, encounter note, handover to laboratory, acknowledgement, staffed-room approval, laboratory completion, **return consultation as a new episode**, and a follow-up encounter retaining earlier history.
- Reception is denied clinical workspace details. Pharmacy/providers are restricted to their service operations. Cross-facility objects remain hidden.
- Explicit room/staff reservations reject stale resource snapshots, overlapping shifts, duplicate approvals and conflicting database inserts. A new outage blocks a not-yet-started reservation but does not interrupt service already started. No-shows and completion release reservations.
- Researchers save immutable scenario revisions, execute a 50-arrival/3-room experiment, inspect sensitivity, urgency slices and staged comparator ablations, replay individual journeys, and retrieve real exports.
- Real training jobs produce an inactive experimental urgency classifier and a separate operational duration model. Neither inference nor resource choice changes clinician-confirmed priority.
- Worker failure/recovery, invalid observation inputs, insufficient prediction data, forecast arithmetic, finite-horizon censoring, repeated-run determinism and distinct resource-choice strategies have automated coverage.

Screenshots: [patient workspace](evidence/patient-workspace.png), [staffed-room assignment](evidence/staffed-room-assignment.png), [busy-clinic results](evidence/busy-clinic-experiment.png), [operational evaluation](evidence/operational-prediction.png), [completed journey](evidence/completed-journey.png), [private mobile status](evidence/patient-mobile.png).

## Actual research outputs

The saved busy-clinic preset uses 50 synthetic arrivals, 3 rooms, 5 paired replications, explicit shifts, breaks/outages, no-shows and laboratory returns. Room duration multipliers are deliberately not in room-number order: 1.5, 0.7, 1.0. The full configuration and shared input hashes are exported.

| Base-demand policy | Mean completed-journey wait (min) | Mean replication P90 (min) | Completed per run | Unserved per run |
|---|---:|---:|---:|---:|
| Fixed room | 94.2010 | 180.7688 | 48.4 | 1.6 |
| Next available | 76.6611 | 126.8764 | 48.4 | 1.6 |
| Capacity aware | 76.5231 | 127.4031 | 48.4 | 1.6 |

Capacity aware minus fixed room: **−17.6779 minutes**, paired 95% interval **−26.3588 to −8.9970**. This is conditional on synthetic assumptions, not evidence of real clinical benefit or validation of the live room-history heuristic. Capacity aware was only about 0.14 minutes better in mean than next available, and its P90 was slightly **worse**. Completed-only means can be selection-biased; unserved counts and urgency slices remain visible. Ablations are staged policy comparators, not a full factorial causal study: capacity aware → next available removes resource-aware choice; next available → fixed room removes pooling/routing flexibility.

The operational duration pipeline selected the **stage-median baseline**, not gradient boosting. Untouched temporal test MAE: **2.9825 minutes**; interval coverage: **78.75%** against a nominal 80%; mean interval width: **9.4810 minutes**. There were 709 training, 229 calibration and 240 test rows from 300 synthetic visit groups after outcome-availability purging. This is not evidence of model superiority or a patient-specific guarantee.

The original FCFS/urgency/hybrid comparison is retained: its previously verified hybrid-minus-FCFS result was **+4.4319 minutes**, with an interval crossing zero. The new resource experiment does not overwrite that adverse result. The urgency classifier's previously recorded macro F1 against synthetic labels was **0.4046**, not diagnostic accuracy.

## Acceptance mapping

The original specification remains the primary contract. The existing acceptance coverage is retained by the expanded regression suite; see the [earlier detailed F/R/E mapping](TEST_EVIDENCE_20261025.md#acceptance-mapping-specification-16).

| Scope | Current verification |
|---|---|
| F1–F3: PostgreSQL startup, roles, complete patient workflow | Full-stack clean instance, real accounts, recorded episodes and follow-up history |
| F4–F7: queues, clinician authority, AI fallback, outages | Queue regressions plus reservation races, non-preemptive outages and unchanged-priority assertions |
| F8–F9: live views and private status | Multi-context browser workflow, offline controls, 20-stream test, token/privacy tests |
| F10 / R1–R4: simulation, reproducibility, timing, adverse results | Original policies retained; distinct resource comparators, identical worker reruns, finite-day losses and exports |
| R5–R6: provenance, evaluation, explanations | Synthetic-label boundaries, temporal operational evaluation, baseline selection, version/config/input hashes |
| E1–E3: tests, concurrency, security/audit | 67 backend + 10 frontend + 6 browser tests; PostgreSQL constraints and role-scoped APIs |
| E4–E6: synthetic delivery, error states and recovery | Local-only stack, explicit fallbacks, preserved records, isolated backups and browser fixtures |
| E7–E8: API types and working demonstration | 76 generated schemas, successful build, [enhanced demo guide](ENHANCED_DEMO.md), saved runs and screenshots |

## Reproduce

From the workspace root, with the documented local configuration:

```bash
docker compose build api worker migrate web
docker compose up -d --no-build --wait --wait-timeout 90
# Supply your local owner test URI only to the isolated test process:
docker compose run --rm --no-deps -e TEST_POSTGRES_URL=YOUR_LOCAL_TEST_URI api pytest -q
make test-web
make contracts
python scripts/verify_browser.py
python scripts/verify_enhanced_demo.py
python scripts/verify_backup_restore.py
python scripts/verify_live_streams.py
python scripts/verify_clean_boot.py
```

Use the locked Python environment and documented Node version. Browser verification needs free loopback ports 3100/8100 and Chrome (or installed Chromium plus `PLAYWRIGHT_CHANNEL=chromium`). `verify_enhanced_demo.py` deliberately **adds** saved synthetic scenario/run records and trains the operational predictor in the main demo; it does not alter patient priorities or staffing. No Git repository or remote CI execution was supplied, so no commit, clone or hosted CI run is claimed.

## Boundaries

All six enhancement areas in [the implementation plan](ENHANCEMENT_PLAN.md) are connected and exercised for the local research prototype. This does not complete field research: approved real-world observations/interviews, clinical validation, protocol adoption and ethics/governance approval remain future work. The 50-arrival experiment is simulated, not 50 observed clinical cases.

Other limits remain explicit: neutral fixed P1–P5 labels, no vital-sign thresholds or autonomous decisions, recorded rather than verified attendance, non-causal room-history suggestions, approximate public waiting ranges, synthetic-only uploads, no offline clinical edits, no FHIR/EHR integration, no public hosting/TLS service, process-local rate limits and unencrypted local backups. Browser tests exercise representative workflows, not every administrator form or every scenario combination. See [engineering decisions](DECISIONS.md).

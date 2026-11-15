# Research-depth verification — 28 October 2026

The enhanced prototype is running locally with a real PostgreSQL database, durable worker and production-built web application. All results below are **synthetic software evidence**, not clinical effectiveness, a recruited clinician study or an academic grade guarantee. The original build contract remains [the specification](../smart_healthcare_queue_ai_agent_build_spec.md); the [26 October evidence](TEST_EVIDENCE.md) records the preceding extension.

## Executed checks

| Check | Observed result | Evidence |
|---|---|---|
| Backend/security/research suite | **105 passed, 0 skipped**, 78.41 seconds | [JUnit](evidence/pytest-research-depth.xml) |
| Real PostgreSQL checks (included above) | **6 passed** | Concurrent queue/room/trial commands, unique active trials, completed-evidence immutability, migration upgrade/downgrade and metadata parity in disposable schemas |
| Frontend unit tests | **16 passed** | [Machine-readable report](evidence/frontend-research-depth.json); safe API, permissions, dialogs, workbench consent/shadow/error flows and delayed service-response regression |
| Full-stack browser suite | **8 passed, 0 skipped, 0 flaky**, 89.12 seconds | [Summary](evidence/browser-enhanced.json), [tests](../apps/web/tests/e2e/), local HTML report `apps/web/playwright-report/index.html` |
| TypeScript / production build | PASS | `npm --prefix apps/web run typecheck`; both isolated and main Docker web builds succeeded |
| API contracts | **92 generated schemas**, stored OpenAPI equals running API | [OpenAPI](API_OPENAPI.json), [generated types](../apps/web/src/lib/generated.ts), imported workbench envelopes |
| Migrations / running demonstration | PASS: `20261026_0004 (head)`; API health and web HTTP 200 | [Migration](../services/api/migrations/versions/20261026_0004_research_depth.py), localhost ports 8000/3000 |
| Persisted research reproducibility | Two completed worker runs; complete numerical results/traces identical | [Summary](evidence/research-depth-demo.json), [JSON](evidence/operations-research.json), [CSV](evidence/operations-research.csv), [frozen protocol](evidence/research-protocol.json) |
| Logical database restore | Counts and integrity digests match, including research protocols/cases/runs | [Restore evidence](evidence/backup-restore.json); main data preserved |
| Two clean-boot/reset cycles and actual restore commands | PASS; private dataset hashes restored | [Clean-boot evidence](evidence/clean-boot-reset.json); only owned temporary projects removed |
| Concurrent live updates | 20 SSE streams held open; authenticated reads and health remain responsive | [Stream evidence](evidence/live-streams.json); sampled health responses 0.0096–0.0385 seconds |

Python 3.12 in Docker, PostgreSQL 17.2, Node 22.23.4, Next.js 16.4.3 and Chrome were used. The host's earlier `.venv` referenced a removed interpreter, so Python application tests used Docker; standard-library orchestration used host Python 3.14.4. Pytest emitted one upstream Starlette/httpx deprecation warning. No test failures are suppressed.

Browser verification first exposed exact-label ambiguity in wrapped dropdowns, excessive automated login frequency, and an older Staff & rooms response race. Explicit accessible names, rate-limit-aware test login and service-bound response handling fixed them. A deferred-response unit test proves that an old queue cannot overwrite the selected service. The final browser run uses fresh PostgreSQL and artifact volumes and preserves the main demonstration.

## Feature acceptance mapping

| Enhancement | Working verification |
|---|---|
| Frozen protocols / provenance | Real protocol form and API, dataset hash validation, fixed model/configuration/case identity, database immutability, generated contracts |
| Blinded references / consensus | Separate clinician and triage browser sessions submit independent labels, then original-reviewer consensus; reference-case reuse rejected for participant trials |
| Calibration / selective advice | Five chronological partitions, ordinal comparator, raw/calibrated scores, threshold-selection utility, risk–coverage and bootstrap/Wilson uncertainty tested |
| Explainability / robustness | Exact contribution reconstruction, contrastive calculations, withheld class-identifying output on abstention, learning/stress/stability diagnostics and delayed-label monitoring challenge |
| Consented human-factors infrastructure | Manual/advisory/explanation assignment, consent requirement, owner checks, concurrent start/complete, immutable responses; shadow API hides output until independent save |
| Direct waiting-time study | Arrival-time feature boundary, outcome-availability purging, independent calibration/test days, baseline losses and interval coverage retained |
| Forecast-informed planning | Equal paid budgets, independent planning/evaluation streams, fixed/pooling/historical comparators, paired base/load/outage outcomes, finite-horizon and constraint tests |
| Database/worker/UI integration | Durable job success/failure, frozen hash binding, repeated actual worker runs, results polling, sensitivity selection, JSON/CSV exports and private aggregate access |
| Existing patient-management workflows | Complete registered visit, clinician triage/override, pharmacy closure, private mobile status, offline controls, longitudinal notes/handover/lab return and staffed assignment all rerun |

## Actual synthetic results and interpretation

Default study: seed 2026, 40 development days, 12 held-out days, 50 nominal arrivals/day, ten paired planning replications, shift strength 1, missing-rate setting 0. The full machine-readable exports contain actual generated sample counts, missingness/stress settings, software identity, hashes and all outcome denominators. The smaller browser fixture deliberately uses 28/4 days and two replications to verify interaction mechanics; its screenshots are **not** the default study's numerical results.

| Outcome | Recorded result | Interpretation |
|---|---|---|
| Advisory macro-F1 | 0.3717 on 200 final synthetic cases | Limited agreement with generator labels, not clinical accuracy |
| Raw → calibrated log loss | 1.32624 → 1.32282 | Small change; paired row-bootstrap difference interval **[−0.02364, +0.01097]** spans zero |
| Selected advisory threshold | 0.75; **11/200 offered suggestions (5.5%)** | Most cases require independent assessment; this is not broad model usefulness |
| Errors among offered suggestions | 0/11; Wilson 95% error interval **[0%, 25.88%]** | Zero observed errors cannot establish safety or perfect performance |
| Direct-wait MAE | **15.50 min**, workload baseline **17.84 min**, 683 started cases | Held-out consultation cohort: 791 arrivals, including 108 unstarted/unserved cases excluded from prediction-error metrics |
| Waiting interval | Nominal 80%; measured **81.11%** coverage, mean width **24.01 min** | Marginal observed coverage, not an individual or temporal-drift guarantee |
| Arrival forecast hourly MAE | Learned **2.57**, historical **3.10** arrivals/hour | Better forecast error alone does not prove improved operational outcomes |
| Learned − historical planning, base | **−4.10 min**, paired 95% CI **[−8.67, +0.48]** | No clear base-scenario improvement; achieved half-width 4.58 minutes |
| Same comparison, low load | **+2.33 min**, CI **[−1.32, +5.97]** | Point estimate worsens; retain the adverse/no-clear-benefit result |
| Same comparison, high load | **−10.44 min**, CI **[−20.08, −0.79]** | Scenario-specific synthetic result; not a clinic-effect estimate |
| Same comparison, room outage | **−6.68 min**, CI **[−12.65, −0.71]** | Availability depends on schedule/outage overlap despite equal paid budgets |

Planning comparisons use all-arrival finite-horizon accumulated waiting in a consultation-only model. Four policies each have 1,080 paid staff-minutes; all reported constraints passed. These scenario intervals are exploratory and unadjusted for multiple comparisons. The original whole-journey Objective 4 outcome and its previous no-clear-benefit result remain separate and unchanged. The universal 30-minute start clearance and bounded synthetic durations are substantial modelling assumptions, not recommendations for actual care.

The offline monitoring challenge observed 0/40 input false-alarm windows and 0/35 released-error false-alarm windows in the unchanged scenario. Missing-input shifts were detected by the input guard in 5/5 replications. Label shift was detected by the delayed-error monitor in only **1/5**, and by the input guard in **0/5**. Missing detections remain null, not zero-delay successes. Five replicated, resampled synthetic sequences do not validate the detector or establish its false-alarm rate in clinical use. [Complete advisory/monitoring results](evidence/advisory-reliability.json).

## Demonstration artifacts and preservation

- [Operations study screenshot](evidence/research-operations-study.png)
- [Calibration and selective-prediction screenshot](evidence/research-calibration.png)
- [Completed shadow exercise screenshot](evidence/research-shadow-workflow.png)
- [Full demonstration instructions](RESEARCH_DEPTH_DEMO.md)

The shadow screenshot shows an explicitly automated fixture **after** the independent answer was committed. A completed shadow task may reveal the raw model/explanation for research inspection; it was not available to inform that answer. Before-decision advisory displays suppress class-identifying output on abstention.

The main verification added one protocol, 24 cases, two runs and an experimental model; it issued zero patient/schedule commands and zero model-lifecycle commands. It created **no participant responses**. Restore evidence includes 316 patients, 317 visits, 24 research cases and two research runs; the main trial/reference tables remain empty. Main backup `backups/demo-JeD5WszD` was taken before applying migration 0004. Backups are permission-restricted local archives, not encrypted disaster-recovery certification.

## Remaining research boundaries

Local immutable protocols are not external preregistration. Synthetic proxies/consensus are not clinical ground truth. The software has not recruited the proposal's staff sample or observed its planned baseline cohort. It supplies the infrastructure for approved controlled research, not completed fieldwork. Independent external validation, meaningful clinical features/references, ethical/facility authorisation, a prospective analysis/sample-size plan and human-study interpretation remain necessary for any clinical or academic empirical claims.

The Sites local-preview workflow informed real-browser evidence, and PostgreSQL guidance informed short command transactions and partial uniqueness constraints. Neither workflow published a hosted site or provisioned an external database. See [architecture](ARCHITECTURE.md), [model/analysis cards](RESEARCH_EVALUATION.md) and ADR-022–026 in [decisions](DECISIONS.md).

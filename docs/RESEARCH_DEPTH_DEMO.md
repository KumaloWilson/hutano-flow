# Research workbench demonstration

Updated 28 October 2026. This is a synthetic research exercise, not patient-care validation, ethics approval or a recruited human study. Use the existing [setup and demonstration accounts](../README.md). Open <http://localhost:3000>; API documentation is at <http://localhost:8000/docs>.

## Inspect the saved demonstration

Sign in as `research@demo.hutano.test` / `DemoResearch1!`, open **Research workbench**, and choose the saved reproducibility protocol. The standard demonstration has two completed operational runs with identical results and a fixed configuration hash. Expand the model diagnostics to inspect the newly trained experimental model. It remains inactive; manual operations work without activating it.

Saved artifacts: [protocol/export](evidence/research-protocol.json), [operations JSON](evidence/operations-research.json), [operations CSV](evidence/operations-research.csv), [advisory evaluation](evidence/advisory-reliability.json), [verification summary](evidence/research-depth-demo.json). These contain computed synthetic results. The summary records actual protocol/run IDs. The verifier added no participant responses to the main demonstration.

## Create and evaluate an immutable protocol

1. As researcher, open **Research workbench**. Inspect source quality and feature definitions. `recorded_measurement` is dimensionless synthetic input, not a vital sign.
2. Enter a name/question, select the synthetic dataset and choose **Manual-only independent assessment** with no model. Standard settings: 40 development days, 12 test days, 50 mean arrivals/day, 10 replications, seed 2026. Record any different hypothesis/configuration before evaluating it.
3. Save the protocol and inspect its hash/frozen settings. Changes require a new protocol.
4. Click **Run saved operations study**. A database job runs in the worker; navigation does not erase it. Status and failures are retained.
5. Inspect **Direct waiting-time prediction**: held-out MAE versus workload baseline, observed interval coverage/width, cohort counts and stress slices.
6. Inspect **Equal-budget resource planning**: fixed, pooled, historical-planning and learned-planning outcomes. Switch base/low/high/outage scenarios. Compare paid/available minutes, unserved arrivals and paired intervals. A negative mean alone is inconclusive if its interval spans zero.
7. Download JSON/CSV. Repeat the saved study: run IDs/timestamps differ, while seeded numerical results and replay match. Results never apply a live schedule or urgency decision.

This supporting study models consultation only. Its bounded 1–30-minute synthetic service and universal 30-minute clearance before breaks/end are artificial capacity assumptions. Present the original **Simulation lab** FCFS/urgency/hybrid whole-journey comparison separately as Objective 4's primary analysis.

## Advisory diagnostics and a synthetic participant exercise

1. As researcher, use **AI research** to train a model and wait for the durable job. Training creates an **EXPERIMENTAL**, inactive artifact. Older versions remain in the registry; inspect the new v4 metrics without silently mixing incompatible partitions.
2. In **Research workbench**, expand **Calibration, selective prediction & model diagnostics** and select that model. Inspect partition counts, raw/calibrated losses, risk–coverage, uncertainty, ordinal comparator, learning/stress/explanation diagnostics and monitoring false alarms/misses.
3. If an authorised clinical reviewer elects to review it for this **synthetic demonstration**, use **Help & safety → Clinician research review** as clinician and record that limited purpose. Review is not clinical validation. Administrator activation is not needed for workbench tasks.
4. As researcher, create a **new** protocol selecting the reviewed model and matching dataset. Choose counterbalanced manual/advisory/explanation or shadow. Case snapshots and model identity are frozen. Do not revise an existing protocol after viewing its outcomes.

## Blinded references and independent responses

Use separate browser profiles for `clinician@demo.hutano.test` / `DemoClinician1!` and `triage@demo.hutano.test` / `DemoTriage1!`.

1. Each reviewer selects the same protocol/case under **Blinded synthetic-case review** and saves their own label/rationale. Neither sees the generator label or the other's label first.
2. After both reviews, either original reviewer can open **two-reviewer consensus** and record the agreed synthetic reference/rationale. This is not an independent third adjudicator. Leave unresolved disagreement unresolved.
3. For an approved participant exercise, record actual coded consent and explicit agreement. For software rehearsal, label the reference `SOFTWARE_REHEARSAL_NOT_RECRUITED`; never count it as recruited staff evidence.
4. Start an assigned trial. Predictor snapshots this person previously reviewed or trialled are excluded across protocols. Retrying resumes the active trial.
5. Manual receives no model output. Advisory shows a qualified suggestion if available; explanation also shows model factors. Shadow returns no model output through the API before submission. Before-decision advice hides the predicted class and class-identifying factors on abstention; a completed shadow task can reveal raw model output for retrospective research inspection.
6. Save the independent label, rationale, trust and authority-comprehension response. “No / unsure” is valid. Completed responses cannot be edited. Shadow output appears only after the save succeeds.
7. As researcher, inspect aggregate agreement, reference counts, arm summaries and monitoring. Exports omit consent references, individual text and participant IDs. Age groups below 30 are suppressed; fewer than ten shadow responses cannot support drift calculations.

Tasks never create patient visits, assign urgency, activate a model or revise staffing. Browser tests exercise consent/blinding with automated fixtures in a disposable database; they are not staff recruitment or usability-effect evidence.

## Repeat the verification

From the repository root with Docker running:

```bash
# Add only reproducible research records to the existing synthetic demo.
# Standard-library Python; no host ML virtualenv is needed.
python3 scripts/verify_research_depth.py

# Browser interactions in its own PostgreSQL/worker/web stack.
# Requires Node/npm and the Chrome used by Playwright.
python3 scripts/verify_browser.py

# Verify recovery without replacing main demonstration data.
python3 scripts/verify_backup_restore.py
python3 scripts/verify_clean_boot.py
```

The browser verifier uses uniquely named temporary projects on localhost ports 3100/8100 and removes only its own volumes. Login tests respect the real rate limit. If Chrome is unavailable, install Playwright Chromium and set `PLAYWRIGHT_CHANNEL=chromium` as in the README.

See [test results and limits](RESEARCH_DEPTH_EVIDENCE.md), [analysis/model cards](RESEARCH_EVALUATION.md) and [engineering decisions](DECISIONS.md). A dissertation still requires approved research, meaningful references, a predeclared analysis and critical discussion; software complexity cannot guarantee a grade.

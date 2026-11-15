# Research evaluation protocol

The included generator produces 300 synthetic walk-in journeys from a fixed seed. Simulation compares FCFS, urgency-first and hybrid policies using common random numbers: every policy receives the same arrivals, urgency labels, routes and service durations. Reported improvements or regressions therefore describe the simulated scenario only.

Primary outcome: **the sum of waiting minutes across each completed outpatient journey**, excluding service duration. Arrival-to-provider time is a separate supporting measure (consultation start minus arrival, including preceding service). Supporting outputs include mean, median, P90 and maximum stage waits, total visit time, throughput, utilisation and long-wait counts. A loss/no-improvement result is retained; reports are never filtered for favourable outcomes.

The demo classifier uses synthetic labels and is marked `EXPERIMENTAL`. Metrics are software pipeline evidence, not clinical validity. A real study requires ethics/facility approval, documented lawful basis, approved de-identification, a temporal holdout where possible, clinician-reviewed labels and a separate model/safety review.

## Reproducibility and estimands

The seeded 300-visit generator produces independent synthetic durations across 21 calendar dates. It is idempotent by seed/index and is **not observed fieldwork**. Running it again does not create another 300 visits. The separate training CSV generator supplies 1,000 labelled synthetic examples; it is not derived from a claimed clinical dataset.

SimPy generates a shared arrival/route/service/category sequence for each seed + replication index, then executes FCFS, urgency-first and within-category ageing against those same inputs. Differences and the Student-t 95% interval use paired replication means. P90 is pooled across eligible observations, not a confidence interval. Long-wait counts retain low-urgency outcomes. Unserved journeys are excluded from completed-journey means and reported separately; zero capacity therefore produces unavailable means, not a misleading zero wait. Busy time uses nominal configured capacity over the drained horizon, with non-preemptive outages, not measured staffing rosters.

The standard recorded run produced a +4.4319 minute hybrid-minus-FCFS difference; its interval spans zero. The all-P3 control produces no difference. Neither is evidence of an effect in a real clinic. See [actual outputs](TEST_EVIDENCE.md).

## Advisory model card (v4, 28 October 2026)

- Target: five neutral, synthetic P1–P5 proxy categories; lower number means higher urgency. The synthetic target formula is only a software test mechanism.
- Features: synthetic age band, visit type, arrival mode, hour and a dimensionless recorded measurement. No diagnoses, identifiers or external medical-model calls.
- Split: chronological 50/10/10/10/20 fit/model-selection/calibration/threshold-selection/final-test; equal timestamps stay together. Imputation, encoding and scaling fit only the first partition. Logistic C selection uses development macro-F1; three-fold fit-only CV is a diagnostic, not final performance. The legacy `train_rows` key counts all development rows; `estimator_fit_rows` counts actual estimator fitting rows.
- Primary estimator: logistic regression for exact additive logit explanations. Majority-class, random-forest and cumulative ordinal comparators remain visible regardless of performance. Service-duration regression remains a separate median-baseline comparison.
- Calibration: scalar temperature fitted by calibration-partition log loss; raw and calibrated reliability bins, log loss and Brier score are reported on the untouched final partition. A lower proper scoring-rule loss alone is not proof of improved calibration across all subgroups.
- Diagnostics: confusion matrix, per-class/macro F1, disagreement in each urgency direction **against synthetic labels**, learning curves on the model-selection partition, fixed-model bootstrap uncertainty, risk–coverage curves, missing/shift stress tests and local explanation stability. Age slices below 30 examples are suppressed.
- Abstention: missing, unseen and out-of-fit-range features trigger guards. The confidence threshold is selected on an independent later development partition using `(accepted errors + 0.35 × abstentions) / rows`. This cost and threshold are engineering assumptions, not approved clinical criteria. Class-identifying factors/probabilities are withheld when advice abstains. Wilson intervals prevent zero observed accepted errors being presented as certainty.
- Explanation: transformed-feature coefficient contributions, intercept, omitted-contribution sum, predicted-class logit and predicted-versus-runner-up contrast. Temperature rescales logits. These are exact fitted-model calculations, not biological or causal explanations.
- Lifecycle: experimental/inactive after training → clinician synthetic-demo review → administrator activation. Every suggestion remains separate from clinician confirmation. Disabled/missing inference leaves the manual workflow available.
- Provenance: source file hash, normalized training hash, seed, feature schema, pipeline revision and dependency versions. Artifacts are private server-created joblib files; uploaded executable artifacts are never accepted.

## Baseline and usability

The baseline importer supports source-to-standard column mapping, preview, chronology/duplicate checks and a retained aggregate provenance report. Use numeric journey numbers only. This build accepts synthetic CSVs only; an approved real-data import pathway is not implied.

The proposal's 300 completed journeys over three weeks and 8–12 staff interviews are **future approved fieldwork targets**, not achievements of the software demo. Guided tasks cover registration, patient finding, triage, calling, overriding, completing, token checking and analytics. Feedback stores consent references, completion, duration, errors and comments; aggregate task performance and descriptive trust ratings remain separate from queue outcomes. No SUS instrument or benchmark claim is made.

## Finite-day resource experiment extension

The new experiment is separate from the original drained-horizon queue-policy comparison. Immutable scenarios specify a finite day, room shifts, repeated breaks/outages, resource-duration factors, initial no-shows with a 70% return propensity, configurable return delay and laboratory-return visits. The default cohort is 50 arrivals across 3 rooms with 5 paired replications and demand multipliers 0.75/1/1.25. Synthetic categories are inputs, not model decisions.

Fixed-room, pooled next-available and pooled capacity-aware assignment share the same realised inputs within each replication. Capacity awareness selects among available rooms using a population service mean, never patient-specific duration or a changed urgency category. Non-speed-ordered room factors make the comparator mechanisms inspectably distinct. Outcomes may nevertheless coincide or worsen.

This report's P90 is the **mean of replication-specific P90s**, unlike the pooled P90 in the original simulator. Its primary mean includes completed journeys only; unfinished arrivals and not-yet-arrived patients are reported separately. Paired Student-t intervals compare replication means under identical scenarios, not different saved versions. Staged comparator ablations show removal of resource-aware choice and then pooling/routing flexibility; this is not a full factorial causal study. JSON exports retain the entire first-replication event replay for each policy.

## Operational duration model card

- Target: completed synthetic episode service minutes, excluding recorded pauses and applying append-only timestamp corrections.
- Inputs: service type, visit type, facility-local hour and weekday; no identifiers, observations or urgency features.
- Partitioning: chronological whole-visit 60/20/20 train/calibration/test, purging outcomes not available before the next partition starts. Visits cannot cross partitions.
- Candidate: quantile gradient boosting; comparator: training-stage median. Calibration MAE selects the estimator; the test set is untouched until evaluation. Residual calibration expands a nominal 80% marginal interval, without claiming individual or distribution-free time-drift guarantees.
- Reporting: measured test MAE, baseline MAE, interval coverage/width, sample counts, feature list and dataset/software version identity. Poor performance and baseline selection remain visible.
- Deployment: private artifact in the operational registry, used only for estimates. Missing/unseen/insufficient data yield explicit unavailability or historical fallback. It never modifies clinical priority. Public queue bounds also approximate residual workload and are not calibrated waiting-time guarantees.
- Demand: next-hour interpolation of rolling observed-day hourly means; walk-forward hourly MAE and constant-rate baseline; no-record days are unknown rather than invented zero-arrival days. Historical spread is descriptive, not a calibrated interval. Stale history is flagged.

Actual executed outputs, including baseline selection and an adverse P90 comparison, are retained in [verification evidence](TEST_EVIDENCE.md). Observed patient outcomes, deployment-effect estimates and real-world calibration remain future approved research.

## Research workbench protocol and analysis

See [the repeatable demonstration](RESEARCH_DEPTH_DEMO.md), [executed results](RESEARCH_DEPTH_EVIDENCE.md) and ADR-022–026. Protocol publication freezes source/feature/case hashes, model identity, design and operational configuration. It is local version control for a study, not external prospective registration. The present software/results have already been inspected; any future confirmatory analysis must predeclare its own hypothesis, outcomes, sample/precision target and analysis before collecting its evaluation cohort.

Independent references use two blinded reviewers and subsequent two-reviewer consensus. Labels remain synthetic-case judgements; the dimensionless input has no clinically validated meaning. Agreements and weighted kappa are descriptive (reviewer pairs can vary), not a ground-truth certificate. Counterbalanced manual/advisory/explanation arms and withheld shadow predictions record consent, elapsed time, trust and authority comprehension. Analyse future human responses with participant/case dependence and study order in mind; this build supplies descriptive summaries, not a powered causal effect model. Automated browser responses are excluded from any claim of staff recruitment.

The supporting direct-wait study uses arrival-time consultation queue snapshots, separate development fit/selection/calibration days and held-out days. It reports point MAE versus queue workload, nominal 80% absolute-residual interval coverage/width, load/outage/missingness slices, and unserved counts. It is distinct from the deployed service-duration predictor and public approximate waiting ranges; no calibrated public ETA claim follows.

The supporting planner compares fixed-room, pooled, historical-demand and learned-demand schedules with equal paid hours. Poisson count regression selects regularisation on later development days; planning samples and evaluation arrivals are separate. Frozen schedules face paired base/low/high/outage evaluation. Report all-arrival finite-horizon accumulated waiting, completed/unfinished counts, actual available minutes, uncertainty and achieved half-width. The artificial bounded-duration/30-minute start-clearance constraint must accompany every interpretation. These consultation-stage outcomes cannot substitute for the original whole-journey primary endpoint.

Offline monitoring reports false alarms, missed shifts and delay with one-window-delayed synthetic labels. Shadow monitoring uses independent pre-reveal human responses as comparison labels, not objective clinical outcomes. No monitoring signal changes a queue, model lifecycle or staffing plan.

## Methodological sources and reporting use

- [Guo et al., temperature scaling (2017)](https://proceedings.mlr.press/v70/guo17a.html) motivates a scalar calibration comparator; its neural-network experiments do not establish benefit for this synthetic logistic model.
- [scikit-learn probability calibration documentation](https://scikit-learn.org/stable/modules/calibration.html) informs independent calibration and probability diagnostics. Log loss/Brier scores combine several properties; inspect reliability and subgroup/sample limits too.
- [TRIPOD+AI (2024)](https://www.bmj.com/content/385/bmj-2023-078378) is a reporting reference: map data sources, predictors, partitioning, missingness, evaluation, uncertainty and limitations to this model card and exports. This project does not claim formal adherence or a clinically validated prediction model.
- [STRESS simulation reporting guidelines](https://repository.lboro.ac.uk/articles/journal_contribution/Strengthening_the_reporting_of_empirical_simulation_studies_Introducing_the_STRESS_guidelines/9503495) guide explicit system boundaries, assumptions, inputs, experimental design and reproducibility reporting. Frozen configurations, replay traces and paired intervals support this mapping, not automatic certification.
- [DECIDE-AI (2022)](https://www.nature.com/articles/s41591-022-01772-9) concerns early clinical evaluation. The current synthetic usability/shadow infrastructure does not constitute such an evaluation.

No external LLM, diagnostic classifier, autonomous triage or live clinical validation is introduced. Human study approval/recruitment, meaningful reference labels, independent external validation and a dissertation discussion remain research work beyond software verification.


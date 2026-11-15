# Research-depth implementation plan

Requested 26 October 2026. This extends the existing local synthetic prototype;
it does not authorise clinical deployment or real-data ingestion.

1. Freeze research protocols, feature definitions, dataset hashes and supporting
   experiment configuration. Preserve independent blinded labels and adjudication.
2. Separate classifier fitting, selection, probability calibration, abstention
   selection and final evaluation. Retain baselines and unfavourable outcomes.
3. Evaluate prediction-time waiting intervals on independent synthetic queue days;
   distinguish service-duration, consultation waiting and whole-journey outcomes.
4. Compare fixed/pooling/historical-planning/learned-planning under the same
   staff-hour budget, with held-out paired simulation inputs.
5. Provide counterbalanced synthetic explanation studies and withheld shadow
   predictions; log consent references, elapsed time and independent decisions.
6. Report robustness, drift, subgroup limitations, reproducibility and uncertainty.
7. Connect database/API/browser workflows, migrations, exports and durable jobs;
   verify in disposable environments and retain the main demonstration history.

Research protocol publication is immutable. New hypotheses/configurations require
a new protocol, not editing a completed result. Software tests and synthetic
study fixtures are never presented as clinician recruitment or fieldwork.

The original primary Objective 4 outcome (summed outpatient journey waiting) and
FCFS/urgency/hybrid experiment remain unchanged. Consultation-only prediction and
resource planning are separately labelled supporting analyses. Models never
modify clinician-confirmed urgency; resource-planning outputs never change live
staff schedules. No external LLM service is used.

Implemented and verified on 28 October 2026: database/API/worker/browser integration,
105 backend tests, 16 frontend tests, eight full-stack browser workflows, migration
round-trip, clean boot/recovery and reproducible persisted study runs passed.
See [executed evidence and research limitations](RESEARCH_DEPTH_EVIDENCE.md) and
[the working demonstration](RESEARCH_DEPTH_DEMO.md). This completes the software
enhancement scope; approved fieldwork and recruited human evaluation remain future
research, not an achievement inferred from automated fixtures.

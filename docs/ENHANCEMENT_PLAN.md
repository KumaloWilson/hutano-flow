# Connected prototype enhancement

Scope agreed 25 October 2026: deepen the existing research prototype end to end without replacing its clinician-authority, synthetic-only or local-deployment boundaries.

1. Patient workspace: repeat-visit history, structured observations, service notes, acknowledged handovers and structured workflow dialogs.
2. Resources: rooms, staff shifts, timed breaks/outages, auditable availability history and atomic approved reservations.
3. Operational decision support: compatible-room alternatives, snapshot-bound staff approval and protected clinician-confirmed queue order. Duration predictions never determine patient priority.
4. Prediction: temporally evaluated service-duration intervals, baseline comparison, demand forecast and explicit insufficiency fallback.
5. Experiments: immutable scenario versions, paired assignment-policy comparisons, staffing schedules, repeated outages, lab returns/no-shows, replay, sensitivity and ablation results.
6. Delivery: a reproducible 50-arrival busy-clinic experiment, real PostgreSQL migrations/concurrency checks, browser workflows, Docker rebuild and updated evidence.

Progress is recorded in the final evidence report after execution, not inferred from feature presence. Existing synthetic records are preserved; only isolated test fixtures may be reset.

Implementation is connected across these six areas. See [the enhanced demo](ENHANCED_DEMO.md) for workflows, [the decision log](DECISIONS.md#adr-017--longitudinal-workspace-without-an-ehr-scope-expansion) for assumptions and [verification evidence](TEST_EVIDENCE.md) for executed checks and remaining research limits.

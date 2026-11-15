# Connected enhancement demonstration

This is a synthetic-only software research demonstration, not clinical validation. Start the local stack using the README. Existing data are migrated in place; no reset is required. Use separate browser profiles/private windows for different staff accounts.

## Patient workspace and laboratory return

1. Reception: register a synthetic patient. Keep the private receipt token out of screenshots/logs.
2. Clinician: record observations using their labelled units, choose P1–P5 and confirm the structured assessment dialog. No model decision is applied automatically.
3. Open **Patient workspace**, search/select the patient, inspect the encounter history, append observations and save a consultation note. Blank observations are missing, not zero. History is append-only.
4. Select the consultation as the handover source, Laboratory as destination and enter a synthetic message. Sending does not route the patient.
5. Call/start Consultation; **Complete & route → laboratory**. An eligible receiving operator acknowledges the message in Service console.
6. Call/start/complete Laboratory; choose **consultation**. A second consultation episode appears without replacing the first. Complete the return consultation and choose the next configured service or Finish visit.
7. Reception: select the same patient and **Register follow-up visit**. The previous encounter remains in history; reception cannot see clinical notes/observations. The new private token appears once. A second simultaneous active visit is rejected.

## Staffed rooms and explicit assignment

1. Administrator or manager: open **Staff & rooms**, create a room for a service with no active unassigned calls, and assign a compatible staff member with timezone-aware shift times. Device-local inputs are sent as UTC; displayed timestamps use Africa/Harare.
2. Add more rooms and different staff for parallel capacity. Staff/room shift overlaps are rejected. The service's configured capacity remains an additional upper bound.
3. Add a room outage or staff break. Current work is preserved; new reservations are unavailable during the block. Only unchanged future schedule entries may be cancelled.
4. Clinician/service operator: choose the service, **Review room alternatives**, inspect availability, population-history explanation and duration fallback/interval, choose a room and supply an approval reason.
5. Approval atomically reserves room/staff and calls only the current queue head. A changed queue, expired proposal or changed availability requires a fresh proposal. Start/complete service in Service console.
6. A no-show releases the reservation. Reopen waiting and request a fresh assignment when the patient returns. An outage after approval blocks a new start; it does not interrupt already-started care.

Room availability is recorded operational capacity, not verified physical attendance. Schedule-based utilisation appears separately with its denominator and limitations. Live resource histories must not be treated as causal staff-performance comparisons.

## Reproducible busy-clinic experiment

1. Researcher/manager: open **Experiments → Load 50-arrival busy-clinic preset**.
2. Inspect 3 heterogeneous rooms, one delayed shift, a staff break, room outage, laboratory-return probability, initial no-shows, 5 paired replications and 75/100/125% demand sensitivity.
3. **Save scenario version → Run saved scenario**. Runs use the saved configuration; unsaved editor changes do not affect them.
4. Inspect fixed-room, next-available and capacity-aware results, paired 95% interval, unserved counts, mean replication P90, urgency slices and ablations. A positive capacity-minus-fixed difference is a loss, not an improvement.
5. Move the replay slider and select individual synthetic patients to inspect stage history and laboratory returns. Inspect room occupancy and availability at the finite horizon.
6. Export JSON/CSV/SVG. Save another immutable revision and use **Compare result** for two saved runs. Different scenario versions are not a paired causal comparison.

The 50 arrivals are a **simulation cohort**, not 50 live patient registrations or observed clinical outcomes. Synthetic room speeds illustrate the assignment hypothesis; they do not validate the live population-history heuristic.

## Operational prediction

Generate history if needed: `docker compose exec api python -m app.cli synthetic --count 300 --seed 2026`.

In **Analytics → Train operational predictor**, the durable worker evaluates service-duration intervals against a stage-median baseline. Inspect test MAE, measured coverage, width, partition counts and provenance. A baseline can win. The demand panel shows next-hour estimates, walk-forward error and stale/insufficient-history warnings. Patient duration never sets priority. The original urgency classifier remains separately experimental and requires its existing review/activation controls.

## Automated demonstration

With current API/worker/migration images built, Node 22.23.4, Python environment and Chrome available:

```bash
python scripts/verify_browser.py
```

This builds a browser-specific web image, starts a uniquely named disposable database-backed Docker instance, generates 300 synthetic histories, runs the complete Playwright suite, and removes only that instance. Main demo records are preserved. Ports 3100 and 8100 must be free. The HTML report is `apps/web/playwright-report/index.html`.

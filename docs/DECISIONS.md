# Architecture decision log

## ADR-001 — Modular monolith

**Status:** accepted, 2026-10-24.  
The prototype uses one FastAPI service with separate workflow, queue, audit, research and simulation modules. This reduces deployment and consistency risk while preserving module boundaries. It is an engineering choice, not a research result.

## ADR-002 — Configurable neutral urgency labels

P1–P5 are neutral ordering labels. No vital-sign threshold or emergency triage protocol is encoded. Only a clinician-entered category is authoritative; any model result remains advisory.

## ADR-003 — Synthetic-only default

Seed data, generated visits and the included classifier are synthetic. Dataset imports reject obvious direct identifiers, are access controlled, and must carry a provenance statement. `RESEARCH_MODE=true` is required at startup unless an explicit future safety review changes the guard.

## ADR-004 — Authentication and browser security

The API uses short-lived signed session tokens in HTTP-only SameSite cookies, a double-submit CSRF token for state changes, Argon2id password hashes, default-deny RBAC and facility-scoped queries. Secure cookies are enabled outside local HTTP by configuration.

## ADR-005 — Queue policy

The operational hybrid policy anchors ranking on clinician-confirmed urgency. Waiting-time ageing only reorders within the same urgency group. Service duration is used for ETA only. Manual pins require clinician permission, an audit reason, and expire when the entry leaves `WAITING`.

## ADR-006 — Offline boundary

The PWA caches only its shell and public static assets. It labels stale/offline state and never queues clinical decisions locally. Read refreshes retry after reconnection; mutation conflicts require a fresh server state.

## ADR-007 — Local deployment rather than Sites hosting

The web application is delivered locally through Docker Compose because the specification requires a PostgreSQL/FastAPI research stack and reproducible local deployment. No hosted clinical or patient data service is used.

## ADR-008 — Conservative command serialization

Each authenticated mutation locks its facility row in PostgreSQL and commits its state, audit, outbox and idempotency response together. This deliberately limits write throughput for a single-site research demonstration. CPU-heavy training and simulation run in a separate durable worker, outside that facility transaction. A request key is bound to actor, endpoint and body hash; a changed body cannot reuse it. Receipt secrets are regenerated with HMAC for an exact retry, never stored in the replay ledger.

## ADR-009 — Token privacy over path compatibility

The specification's URL-token GET route returns 410. The implemented POST lookup keeps the private token out of URL history, referrers and ordinary access logs. It is unauthenticated but opaque-token-authorized and rate limited. The sequential display number alone never retrieves a visit. The token page polls every ten seconds and labels stale state.

## ADR-010 — Research validity and data boundary

Only synthetic uploads are accepted; adding real or open clinical data requires a separate approval and schema review. Baseline time-motion CSV import is separate from the training schema, supports mapping and preview, and stores only an aggregate report. The synthetic classifier uses a temporal holdout, training-only cross-validation, baselines, reliability bins and explicit abstention. A clinician review permits *synthetic demonstration* activation, not clinical validation. There is no external LLM call.

## ADR-011 — What the policy weights mean

Urgency is a hard clinician-confirmed grouping constraint. Waiting weight operates only inside that group. Availability is shared by entries at a service point, so its score contribution does not change their relative order; zero capacity blocks all new calls. The API exposes all score components. The hybrid and urgency-first policies may produce identical results; this is expected under the safety constraint, not hidden or presented as an improvement.

## ADR-012 — Timestamp history and operational limitations

Completed episodes are immutable in PostgreSQL. A separate append-only correction stores original and corrected values with an authorised actor and reason. Analytics use the latest episode correction while preserving the original visit-completion event. Pause intervals are excluded from service duration. Historical room-staffing intervals are not inferred. The original analytics remain timestamp-based; the October 2026 extension adds a separate recorded-shift utilisation measure (ADR-018).

Operating hours are informational local facility configuration; an authorised person sets availability rather than the application silently interrupting care at closing time. P1–P5 labels remain fixed neutral research categories in this build; adopting a local clinical scale requires separate schema/protocol review.

## ADR-013 — Database and launch security

The migration service owns DDL and seed provisioning. API and worker use a separate non-superuser database account without schema-creation or truncate rights. PostgreSQL triggers block audit/decision edits and completed-episode mutation. These controls do not make the system tamper-proof against a database administrator. Local ports bind to loopback; public demonstration credentials, HTTP cookies and process-local rate limits are suitable only for this local research deployment. TLS, distributed rate limiting, independent security assessment and appropriate approvals are required before any broader deployment.

## ADR-014 — Dependency verification

Dependencies are installed and tests are run rather than assuming compatibility from the initial scaffold. Browser testing was upgraded after npm reported GHSA-7mvr-c777-76hp in the older Playwright pin. Slow Python downloads are handled with a longer documented [uv read timeout](https://docs.astral.sh/uv/configuration/environment/#uv_http_timeout) and fewer concurrent downloads; this is a setup workaround, not an application requirement.

The final tested Python resolution is `requirements.lock`; npm uses `package-lock.json`. FastAPI/Starlette, multipart parsing, JWT and test dependencies were updated after checking package metadata and dependency audits. See the [Starlette form-limit advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq). Model versions include the pipeline revision and numerical-library versions to distinguish retraining under changed software.

## ADR-015 — Short-lived reads and privacy-safe live events

SSE messages are invalidations with scoped identifiers and empty data objects, never arbitrary outbox payloads. Clients refetch through role-checked REST endpoints. Ordered `(created_at, id)` cursors cross equal-timestamp pages without replay starvation; active sessions are revalidated on every poll. Database dependencies close before streaming starts using FastAPI's documented [function-scoped dependency lifetime](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope). Each stream poll releases its own transaction before sending messages or waiting.

Container-level burst testing additionally exposed event-loop starvation when a synchronous stream poll waited for a pooled connection. Polling and cursor lookup now execute in the thread pool, allowing other requests to close their connections. Both the off-loop invariant and 20 simultaneous real streams are tested. Merely increasing the connection limit was not treated as a fix.

Timestamp corrections carry the last correction ID as well as the immutable episode version, so one correction cannot unknowingly supersede another. Analytics provenance hashes effective corrected timings rather than only the original values.

## ADR-016 — Recoverable local-demo operations

Backups create unique permission-restricted directories, never silently overwrite an earlier snapshot, and require an explicit trusted directory plus confirmation to restore. Both archives are checked before stopping services. The real restore commands were exercised only on a uniquely named disposable Compose project, including private dataset SHA-256 comparison; the main demonstration was preserved. Backup encryption, untrusted-dump ingestion and production disaster-recovery certification are not supplied by this prototype.

## ADR-017 — Longitudinal workspace without an EHR scope expansion

The 26 October 2026 enhancement adds repeat encounters, append-only observations with explicit units, encounter notes/addenda and acknowledged handovers. It does not add diagnoses, prescriptions, orders or automated vital-sign interpretation. Six observation fields are recording metadata, not normal ranges or clinical thresholds. Reception sees encounter logistics, not notes, observations or handover messages. Service providers/pharmacy can read/write notes only for their authorised services. A handover is not a transfer: staff must explicitly complete-and-route or transfer the episode. A laboratory return creates a new consultation episode and preserves the first.

## ADR-018 — Staffed rooms and historical availability

A service without configured rooms retains the original capacity workflow. Creating its first room enables mandatory approved reservations; existing unassigned calls must finish first. Explicit staff shifts, role compatibility, timed staff breaks and room outages determine eligibility. Scheduling rejects overlapping staff/room shifts, and partial unique PostgreSQL indexes prevent multiple active reservations of a room, member of staff or episode. Facility command serialization protects snapshot checks and atomic call/reservation/audit commits.

Proposals expire after five minutes and are rechecked against queue-head version and current availability before approval. New starts are blocked by intervening outages; already-started work is non-preemptive. Paused work retains its reservation. Completion, transfer, cancellation, no-show and an explicit return to waiting release it. An authorised service operator can act on behalf of the allocated staff member; allocation is operational, not a verified attendance/signature system.

Utilisation is occupied time divided by recorded staffed-room time minus recorded breaks/outages. No interval before a record's creation is assumed known. Overlapping blocks are integrated once. Pauses occupy the room; service may overrun an outage/shift and the ratio may exceed 100%. Zero denominator is unavailable, not zero utilisation. Ongoing/past schedule entries cannot be cancelled to erase history; a new block can record a prospective absence. Historical role revocation, service-point availability changes and physical attendance are **not** reconstructed by this schedule-based denominator.

## ADR-019 — Operational model separate from clinical urgency research

Completed synthetic stage durations train an operational predictor using stage, visit type, local hour and weekday. Chronological whole-visit train/calibration/test partitions prevent one visit crossing sets, and outcomes unavailable at the next partition's start are purged. Quantile gradient boosting competes with a stage-median baseline using calibration-set MAE. The untouched test set reports MAE, baseline MAE, marginal interval coverage and width. Residual interval expansion targets nominal 80% coverage; measured coverage may be worse, especially under time drift. These are not individual guarantees.

The private operational model informs estimates only, never queue ordering or clinical categories. Missing artifacts, unseen visit types and insufficient stage samples produce an explicit fallback. Public waiting ranges approximate residual work using current recorded staffing; they are **not calibrated waiting-time intervals**. The arrival forecast interpolates the next 60 minutes from rolling observed-day hourly means, reports walk-forward error and a constant-rate baseline, and flags stale history. Days with no records are unknown, not assumed open zero-arrival days. Its descriptive spread is not a calibrated prediction interval.

## ADR-020 — Resource assignment and distinct research comparators

Available compatible rooms are presented to authorised staff for explicit choice. With at least five recorded assignments per available room, the suggestion favours lower population mean occupied duration; otherwise it falls back to recent assignment counts. These descriptive resource histories are confounded by case mix and must not be interpreted as causal staff performance. Individual patient duration never changes queue rank or denies access to a room. Staff may choose any available compatible alternative and must supply a reason.

The new finite-day simulator compares fixed round-robin rooms, pooled next-available assignment, and pooled population-capacity-aware assignment. Synthetic room speed factors stand in for resource heterogeneity; they are **not measured live room speeds or a validation of the deployed heuristic**. Synthetic urgency/arrival order is preserved within each policy's eligible queue. Original FCFS/urgency/hybrid results are retained, including the possibility of identical urgency/hybrid ordering.

The busy-day preset deliberately lists rooms in non-speed order (1.5, 0.7, 1.0 duration multipliers). Otherwise selecting the first numbered available room accidentally coincides with choosing the fastest available room. This is an illustrative assumption, not a tuned claim of benefit; equal or worse outcomes remain valid. A controlled single-patient test verifies that the strategies select different resources without selecting different patients.

Scenario versions are immutable with configuration hashes. Replications use common random inputs, repeated breaks/outages, finite shifts, initial no-shows (70% return propensity, configurable delay), optional laboratory-return visits, and a finite observation horizon. Unfinished arrivals and not-yet-arrived patients are distinct. Mean waits are completed-journey-only and can be selection-biased; mean replication P90 is not pooled P90. Paired intervals compare within-scenario replications, not different scenario versions. Ablations expose removing resource-aware choice and room pooling. No improvement is presumed.

## ADR-021 — Isolated full-stack browser verification

Daily display tokens can repeat; private tokens and visit UUIDs remain unambiguous. Browser worklists use visit IDs for stable targeting. Verification runs in a newly named disposable Compose project, with its own PostgreSQL/model volumes and loopback ports 3100/8100, rather than consuming existing demo capacity. The script removes only the project it created. Native browser prompts were replaced by structured, cancellable, focus-restoring dialogs; offline mutations remain disabled.

## ADR-022 — Immutable research protocols and independent synthetic references

The 28 October extension adds six facility-scoped tables in migration `20261026_0004`. Protocols freeze the question, design, dataset hash, feature definitions, optional model/metrics identity, case snapshots and operational configuration. They are locally immutable records, not external preregistration or ethics approval. Changes require a new protocol. Cases are sampled reproducibly from the final chronological dataset partition; timestamp ties stay together. The dimensionless `recorded_measurement` is a generator input, not a vital sign. Outcome, service duration and identifiers are excluded from advisory predictors.

Two different authorised clinical-role accounts can independently review each synthetic case. Neither sees the generator label or the other's label before submission. Consensus is available only to those original reviewers after both labels exist; this is **two-reviewer consensus**, not an independent third adjudicator or clinical gold standard. A participant cannot trial a predictor snapshot they previously reviewed, or independently review one already trialled, across protocols. Protocols/cases/reviews/consensus and completed trials/runs have PostgreSQL immutability triggers. A partial unique index and facility command transaction prevent duplicate active trials. Database administrators remain outside this tamper-resistance boundary.

## ADR-023 — Separate fitting, calibration, abstention selection and final testing

Classifier v4 uses chronological 50/10/10/10/20 fit, model-selection, calibration, threshold-selection and final-test partitions, with tied timestamps kept together. Preprocessing fits only the first partition. C=0.1/1/10 selection uses later development macro-F1; three-fold fit-only CV is a supporting diagnostic. Scalar temperature minimises calibration log loss. The abstention threshold minimises `(accepted errors + 0.35 × abstentions) / examples` on its own partition, breaking ties by coverage then threshold. The cost is an explicit unitless engineering assumption, not a clinical harm/acceptance criterion. Legacy `train_rows` means all development rows; `estimator_fit_rows` identifies rows actually fitted.

Majority, random-forest and cumulative ordinal comparators remain visible. Raw/calibrated probability diagnostics, risk–coverage curves, learning curves, synthetic perturbations and local explanation stability use labelled partition identities. Fixed-model row-bootstrap intervals assume independent synthetic rows and exclude fitting/selection uncertainty. Wilson intervals accompany selective error, including zero observed errors; degenerate bootstrap risk intervals are suppressed. Small age slices remain suppressed below 30 examples. Exact logit contributions and predicted-versus-runner-up contrast are algebraic model explanations, not causal or clinical reasoning. Abstention hides class-identifying explanations/probabilities from operational and participant advisory displays while retaining private research evidence.

## ADR-024 — Consented explanation study and shadow evaluation

Manual-only, rotating counterbalanced manual/advisory/explanation, and shadow designs are stored in the frozen protocol. Counterbalancing rotates by participant offset and case order; it is not a fully randomised powered clinical trial. Participant consent reference, independent label, rationale, trust response, authority-comprehension response and server elapsed time are recorded. A negative/unsure comprehension answer is accepted. Task time includes pauses. Shadow outputs are withheld by the API until the independent response commits; hiding UI text alone is insufficient. Completed responses are immutable and never become automatic training labels or queue decisions.

Aggregate exports exclude participant IDs, consent references, free text and individual responses. Clinicians cannot read research aggregates/monitoring that would reveal reference outcomes while participating. Agreement with consensus and agreement with generator labels are distinguished. Rejection of an incorrect suggestion is counted only where advice was shown, never in manual/shadow arms. Browser fixtures exercise consent mechanics but are explicitly automated software tests, not recruited participants.

## ADR-025 — Supporting waiting-time prediction and equal-budget planning

The new study is **consultation-stage-only** and does not replace Objective 4's whole-journey FCFS/urgency/hybrid simulation. Queue snapshots contain only information available on arrival; realised future service times are prohibited predictors. Development days are split 60/20/20 for fit/selection/residual calibration, with unavailable outcomes purged at boundaries, before independent test days. A queue-workload baseline competes with gradient boosting; nominal 80% absolute-residual intervals are tested for actual coverage/width. Chronological drift invalidates an unconditional exchangeability claim. Started-case prediction errors are reported alongside unserved arrivals and all-arrival waiting.

Fixed rooms, pooled next-available, historical-demand planning and Poisson-forecast planning share held-out inputs and 1,080 paid staff-minutes per day (three 360-minute shifts, each including a 30-minute break). Candidate schedules are selected only using development forecasts and separate planning cohorts. The objective is finite-horizon accumulated waiting across **all arrivals**, including unserved patients. Paired replication intervals and precision are reported against the stronger historical comparator as well as pooling. Low/high load and outage sensitivity runs retain the previously selected schedules. Equal paid budgets need not mean equal available minutes when schedules overlap an outage differently; both are reported.

This supporting engine deliberately bounds synthetic service durations to 1–30 minutes and forbids any new start within 30 minutes of a break/shift end. This universal clearance makes the no-overtime constraint inspectable without ranking patients by individual duration, but sacrifices capacity and is **not a clinical scheduling recommendation**. Outputs never apply schedules to the live resource system. Better prediction alone is not evidence of a waiting-time intervention benefit.

## ADR-026 — Monitoring as an offline research challenge

Shadow monitoring compares completed independent responses with hidden-at-decision inference; those responses are not clinical ground truth. It reports missingness, categorical total-variation distance including the missing category, numeric mean movement in training-standard-deviation units, nonoverlapping response windows, coverage and age slices. Drift diagnostics require at least ten responses and do not trigger retraining or deployment actions.

An additional reproducible challenge resamples synthetic test rows into eight 20-row windows over five replications, with a shift after three unchanged windows and labels delayed one window. Unchanged, missing-input shift and label shift are retained. Guard/error alert thresholds use model-selection rates plus 0.20, capped at one. False alarms, missed detections (null delay) and detection delay are exported; repeating synthetic rows limits independence/generalisation. This is a transparent monitor demonstration, not a validated statistical detector. Missed label-shift detections are retained in the evidence.


## ADR-027 — Real client addresses, account lockout and shared-workstation sessions

**Status:** accepted, 2026-11-15.
Rate limits previously keyed on `request.client.host`. Behind the Next.js proxy that is always the web container, so one bucket served the whole clinic: four patients polling their status page every 10 s exceeded the 20/minute limit, and one mistyped password loop could block every staff sign-in. `X-Forwarded-For` is now honoured only when the direct peer is a configured trusted proxy (`TRUSTED_PROXIES`, default loopback and the Compose network). The chain is read right to left and the first untrusted hop is used, because proxies append hops. A client therefore cannot pick its own bucket.

Patient-status lookups are limited strictly on *misses* per real address (20/minute), per token (20/minute) and by a generous per-address ceiling (600/minute) for a waiting room behind one NAT. Tokens carry 192 bits or more of secret, so the miss limit is what prevents enumeration.

Sign-in uses Argon2 for unknown emails too, so timing does not reveal which accounts exist. Five consecutive failures lock an account for 15 minutes. The lockout is stored in PostgreSQL (multi-worker safe), audited, and released by an administrator's access change or password reset. Unknown emails show the same lockout message, so the lockout reveals nothing either. IP limits remain process-local (single uvicorn worker, ADR-013).

Administrator-set passwords are temporary: the server blocks all other endpoints until the person chooses their own password. The password policy is length-first (12+ characters, common and identity-derived passwords blocked), following NIST SP 800-63B rather than composition rules. Changing a password revokes other sessions. Sessions have an idle window (`SESSION_IDLE_MINUTES`, default 30) inside the absolute lifetime. Only genuine user input refreshes the window, so background polling cannot keep an unattended reception PC signed in. The UI also shows a lock screen after a shorter period.

## ADR-028 — Missed calls: recall and deferral

A called patient who does not appear can be **recalled** (re-announced on the display; status stays CALLED) or **deferred**. Deferral returns them to WAITING with their original `queued_at` and `joined_at`, so measured waits still start at first arrival. Until `deferred_until` (1–60 minutes, default 10), they rank after every callable entry. After that their original place returns. This deliberately overrides urgency order for a patient who is physically absent; it is a presence state, not ageing, and it is time-limited and audited. After three missed calls deferral is refused and staff must record a no-show or a clinician must keep the place by override. The first call stays in `queue_state_events`.

## ADR-029 — Day close

Without an end-of-day step, unseen WAITING entries carried into the next morning with 15-hour waits, distorting within-group ordering, ETAs and analytics. An administrator or clinician now reviews open visits for a local date and closes the day. Unseen, not-started episodes become CANCELLED and the visit becomes LEFT_WITHOUT_SERVICE, with audit reason code `DAY_CLOSE_UNSEEN`. Visits already in service block the close until they are finished or explicitly kept open. The preview's count must match (optimistic concurrency) and each date can be closed once. `day_closures` is append-only in PostgreSQL. Queue entries from an earlier local day are flagged `carried_over` and counted in System health. Nothing is closed automatically (consistent with ADR-012 on operating hours).

## ADR-030 — Downtime, LAN TLS, encrypted backups and system health

**Downtime.** Staff print a downtime sheet (current queue order plus blank rows) and work on paper during an outage. Afterwards, reception or an admin back-enters paper records from the last seven days as visits with `entry_mode = RETROSPECTIVE` and a paper reference, with validated stage ordering. These are new records with paper times; they are not offline-queued commands, so ADR-006 still holds. Analytics count them separately.

**LAN TLS.** `docker-compose.lan.yml` now exposes only a Caddy TLS proxy using its own local CA, with secure cookies and HTTPS origins. Plain HTTP stays on loopback. HTTPS is also what makes the PWA and service worker work on LAN tablets.

**Backups.** With `BACKUP_PASSPHRASE_FILE` set, archives stream through GPG (AES-256, symmetric) and no plaintext is written to disk. `REQUIRE_BACKUP_ENCRYPTION=1` refuses unencrypted backups. A SHA256SUMS manifest is checked before restore.

**System health.** A status file sits on a separate volume (so a restore cannot rewind it) and feeds an admin/manager System health view: database, worker, storage, backup age and encryption, locked accounts, carried-over entries, display liveness and device clock skew.

## ADR-031 — Waiting-room display and FHIR-shaped export

Displays authenticate with revocable per-screen keys (stored as SHA-256 digests, shown once, stripped from the idempotency replay ledger). The board shows only display numbers being called, destination and room, and per-service queue counts. It never shows names, urgency, the order of waiting patients or reasons, so it cannot be used to infer who was prioritised.

The spec section 14 export is an admin-only, synthetic-only, one-way FHIR R4-shaped Bundle (Patient without pseudonym, Encounter, Observation) using local code systems and a structural self-check. It is explicitly not a certified FHIR interface, and P1–P5 are exported as a neutral local category (ADR-002).

## ADR-032 — Patient-facing status extension and interface redesign

The public status response now also returns the patient's *own* stage names with done/current/next state, and the room they are called to. It still excludes identity, urgency, times and reasons; the minimality test pins the new exact key set. Receipts carry a QR code to `/status#t=<token>`. The fragment is never sent to the server, and the page removes it from the address bar and history after reading it.

The interface was redesigned around role-specific work and offline-capable self-hosted fonts. It keeps a neutral ink ramp for P1–P5, with no alarm palette that would imply clinical acuity. Patient-facing copy is in English, chiShona and isiNdebele. **These translations are drafts for usability testing and must be reviewed by native speakers before any field use.** Accessible names relied on by the browser suite are kept stable.

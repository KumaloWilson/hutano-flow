# Hutano Flow

Hutano Flow is a database-backed research prototype for clinician-supervised outpatient queue optimisation and patient-flow management. It is based on Michelle Sambawamedza's project specification and is **not authorised for clinical use**. See [verified results and acceptance mapping](docs/TEST_EVIDENCE.md).

The system starts in research mode, accepts synthetic patients only, and keeps P1–P5 urgency authority with a signed-in clinician. The included AI classifier and all supplied data are synthetic software demonstrations—not clinical evidence.

The 30 October clinic demonstration adds believable fictional identities, three weeks of coherent history, live scripted cases, staffed rooms, a guided walkthrough, filtered analytics and saved scenario comparisons. Start with the [clinic demonstration](docs/CLINIC_DEMO.md) and [verification evidence](docs/CLINIC_DEMO_EVIDENCE.md). The [research demonstration](docs/RESEARCH_DEPTH_DEMO.md) covers the deeper workbench; earlier evidence remains dated separately.

## What is included

- Next.js/TypeScript responsive PWA for reception, triage, queues, service staff, managers, researchers and privacy-safe patient status.
- FastAPI/SQLAlchemy REST API with facility scoping, RBAC, Argon2id credentials, HTTP-only session cookies, CSRF checks, idempotency and optimistic locking.
- PostgreSQL schema and Alembic migration covering visits, episodes, queues, triage, audit/outbox, datasets, models and simulations.
- Deterministic FCFS/urgency/hybrid queue policies, atomic calling, clinician override, long-wait warning and service outage control.
- SSE queue updates with polling/manual refresh fallback and an offline/stale-state boundary.
- Operational analytics and privacy-safe CSV exports.
- Reproducible SimPy experiments using common random numbers across policies, including zero-capacity and adverse/no-improvement results.
- Synthetic scikit-learn research classifier, model registry, confusion matrix, per-class metrics, under-triage-against-synthetic-label count and confidence abstention.
- Pytest integration/security/research tests and Playwright workflows.
- Longitudinal patient workspace, observations with units, encounter notes/addenda, acknowledged handovers and repeat consultation episodes.
- Staffed rooms, shifts, breaks/outages and snapshot-bound human-approved reservations with database double-booking constraints.
- Operational duration intervals with temporal evaluation, baseline comparison and an observed-day arrival forecast; neither changes patient priority.
- Immutable finite-day experiment versions, three resource-assignment policies, paired uncertainty, sensitivity/ablations, replay and report exports.
- Frozen research protocols, blinded dual reviews/consensus, consented counterbalanced explanation tasks and shadow predictions withheld until independent assessment.
- Separate fitting, model selection, calibration, abstention selection and final evaluation; ordinal baselines, risk–coverage, uncertainty, stress/stability and offline drift-detection diagnostics.
- Supporting direct waiting-time intervals and forecast-informed planning against fixed/pooling/historical baselines at equal paid staffing budgets, with durable runs and reproducible exports.

## Quick start

Requirements: Docker Engine with Compose v2/BuildKit, at least 4 GB free memory, and localhost ports 3000, 8000 and 55432 available. Initial package downloads may be substantial.

```bash
cp .env.example .env
# Replace SECRET_KEY with a random value of at least 32 characters.
# Set POSTGRES_PASSWORD and APP_DB_PASSWORD, and update both database URLs to match.
docker compose up -d --build
docker compose exec api python -m app.cli showcase
```

Open:

- Web application: `http://localhost:3000`
- API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

The one-shot `migrate` service applies migrations and idempotently creates the facility, service points, demo accounts, neutral queue policy and actual synthetic training CSV. API and worker then run as the restricted `hutano_app` database role. Nothing is published externally; all three exposed ports bind to loopback. `RESEARCH_MODE=false` intentionally refuses startup.

For an existing database created before the restricted role was introduced, provision it once with `docker compose exec -T db sh /docker-entrypoint-initdb.d/10-hutano.sh`. Changing `.env` passwords does not rotate passwords in an existing database; use an explicit administrator procedure or reset **disposable demo data only**.

## Demo accounts

The login screen defaults to **Hutano Community Clinic**. Its accounts use
`@showcase.hutano.test` with the corresponding role passwords below. The complete
[clinic role list and walkthrough](docs/CLINIC_DEMO.md) also includes a second
clinician and laboratory provider. Select **Original research workspace** to use
the original accounts in this table. No original data is overwritten.

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@demo.hutano.test` | `DemoAdmin1!` |
| Receptionist | `reception@demo.hutano.test` | `DemoReception1!` |
| Triage nurse | `triage@demo.hutano.test` | `DemoTriage1!` |
| Clinician/provider | `clinician@demo.hutano.test` | `DemoClinician1!` |
| Pharmacy | `pharmacy@demo.hutano.test` | `DemoPharmacy1!` |
| Researcher/manager | `research@demo.hutano.test` | `DemoResearch1!` |

These credentials are public demonstration credentials. They must never be reused for any deployment containing authorised real data.

## Demonstration workflow

Follow [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). The shortest end-to-end path is:

1. Reception creates a synthetic patient/visit and completes registration.
2. Triage or clinician explicitly assigns a neutral P1–P5 category.
3. Clinician calls and starts Consultation, then completes and routes to Pharmacy.
4. Pharmacy calls, starts and completes service, closing the visit.
5. The anonymous status page accepts the full opaque receipt token and reveals only stage, general state, approximate people ahead and a qualified estimate.

For the deeper workflow, follow [the enhanced demonstration](docs/ENHANCED_DEMO.md): patient workspace → staffed laboratory handover/return → repeat visit, then the saved **50-arrival / 3-room** experiment and operational predictor. The simulated cohort is separate from live registrations.

## Tests

With Docker:

```bash
docker compose run --rm api pytest -q
make test-web
# Install host browser-test dependencies:
cd apps/web
npm ci
PLAYWRIGHT_CHANNEL=chromium npx playwright install chromium
cd ../..
# Verify against an isolated, disposable full Docker stack:
PLAYWRIGHT_CHANNEL=chromium python scripts/verify_browser.py
```

Use Node 22.23.4 (or a compatible newer supported release) for host tests. If Google Chrome is already installed, `npm run test:e2e` uses it by default. `make test-web` builds a dedicated test image; the minimal runtime web image intentionally has no test tooling.

Backend tests use isolated SQLite databases, plus six opt-in tests that create and remove uniquely named PostgreSQL schemas. Run the full set in Docker with owner authority **only for the test process**:

```bash
docker compose run --rm api sh -c 'TEST_POSTGRES_URL="$1" pytest -q' sh \
  'postgresql+psycopg://hutano:YOUR_LOCAL_OWNER_PASSWORD@db:5432/hutano_flow'
```

Do not use real credentials in shared shell history. These are local synthetic-demo credentials only. Without `TEST_POSTGRES_URL`, the six PostgreSQL-only tests are explicitly skipped, not counted as passed. The production command service continues to use the restricted application role. `npm run test:e2e` alone targets the current demo and creates synthetic records; prefer the isolated script to avoid existing active visits consuming test capacity.

For host development use Python **3.12**, a virtual environment and `pip install -r services/api/requirements.lock`. Run Alembic/seed from `services/api`, set `DATABASE_URL` to localhost:55432, and use the same absolute `MODEL_ARTIFACT_DIR` for API, seed and worker. Start `uvicorn app.main:app --host 127.0.0.1 --port 8000`, `python -m app.worker`, and `npm run dev` in separate terminals. `.env` loading is relative to the working directory; do not assume root `.env` is read from `services/api`.

If an old `.venv` points to a removed interpreter, recreate it with Python 3.12 or use the Docker test commands; do not install the ML stack into an incompatible host interpreter. `verify_research_depth.py`, `verify_browser.py`, `verify_backup_restore.py` and `verify_clean_boot.py` use the Python standard library and can be orchestrated with host `python3`.

Generate 300 reproducible completed synthetic journeys:

```bash
docker compose exec api python -m app.cli synthetic --count 300 --seed 2026
```

Generate the OpenAPI snapshot and matching TypeScript schemas:

```bash
make contracts
```

## Reset, backup and restore

Reset removes this Compose project's demo database/model volumes. Existing local records and private model files are lost unless backed up:

```bash
make reset CONFIRM=RESET_SYNTHETIC_DEMO
```

For synthetic demo data only:

```bash
./scripts/backup_demo.sh
# Use the unique directory printed by the backup command:
CONFIRM=RESTORE_SYNTHETIC_DEMO ./scripts/restore_demo.sh backups/demo-XXXXXXXX
# Non-destructive-to-source restore verification using a disposable database:
python scripts/verify_backup_restore.py
# Isolated fresh-volume boot/reset and actual backup/restore command checks:
python scripts/verify_clean_boot.py
# Hold 20 dashboard streams open while checking authenticated API availability:
python scripts/verify_live_streams.py
```

Backups contain authentication and private artifact data even in synthetic mode. They are permission-restricted, ignored by source control, and **not encrypted**. Each backup uses a new directory without overwriting earlier snapshots. Keep the database and artifact archives together. Verify with no active writes/research jobs. Restore only trusted local snapshots: database dumps contain executable SQL. Restoration replaces this project's database; do not point it at another system. It restores archived artifact files without deleting unrelated newer files.

## Reproduce aggregate evidence

After generating 300 visits and training an inactive model in AI research:

```bash
python scripts/collect_evidence.py
```

Run with a Python environment containing the locked dependencies. This submits real worker jobs and writes aggregate JSON/CSV/SVG reports under `docs/evidence`. The default evidence run showed hybrid **increasing** mean total waiting by 4.4319 minutes, with an interval spanning zero; the result is retained. No clinical or real-world effectiveness claim follows.

## Project map

- `apps/web` — Next.js PWA and browser tests
- `services/api/app` — API, workflow, queue, ML and simulation code
- `services/api/migrations` — versioned database migration
- `services/api/tests` — integration, permission, leakage and research tests
- `docs` — architecture, data dictionary, threat model, evaluation, demo and decisions
- `smart_healthcare_queue_ai_agent_build_spec.md` — primary implementation contract

## Engineering assumptions and limits

- The actual study facility, approved triage instrument and labelled dataset are not available. One configurable demo clinic and neutral P1–P5 labels are used.
- Waiting-time ageing never crosses clinician-confirmed urgency groups by default. A clinician can explicitly pin an ordinary entry with a reason.
- ETA requires at least five completed stage samples, uses an evaluated operational duration model when applicable, and otherwise falls back to the recorded synthetic distribution. Current recorded staffing constrains capacity. Residual workload and waiting ranges are approximate, not calibrated individual guarantees.
- Offline mode caches the application shell only; it never submits clinical decisions later without a current server state.
- Dataset upload is synthetic-only in this build and rejects obvious direct-identifier columns. This does not replace a real de-identification review.
- The prototype has not undergone clinical validation, penetration testing, legal review, medical-device review or ethics/facility approval.
- Staff & rooms reports utilisation only over recorded staffing intervals, with explicit breaks/outages and no inferred prior history. Original simulations retain nominal-capacity metrics; the finite-day experiment reports scheduled availability and occupied time separately.
- Process-local rate limits and public demo passwords are for this loopback-only demonstration, not an internet-facing deployment.

## Troubleshooting

`409` means a stale version or changed-content retry key: refresh the current state, review it, then issue a new command. Research jobs remaining `PENDING` usually mean the worker is not running; inspect `docker compose logs worker`. Model training requires a registered, private CSV file, not just metadata. Dataset paths are rematerialised by seed when moving between host and Docker; retrain an inactive version to rematerialise its model file. Do not load externally supplied joblib/pickle artifacts.

For slow downloads, allow the first build to complete; subsequent builds cache dependencies. Do not run multiple installers against the same dependency directory. Use `docker compose logs migrate api worker` for startup failures and `docker compose ps` for health. These setup instructions do not authorise real-data use or public deployment.

See [docs/DECISIONS.md](docs/DECISIONS.md), [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), and [docs/RESEARCH_EVALUATION.md](docs/RESEARCH_EVALUATION.md) for the full rationale.


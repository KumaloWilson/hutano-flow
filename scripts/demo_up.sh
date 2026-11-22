#!/usr/bin/env sh
# Start the whole demonstration stack with one command: `make demo` or ./scripts/demo_up.sh
# First run on a fresh clone: creates .env from .env.example with random local secrets.
# An existing .env is never changed. Fictional/synthetic data only; loopback ports only.
set -eu
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/engine/install/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required (docker compose …)." >&2; exit 1; }

if [ ! -f .env ]; then
  random() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }
  secret=$(random); owner=$(random); app=$(random)
  sed -e "s/^SECRET_KEY=.*/SECRET_KEY=$secret/" \
      -e "s/change-this-local-password/$owner/g" \
      -e "s/change-this-app-password/$app/g" .env.example > .env
  chmod 600 .env
  echo "Created .env with random local secrets (kept for later runs; never commit it)."
fi

echo "Building and starting the database, API, worker and web app…"
docker compose up -d --build --wait --wait-timeout 300

cat <<'EOF'

Hutano Flow is running (research prototype; fictional data; not for clinical use).
  Web app:  http://localhost:3000   (choose Hutano Community Clinic and a role)
  API docs: http://localhost:8000/docs
Research results finish a few minutes after start-up; the Overview shows when they are ready.
Walkthrough: docs/CLINIC_DEMO.md   Stop: docker compose down
EOF

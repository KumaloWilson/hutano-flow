.PHONY: demo up down reset test test-api test-web test-local venv seed synthetic showcase openapi contracts

# One command for the whole demonstration stack (creates .env on a fresh clone).
demo:
	./scripts/demo_up.sh

up:
	docker compose up --build

down:
	docker compose down

reset:
	@test "$(CONFIRM)" = "RESET_SYNTHETIC_DEMO" || (echo 'Destructive: rerun make reset CONFIRM=RESET_SYNTHETIC_DEMO to remove this project’s demo volumes'; exit 1)
	docker compose down -v
	docker compose up -d --build

test: test-api test-web

test-api:
	docker compose run --rm api pytest -q

test-web:
	docker build --target tests -t hutano-flow-web-tests apps/web
	docker run --rm hutano-flow-web-tests

seed:
	docker compose exec api python -m app.seed

synthetic:
	docker compose exec api python -m app.cli synthetic --count 300 --seed 2026

showcase:
	docker compose exec api python -m app.cli showcase

openapi:
	curl --fail http://localhost:8000/openapi.json -o docs/API_OPENAPI.json

contracts: openapi
	node scripts/generate-contracts.mjs

# Host test environment. Uses a uv-managed Python 3.12 (kept under ~/.local, not /tmp,
# so a reboot cannot remove the interpreter); falls back to a system python3.12.
venv:
	rm -rf .venv
	if command -v uv >/dev/null; then uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r services/api/requirements.lock; \
	else python3.12 -m venv .venv && .venv/bin/pip install -r services/api/requirements.lock; fi

test-local:
	@.venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null || { echo 'Local Python 3.12 environment is missing or broken: run make venv'; exit 1; }
	cd services/api && ../../.venv/bin/python -m pytest -q
	cd apps/web && npm test && npm run typecheck


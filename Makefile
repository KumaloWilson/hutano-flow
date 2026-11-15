.PHONY: up down reset test test-api test-web test-local seed synthetic openapi contracts

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

openapi:
	curl --fail http://localhost:8000/openapi.json -o docs/API_OPENAPI.json

contracts: openapi
	node scripts/generate-contracts.mjs

test-local:
	cd services/api && ../../.venv/bin/python -m pytest -q
	cd apps/web && npm test && npm run typecheck


#!/usr/bin/env sh
set -eu
# Run from the repository root; host Node/Chrome prerequisites are in README.
docker compose up -d --build --wait --wait-timeout 90
docker compose exec api pytest -q
cd apps/web
npm ci
npm run test:e2e


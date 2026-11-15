#!/usr/bin/env sh
set -eu
backup_dir=${1:?Pass the trusted backup directory printed by backup_demo.sh}
test -f "$backup_dir/hutano-demo.dump"
test -f "$backup_dir/hutano-artifacts.tar.gz"
test "${CONFIRM:-}" = "RESTORE_SYNTHETIC_DEMO" || { echo 'Destructive: set CONFIRM=RESTORE_SYNTHETIC_DEMO to replace this project’s database and artifacts'; exit 1; }
# Validate both archives before taking the application offline. Restore only
# trusted local backups: database dumps can contain executable SQL.
docker compose exec -T db pg_restore --list < "$backup_dir/hutano-demo.dump" > /dev/null
docker compose exec -T api tar -tzf - < "$backup_dir/hutano-artifacts.tar.gz" > /dev/null
docker compose stop api worker
docker compose exec -T db sh -c 'pg_restore --exit-on-error --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$backup_dir/hutano-demo.dump"
docker compose run --rm -T --no-deps api tar -xzf - -C /app < "$backup_dir/hutano-artifacts.tar.gz"
docker compose up -d --wait --wait-timeout 90 api worker
echo "Synthetic demo database and artifacts restored."


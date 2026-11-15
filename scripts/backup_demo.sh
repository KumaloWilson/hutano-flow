#!/usr/bin/env sh
set -eu
umask 077
mkdir -p backups
backup_dir=$(mktemp -d backups/demo-XXXXXXXX)
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$backup_dir/hutano-demo.dump"
if docker compose ps --status running --services | grep -qx api; then
  docker compose exec -T api tar -czf - -C /app artifacts > "$backup_dir/hutano-artifacts.tar.gz"
else
  # A stopped API must not force an application migration before its backup.
  docker compose run --rm --no-deps -T api tar -czf - -C /app artifacts > "$backup_dir/hutano-artifacts.tar.gz"
fi
echo "Synthetic database and private model artifacts backed up to $backup_dir (not encrypted)." >&2
# stdout is the explicit path required by restore; earlier snapshots are retained.
printf '%s\n' "$backup_dir"


#!/usr/bin/env sh
# Back up the demo database and private model artifacts into a new, unique directory.
#
# Encryption (recommended, ADR-030): set BACKUP_PASSPHRASE_FILE to a file readable only by
# you, containing a long passphrase. Archives are then streamed straight through GPG
# (AES-256, symmetric) so no plaintext copy is ever written to disk.
#   BACKUP_PASSPHRASE_FILE=~/.config/hutano/backup-passphrase ./scripts/backup_demo.sh
# Set REQUIRE_BACKUP_ENCRYPTION=1 to refuse unencrypted backups altogether.
set -eu
umask 077
mkdir -p backups
backup_dir=$(mktemp -d backups/demo-XXXXXXXX)

passphrase=${BACKUP_PASSPHRASE_FILE:-}
if [ -n "$passphrase" ]; then
  test -r "$passphrase" || { echo "BACKUP_PASSPHRASE_FILE is not readable: $passphrase" >&2; exit 1; }
  command -v gpg >/dev/null || { echo "gpg is required for encrypted backups" >&2; exit 1; }
  encrypted=true
elif [ "${REQUIRE_BACKUP_ENCRYPTION:-0}" = "1" ]; then
  echo "Refusing an unencrypted backup: set BACKUP_PASSPHRASE_FILE" >&2
  rmdir "$backup_dir"
  exit 1
else
  encrypted=false
fi

# Reads stdin, writes the named archive (adding .gpg and encrypting when configured).
store() {
  if [ "$encrypted" = true ]; then
    gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$passphrase" \
      --symmetric --cipher-algo AES256 --output "$1.gpg"
  else
    cat > "$1"
  fi
}

docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' | store "$backup_dir/hutano-demo.dump"
if docker compose ps --status running --services | grep -qx api; then
  docker compose exec -T api tar -czf - -C /app artifacts | store "$backup_dir/hutano-artifacts.tar.gz"
  api_running=true
else
  # A stopped API must not force an application migration before its backup.
  docker compose run --rm --no-deps -T api tar -czf - -C /app artifacts | store "$backup_dir/hutano-artifacts.tar.gz"
  api_running=false
fi

# Integrity manifest for the stored (possibly encrypted) files.
( cd "$backup_dir" && sha256sum hutano-* > SHA256SUMS )

completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
status=$(printf '{"completed_at":"%s","encrypted":%s,"snapshot":"%s"}' "$completed_at" "$encrypted" "$(basename "$backup_dir")")
printf '%s\n' "$status" > "$backup_dir/backup-status.json"
# Tell the running API, so System health can show backup age (kept outside artifacts).
if [ "$api_running" = true ]; then
  printf '%s\n' "$status" | docker compose exec -T api sh -c 'cat > /app/ops-status/backup.json' || \
    echo "Backup succeeded, but the API status file could not be updated." >&2
fi

if [ "$encrypted" = true ]; then
  echo "Synthetic database and private model artifacts backed up (encrypted, AES-256) to $backup_dir." >&2
else
  echo "Synthetic database and private model artifacts backed up to $backup_dir (NOT encrypted; set BACKUP_PASSPHRASE_FILE)." >&2
fi
# stdout is the explicit path required by restore; earlier snapshots are retained.
printf '%s\n' "$backup_dir"

#!/usr/bin/env sh
# Restore a trusted backup created by backup_demo.sh (plain or GPG-encrypted).
#   CONFIRM=RESTORE_SYNTHETIC_DEMO ./scripts/restore_demo.sh backups/demo-XXXXXXXX
# Encrypted snapshots also need BACKUP_PASSPHRASE_FILE.
set -eu
backup_dir=${1:?Pass the trusted backup directory printed by backup_demo.sh}
test "${CONFIRM:-}" = "RESTORE_SYNTHETIC_DEMO" || { echo 'Destructive: set CONFIRM=RESTORE_SYNTHETIC_DEMO to replace this project’s database and artifacts'; exit 1; }

if [ -f "$backup_dir/hutano-demo.dump.gpg" ]; then
  test -f "$backup_dir/hutano-artifacts.tar.gz.gpg"
  passphrase=${BACKUP_PASSPHRASE_FILE:?This snapshot is encrypted; set BACKUP_PASSPHRASE_FILE}
  test -r "$passphrase"
  suffix=.gpg
else
  test -f "$backup_dir/hutano-demo.dump"
  test -f "$backup_dir/hutano-artifacts.tar.gz"
  suffix=
fi

# Emit the plaintext archive on stdout, decrypting in memory when needed.
open_archive() {
  if [ -n "$suffix" ]; then
    gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$passphrase" --decrypt "$1$suffix"
  else
    cat "$1"
  fi
}

if [ -f "$backup_dir/SHA256SUMS" ]; then
  ( cd "$backup_dir" && sha256sum --check --quiet SHA256SUMS ) || { echo "Checksum mismatch; refusing to restore" >&2; exit 1; }
fi
# Validate both archives (including decryption) before taking the application offline.
# Restore only trusted local backups: database dumps can contain executable SQL.
open_archive "$backup_dir/hutano-demo.dump" | docker compose exec -T db pg_restore --list > /dev/null
open_archive "$backup_dir/hutano-artifacts.tar.gz" | docker compose exec -T api tar -tzf - > /dev/null
docker compose stop api worker
open_archive "$backup_dir/hutano-demo.dump" | docker compose exec -T db sh -c 'pg_restore --exit-on-error --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
open_archive "$backup_dir/hutano-artifacts.tar.gz" | docker compose run --rm -T --no-deps api tar -xzf - -C /app
docker compose up -d --wait --wait-timeout 90 api worker
echo "Synthetic demo database and artifacts restored."

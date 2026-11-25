#!/bin/sh
# Nightly backup of the Postgres database and the hand off folder. Safe to run from cron: it moves to the repository folder itself.
#   BACKUP_DIR       where the files go (default /var/backups/pipecairn)
#   BACKUP_COPY_TO   optional rsync target on ANOTHER machine, for example user@host:/backups/pipecairn/ (a copy on the same disk is not a backup)
set -eu
umask 077  # a dump holds every lead and every reply: the files are readable by the user who runs this and nobody else
cd "$(dirname "$0")/../.."
OUT="${BACKUP_DIR:-/var/backups/pipecairn}"
mkdir -p "$OUT"
chmod 700 "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
DUMP="$OUT/pipecairn-$STAMP.dump"
HAND="$OUT/handoff-$STAMP.tar"
TMP_DUMP="$DUMP.partial"
TMP_HAND="$HAND.partial"
trap 'rm -f -- "$TMP_DUMP" "$TMP_HAND"' EXIT
# Write to a partial file first, so a failed dump never counts as a backup and never pushes a good one out of the rotation.
docker compose exec -T db pg_dump -U pipecairn -Fc pipecairn > "$TMP_DUMP"
if [ ! -s "$TMP_DUMP" ]; then
  echo "backup failed: the database dump is empty" >&2
  exit 1
fi
mv -- "$TMP_DUMP" "$DUMP"
docker compose exec -T api tar -C /data -cf - handoff > "$TMP_HAND" || true
if [ -s "$TMP_HAND" ]; then mv -- "$TMP_HAND" "$HAND"; fi
# keep the newest 14 of each
ls -1t "$OUT"/pipecairn-*.dump | tail -n +15 | while read -r old; do rm -f -- "$old"; done
ls -1t "$OUT"/handoff-*.tar 2>/dev/null | tail -n +15 | while read -r old; do rm -f -- "$old"; done
if [ -n "${BACKUP_COPY_TO:-}" ]; then
  rsync -a "$OUT"/ "$BACKUP_COPY_TO"
  echo "copied to $BACKUP_COPY_TO"
fi
echo "wrote $DUMP"

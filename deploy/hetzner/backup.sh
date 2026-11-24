#!/bin/sh
# Daily Postgres backup. Run from the repository folder: deploy/hetzner/backup.sh
set -eu
OUT=/var/backups/pipecairn
mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
docker compose exec -T db pg_dump -U pipecairn -Fc pipecairn > "$OUT/pipecairn-$STAMP.dump"
# keep the newest 14 dumps
ls -1t "$OUT"/pipecairn-*.dump | tail -n +15 | while read -r old; do rm -f -- "$old"; done
echo "wrote $OUT/pipecairn-$STAMP.dump"

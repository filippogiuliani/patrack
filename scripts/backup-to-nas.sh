#!/bin/sh
# paTrack → NAS with Borg. Runs on the Docker host (cron or systemd timer), once a night.
#
# What it copies (into an encrypted Borg repository on the NAS):
#   - a consistent snapshot of the database (made by paTrack itself, never the live file)
#   - files/ (the originals and previews, already encrypted with paTrack's key)
#   - .file_key and .secret_key (without the key the files cannot be read; the Borg repo is encrypted too)
# The outcome is written to paTrack_data/offsite.json: the Family page shows it and warns when it is missing or old.
#
# Configuration: scripts/backup.env (see backup.env.example). Exit code 0 = ok, 1 = failed.
set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. "$ROOT/scripts/backup.env"

DATA="${PATRACK_DATA_DIR:-$ROOT/paTrack_data}"
# How to run paTrack's manage.py: in the container by default
MANAGE="${PATRACK_MANAGE:-docker exec patrack python manage.py}"
STATUS="$DATA/offsite.json"
LOG="$DATA/offsite.log"
export BORG_REPO BORG_PASSPHRASE BORG_RSH="${BORG_RSH:-ssh}"

status() { # ok(true|false) message archive
  msg=$(printf '%s' "$2" | tr '"\\\n' "'/ " | cut -c1-300)
  printf '{"at": "%s", "ok": %s, "message": "%s", "archive": "%s"}\n' "$(date -Iseconds)" "$1" "$msg" "$3" > "$STATUS.tmp" \
    && mv "$STATUS.tmp" "$STATUS"
}
fail() { status false "$1" ""; echo "$(date -Iseconds) FAILED: $1" >> "$LOG"; echo "paTrack backup FAILED: $1" >&2; exit 1; }

# 1) Consistent database snapshot
SNAP_NAME=$($MANAGE backup 2>>"$LOG" | sed -n 's/^Created: //p')
[ -n "$SNAP_NAME" ] || fail "database snapshot failed (is paTrack running?)"
SNAP="$DATA/backups/$SNAP_NAME"
[ -f "$SNAP" ] || fail "snapshot $SNAP not found"

# 2) Borg archive (paths relative to the data dir, so a restore lands in the same layout)
ARCHIVE="patrack-$(date +%Y-%m-%dT%H%M)"
cd "$DATA" || fail "data dir $DATA not found"
borg create --compression zstd,6 --stats "::$ARCHIVE" "backups/$SNAP_NAME" files .file_key .secret_key >>"$LOG" 2>&1
rc=$?
# Borg: 0 = ok, 1 = warning (e.g. a file changed while reading: the next run copies it), 2+ = error
[ $rc -le 1 ] || fail "borg create exited with $rc (see $LOG)"

# 3) Keep 14 daily, 8 weekly, 24 monthly archives. With an append-only repository (recommended) this only marks
#    them: space is freed when you compact from the NAS side.
borg prune --keep-daily 14 --keep-weekly 8 --keep-monthly 24 >>"$LOG" 2>&1 || echo "$(date -Iseconds) prune failed" >> "$LOG"
borg compact >>"$LOG" 2>&1 || true

status true "$([ $rc -eq 1 ] && echo 'completed with warnings' || echo 'ok')" "$ARCHIVE"
echo "$(date -Iseconds) ok $ARCHIVE" >> "$LOG"

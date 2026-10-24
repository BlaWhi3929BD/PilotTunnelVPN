#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${TUNNELPILOT_DATABASE_PATH:-/opt/tunnelpilot/server/data/tunnelpilot.db}"
BACKUP_DIR="${TUNNELPILOT_BACKUP_DIR:-/opt/tunnelpilot/server/data/backups}"
MAX_BACKUPS="${TUNNELPILOT_MAX_BACKUPS:-7}"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Error: sqlite3 binary is required for database backup but was not found." >&2
  exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found at $DB_PATH, skipping backup."
  exit 0
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/tunnelpilot-$TIMESTAMP.db"

echo "Creating safe online SQLite backup to $BACKUP_FILE..."
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
chmod 600 "$BACKUP_FILE"

echo "Verifying backup integrity..."
INTEGRITY="$(sqlite3 "$BACKUP_FILE" "PRAGMA quick_check;")"
if [[ "$INTEGRITY" != "ok" ]]; then
  echo "Error: Backup integrity check failed: $INTEGRITY" >&2
  rm -f "$BACKUP_FILE"
  exit 1
fi

echo "Backup integrity verified: ok"

# Prune old backups, keeping only the most recent $MAX_BACKUPS
BACKUP_COUNT="$(ls -1t "$BACKUP_DIR"/tunnelpilot-*.db 2>/dev/null | wc -l)"
if (( BACKUP_COUNT > MAX_BACKUPS )); then
  ls -1t "$BACKUP_DIR"/tunnelpilot-*.db | tail -n +"$((MAX_BACKUPS + 1))" | xargs -r rm -f
  echo "Pruned old backups, retained latest $MAX_BACKUPS copies."
fi

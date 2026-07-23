#!/usr/bin/env bash
# EntropicMem Backup — Google Drive via rclone
# Usage: ./entropicmem_backup.sh
# Scheduled daily via cron
#
# Env overrides:
#   HERMES_HOME     (default: $HOME/.hermes)
#   RCLONE_REMOTE   (default: mygdrive)
#   RCLONE_PATH     (default: hermes-backups/entropicmem)
#
# Uses /tmp staging to avoid rclone v1.74.x .db bug.
# DO NOT point rclone at ~/.hermes/backups/ directly.

set -eu
# NOTE: deliberately NOT using pipefail — the rclone .db bug causes spurious
# pipe failures; we check return codes explicitly instead.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
RCLONE_REMOTE="${RCLONE_REMOTE:-mygdrive}"
RCLONE_PATH="${RCLONE_PATH:-hermes-backups/entropicmem}"
ENTROPICMEM_DIR="$HERMES_HOME/entropicmem"
BACKUP_DIR="$HERMES_HOME/backups"
TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

# Ensure backup dir exists
mkdir -p "$BACKUP_DIR"

# ── 1. Verify data exists ──────────────────────────────────
[ -d "$ENTROPICMEM_DIR" ] || fail "EntropicMem dir missing: $ENTROPICMEM_DIR"
[ -f "$ENTROPICMEM_DIR/memory.db" ] || fail "memory.db missing: $ENTROPICMEM_DIR/memory.db"

# ── 2. Tar+gzip the three data paths ───────────────────────
ARCHIVE="entropicmem_$TIMESTAMP.tar.gz"
log "Creating archive: $ARCHIVE"

tar_err="$(mktemp)"
tar_exit=0

tar -czf "$BACKUP_DIR/$ARCHIVE" \
    -C "$HERMES_HOME" \
    entropicmem/memory.db \
    entropicmem/index.db \
    entropicmem/vault/ \
    2>"$tar_err" || tar_exit=$?

if [ "$tar_exit" -ne 0 ]; then
    # Only treat missing index.db or vault as expected/optional
    if grep -q "entropicmem/index.db" "$tar_err" || grep -q "entropicmem/vault" "$tar_err"; then
        log "WARN: partial archive (index.db or vault missing), backing up memory.db only"
        rm -f "$tar_err"
        tar -czf "$BACKUP_DIR/$ARCHIVE" \
            -C "$HERMES_HOME" \
            entropicmem/memory.db
    else
        log "ERROR: tar failed while creating archive: $ARCHIVE"
        cat "$tar_err" >&2
        rm -f "$tar_err"
        fail "Archive creation failed (tar exit code: $tar_exit)"
    fi
else
    rm -f "$tar_err"
fi

ARCHIVE_SIZE=$(stat -c%s "$BACKUP_DIR/$ARCHIVE" 2>/dev/null || stat -f%z "$BACKUP_DIR/$ARCHIVE" 2>/dev/null || echo "unknown")
log "Archive size: $ARCHIVE_SIZE bytes"

# ── 3. Upload via rclone (stage through mktemp) ────────────
STAGE="$(mktemp "/tmp/entropicmem_backup_XXXXXX.tar.gz")"
cp "$BACKUP_DIR/$ARCHIVE" "$STAGE"
log "Uploading to $RCLONE_REMOTE:$RCLONE_PATH/ ..."
if rclone copy "$STAGE" "$RCLONE_REMOTE:$RCLONE_PATH/" 2>&1; then
    log "Upload complete"
else
    rm -f "$STAGE"
    fail "rclone upload failed"
fi
rm -f "$STAGE"

# ── 4. Keep last 7 daily backups locally ────────────────────
CLEANED=$(ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz 2>/dev/null | tail -n +8 | wc -l)
ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm
[ "$CLEANED" -gt 0 ] && log "Cleaned $CLEANED old local backup(s)"

# ── 5. Verify remote ────────────────────────────────────────
REMOTE_COUNT=$(rclone ls "$RCLONE_REMOTE:$RCLONE_PATH/" 2>/dev/null | wc -l || echo "0")
log "Remote archives: $REMOTE_COUNT"

log "EntropicMem backup complete: $ARCHIVE"

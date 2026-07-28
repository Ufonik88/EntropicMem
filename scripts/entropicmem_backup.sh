#!/usr/bin/env bash
# EntropicMem Backup — encrypted archive → Google Drive via rclone
# Usage: ./entropicmem_backup.sh
# Scheduled daily via cron
#
# Env overrides:
#   HERMES_HOME     (default: $HOME/.hermes)
#   RCLONE_REMOTE   (default: mygdrive)
#   RCLONE_PATH     (default: hermes-backups/entropicmem)
#   ENTROPICMEM_BACKUP_KEY_FILE (default: $HERMES_HOME/entropicmem/.backup_key)
#
# Uses /tmp staging to avoid rclone v1.74.x .db bug.
# DO NOT point rclone at ~/.hermes/backups/ directly.
# Archives are AES-256-CBC encrypted before upload (OpenSSL pbkdf2).

set -eu
# NOTE: deliberately NOT using pipefail — the rclone .db bug causes spurious
# pipe failures; we check return codes explicitly instead.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
RCLONE_REMOTE="${RCLONE_REMOTE:-mygdrive}"
RCLONE_PATH="${RCLONE_PATH:-hermes-backups/entropicmem}"
RCLONE_BIN="/home/linuxbrew/.linuxbrew/bin/rclone"
OPENSSL_BIN="$(command -v openssl || echo /usr/bin/openssl)"
ENTROPICMEM_DIR="$HERMES_HOME/entropicmem"
BACKUP_DIR="$HERMES_HOME/backups"
KEY_FILE="${ENTROPICMEM_BACKUP_KEY_FILE:-$ENTROPICMEM_DIR/.backup_key}"
TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true
chmod 700 "$ENTROPICMEM_DIR" 2>/dev/null || true

# ── 0. Ensure backup key ───────────────────────────────────
if [ ! -f "$KEY_FILE" ]; then
  log "Generating backup key: $KEY_FILE"
  "$OPENSSL_BIN" rand -out "$KEY_FILE" 32
  chmod 600 "$KEY_FILE"
fi
chmod 600 "$KEY_FILE"

# ── 1. Verify data exists ──────────────────────────────────
[ -d "$ENTROPICMEM_DIR" ] || fail "EntropicMem dir missing: $ENTROPICMEM_DIR"
[ -f "$ENTROPICMEM_DIR/memory.db" ] || fail "memory.db missing: $ENTROPICMEM_DIR/memory.db"

# ── 2. Tar+gzip the three data paths ───────────────────────
ARCHIVE="entropicmem_$TIMESTAMP.tar.gz"
ENC_ARCHIVE="${ARCHIVE}.enc"
log "Creating archive: $ARCHIVE"

TAR_FILES=("entropicmem/memory.db")
if [ -f "$ENTROPICMEM_DIR/index.db" ]; then
  TAR_FILES+=("entropicmem/index.db")
fi
if [ -d "$ENTROPICMEM_DIR/vault" ]; then
  TAR_FILES+=("entropicmem/vault/")
fi

if ! tar -czf "$BACKUP_DIR/$ARCHIVE" -C "$HERMES_HOME" "${TAR_FILES[@]}"; then
  fail "Archive creation failed"
fi
chmod 600 "$BACKUP_DIR/$ARCHIVE"

ARCHIVE_SIZE=$(stat -c%s "$BACKUP_DIR/$ARCHIVE" 2>/dev/null || stat -f%z "$BACKUP_DIR/$ARCHIVE" 2>/dev/null || echo "unknown")
log "Archive size: $ARCHIVE_SIZE bytes"

# ── 3. Encrypt archive ─────────────────────────────────────
log "Encrypting archive → $ENC_ARCHIVE"
if ! "$OPENSSL_BIN" enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
    -in "$BACKUP_DIR/$ARCHIVE" \
    -out "$BACKUP_DIR/$ENC_ARCHIVE" \
    -pass "file:$KEY_FILE"; then
  rm -f "$BACKUP_DIR/$ENC_ARCHIVE"
  fail "Encryption failed"
fi
chmod 600 "$BACKUP_DIR/$ENC_ARCHIVE"
# Drop plaintext local tar after successful encrypt
rm -f "$BACKUP_DIR/$ARCHIVE"

# ── 4. Upload ciphertext via rclone (stage through mktemp) ─
STAGE="$(mktemp "/tmp/entropicmem_backup_XXXXXX.tar.gz.enc")"
cp "$BACKUP_DIR/$ENC_ARCHIVE" "$STAGE"
chmod 600 "$STAGE"
log "Uploading to $RCLONE_REMOTE:$RCLONE_PATH/ ..."
if "$RCLONE_BIN" copy "$STAGE" "$RCLONE_REMOTE:$RCLONE_PATH/" 2>&1; then
  log "Upload complete"
else
  rm -f "$STAGE"
  fail "rclone upload failed"
fi
rm -f "$STAGE"

# ── 5. Keep last 7 encrypted local backups ─────────────────
CLEANED=$(ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz.enc 2>/dev/null | tail -n +8 | wc -l)
ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz.enc 2>/dev/null | tail -n +8 | xargs -r rm
# Also purge any leftover plaintext tars
ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz 2>/dev/null | xargs -r rm -f
[ "$CLEANED" -gt 0 ] && log "Cleaned $CLEANED old local encrypted backup(s)"

# ── 6. Verify remote ────────────────────────────────────────
REMOTE_COUNT=$("$RCLONE_BIN" ls "$RCLONE_REMOTE:$RCLONE_PATH/" 2>/dev/null | wc -l || echo "0")
log "Remote archives: $REMOTE_COUNT"

log "EntropicMem backup complete: $ENC_ARCHIVE"

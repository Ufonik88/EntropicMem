#!/usr/bin/env bash
# EntropicMem Backup Restore
#
# Usage:
#   ./entropicmem_restore.sh                          # Restore from latest backup
#   ./entropicmem_restore.sh --archive FILE           # Restore from specific archive
#   ./entropicmem_restore.sh --dry-run                # Show what would happen
#   ./entropicmem_restore.sh --list                   # List available backups
#
# Restores memory.db, index.db, and vault from a tar.gz backup archive.
# Creates a safety backup of current data before restore.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENTROPICMEM_DIR="$HERMES_HOME/entropicmem"
BACKUP_DIR="$HERMES_HOME/backups"

# ── defaults ────────────────────────────────────────────────────────────────
DRY_RUN=false
LIST_ONLY=false
ARCHIVE=""
ERRORS=0

# ── parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --list)    LIST_ONLY=true; shift ;;
    --archive) ARCHIVE="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--list] [--archive FILE]"
      echo "  --dry-run       Show what would happen without making changes"
      echo "  --list          List available backups"
      echo "  --archive FILE  Restore from specific archive"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── helpers ─────────────────────────────────────────────────────────────────
log()  { echo "[RESTORE] $*"; }
warn() { echo "[RESTORE] WARNING: $*" >&2; }
fail() { echo "[RESTORE] ERROR: $*" >&2; exit 1; }

list_backups() {
  log "Available backups in $BACKUP_DIR:"
  if ls "$BACKUP_DIR"/entropicmem_*.tar.gz 1>/dev/null 2>&1; then
    ls -lht "$BACKUP_DIR"/entropicmem_*.tar.gz | head -10
  else
    log "No backups found in $BACKUP_DIR"
  fi
}

find_latest() {
  local latest
  latest=$(ls -1t "$BACKUP_DIR"/entropicmem_*.tar.gz 2>/dev/null | head -1)
  if [[ -z "$latest" ]]; then
    fail "No backups found in $BACKUP_DIR"
  fi
  echo "$latest"
}

verify_archive() {
  local archive="$1"
  if [[ ! -f "$archive" ]]; then
    fail "Archive not found: $archive"
  fi
  
  # Verify it's a valid gzip
  if ! gzip -t "$archive" 2>/dev/null; then
    fail "Archive is not valid gzip: $archive"
  fi
  
  # Verify it contains expected files
  local contents
  contents=$(tar -tzf "$archive" 2>/dev/null || echo "")
  if echo "$contents" | grep -q "entropicmem/memory.db"; then
    log "Archive verified: contains memory.db"
  else
    fail "Archive does not contain memory.db"
  fi
}

safety_backup() {
  if [[ ! -d "$ENTROPICMEM_DIR" ]]; then
    return
  fi
  
  local safety_dir="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S)"
  log "Creating safety backup: $safety_dir"
  
  mkdir -p "$safety_dir"
  cp "$ENTROPICMEM_DIR/memory.db" "$safety_dir/" 2>/dev/null || true
  cp "$ENTROPICMEM_DIR/index.db" "$safety_dir/" 2>/dev/null || true
  cp -r "$ENTROPICMEM_DIR/vault" "$safety_dir/" 2>/dev/null || true
  
  log "Safety backup created: $safety_dir"
}

restore_archive() {
  local archive="$1"
  
  if $DRY_RUN; then
    log "[DRY RUN] Would restore from: $archive"
    log "[DRY RUN] Contents:"
    tar -tzf "$archive" | head -20
    return 0
  fi
  
  # Safety backup
  safety_backup
  
  # Extract to temp directory
  local tmpdir
  tmpdir=$(mktemp -d)
  
  log "Extracting archive..."
  tar -xzf "$archive" -C "$tmpdir"
  
  # Restore files
  if [[ -d "$tmpdir/entropicmem" ]]; then
    mkdir -p "$ENTROPICMEM_DIR"
    
    if [[ -f "$tmpdir/entropicmem/memory.db" ]]; then
      cp "$tmpdir/entropicmem/memory.db" "$ENTROPICMEM_DIR/"
      log "Restored memory.db"
    fi
    
    if [[ -f "$tmpdir/entropicmem/index.db" ]]; then
      cp "$tmpdir/entropicmem/index.db" "$ENTROPICMEM_DIR/"
      log "Restored index.db"
    fi
    
    if [[ -d "$tmpdir/entropicmem/vault" ]]; then
      cp -r "$tmpdir/entropicmem/vault" "$ENTROPICMEM_DIR/"
      log "Restored vault/"
    fi
  fi
  
  rm -rf "$tmpdir"
  
  # Verify restore
  verify_restore
}

verify_restore() {
  log "Verifying restore..."
  local issues=0
  
  if [[ -f "$ENTROPICMEM_DIR/memory.db" ]]; then
    local count
    count=$(sqlite3 "$ENTROPICMEM_DIR/memory.db" "SELECT COUNT(*) FROM facts;" 2>/dev/null || echo "0")
    if [[ "$count" -gt 0 ]]; then
      log "  ✓ memory.db: $count facts"
    else
      warn "  ✗ memory.db: empty or unreadable"
      ((issues++)) || true
    fi
  else
    warn "  ✗ memory.db: missing"
    ((issues++)) || true
  fi
  
  if [[ -f "$ENTROPICMEM_DIR/index.db" ]]; then
    log "  ✓ index.db: exists"
  else
    warn "  ✗ index.db: missing"
    ((issues++)) || true
  fi
  
  if [[ -d "$ENTROPICMEM_DIR/vault" ]]; then
    local note_count
    note_count=$(find "$ENTROPICMEM_DIR/vault" -name "*.md" | wc -l)
    log "  ✓ vault/: $note_count notes"
  else
    warn "  ✗ vault/: missing"
    ((issues++)) || true
  fi
  
  if [[ $issues -eq 0 ]]; then
    log "Restore verification PASSED"
    return 0
  else
    warn "Restore verification found $issues issues"
    return 1
  fi
}

# ── main ────────────────────────────────────────────────────────────────────
log "EntropicMem Backup Restore"
log "HERMES_HOME: $HERMES_HOME"
echo

# List mode
if $LIST_ONLY; then
  list_backups
  exit 0
fi

# Find archive
if [[ -z "$ARCHIVE" ]]; then
  log "No archive specified, using latest..."
  ARCHIVE=$(find_latest)
fi

log "Archive: $ARCHIVE"
verify_archive "$ARCHIVE"

# Restore
restore_archive "$ARCHIVE"

echo
log "Restore complete."

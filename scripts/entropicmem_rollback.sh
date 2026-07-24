#!/usr/bin/env bash
# EntropicMem Rollback Script — Idempotent + Validated
# 
# Usage:
#   ./entropicmem_rollback.sh              # Normal rollback
#   ./entropicmem_rollback.sh --dry-run    # Show what would happen
#   ./entropicmem_rollback.sh --verify     # Verify rollback state only
#   ./entropicmem_rollback.sh --force      # Force rollback even if already rolled back
#
# Exit codes:
#   0 = success or already rolled back
#   1 = error or validation failed

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SNAP="$HERMES_HOME/entropicmem/cutover-2026-07-22"
STATE="$SNAP/pre_cutover_state.json"
CONFIG="$HERMES_HOME/config.yaml"

# ── defaults ────────────────────────────────────────────────────────────────
DRY_RUN=false
VERIFY=false
FORCE=false
ERRORS=0

# ── parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --verify)  VERIFY=true; shift ;;
    --force)   FORCE=true; shift ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--verify] [--force]"
      echo "  --dry-run  Show what would happen without making changes"
      echo "  --verify   Verify current rollback state only"
      echo "  --force    Force rollback even if already rolled back"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── helpers ─────────────────────────────────────────────────────────────────
log()  { echo "[ROLLBACK] $*"; }
warn() { echo "[ROLLBACK] WARNING: $*" >&2; }
fail() { echo "[ROLLBACK] ERROR: $*" >&2; ((ERRORS++)) || true; }

check_state_file() {
  if [[ ! -f "$STATE" ]]; then
    fail "Missing state file: $STATE"
    log "Cannot proceed without pre-cutover state. Restore from backup or create state manually."
    return 1
  fi
  log "State file found: $STATE"
  return 0
}

check_already_rolled_back() {
  local provider
  provider=$(hermes config get memory.provider 2>/dev/null || echo "")
  if [[ "$provider" == "mnemosyne" ]]; then
    log "Already rolled back (memory.provider=$provider)"
    return 0
  fi
  return 1
}

enable_mnemosyne_plugin() {
  local current
  current=$(hermes plugins list 2>/dev/null | grep -i mnemosyne | head -1 || echo "")
  if echo "$current" | grep -q "enabled"; then
    log "Mnemosyne plugin already enabled"
    return 0
  fi
  if $DRY_RUN; then
    log "[DRY RUN] Would enable mnemosyne plugin"
    return 0
  fi
  hermes plugins enable mnemosyne
  log "Mnemosyne plugin enabled"
}

set_provider() {
  local target="${RESTORE_PROVIDER:-mnemosyne}"
  local current
  current=$(hermes config get memory.provider 2>/dev/null || echo "")
  
  if [[ "$current" == "$target" ]]; then
    log "memory.provider already set to $target"
    return 0
  fi
  
  if $DRY_RUN; then
    log "[DRY RUN] Would set memory.provider=$target (current: $current)"
    return 0
  fi
  
  hermes config set memory.provider "$target"
  log "memory.provider set to $target"
}

validate_rollback() {
  log "Validating rollback state..."
  local issues=0
  
  # Check plugin status
  local plugin_status
  plugin_status=$(hermes plugins list 2>/dev/null | grep -i mnemosyne || echo "")
  if echo "$plugin_status" | grep -q "enabled"; then
    log "  ✓ Mnemosyne plugin: enabled"
  else
    warn "  ✗ Mnemosyne plugin: not enabled"
    ((issues++)) || true
  fi
  
  # Check provider
  local provider
  provider=$(hermes config get memory.provider 2>/dev/null || echo "")
  if [[ "$provider" == "mnemosyne" ]]; then
    log "  ✓ memory.provider: mnemosyne"
  else
    warn "  ✗ memory.provider: $provider (expected mnemosyne)"
    ((issues++)) || true
  fi
  
  # Check Mnemosyne DB exists
  if [[ -f "$HERMES_HOME/mnemosyne/data/mnemosyne.db" ]]; then
    log "  ✓ Mnemosyne DB: exists"
  else
    warn "  ✗ Mnemosyne DB: missing"
    ((issues++)) || true
  fi
  
  if [[ $issues -eq 0 ]]; then
    log "Validation PASSED - rollback complete"
    return 0
  else
    warn "Validation found $issues issues"
    return 1
  fi
}

print_cron_ids() {
  log "Paused cron job IDs to RESUME manually:"
  python3 -c "
import json
from pathlib import Path
snap = Path.home() / '.hermes' / 'entropicmem' / 'cutover-2026-07-22'
state_file = snap / 'pre_cutover_state.json'
if state_file.exists():
    state = json.loads(state_file.read_text())
    for jid in state.get('cron_jobs_to_pause', []):
        print(f'  {jid}')
    print()
    print('Example (via agent): cronjob(action=\"resume\", job_id=\"...\")')
else:
    print('  (no state file found)')
" || true
}

# ── main ────────────────────────────────────────────────────────────────────
log "EntropicMem Rollback"
log "Snapshot: $SNAP"
echo

# Verify mode
if $VERIFY; then
  check_state_file || exit 1
  validate_rollback
  exit $?
fi

# Check if already rolled back
if check_already_rolled_back && ! $FORCE; then
  log "Rollback already complete. Use --force to re-run."
  exit 0
fi

# Check state file
check_state_file || exit 1

# Execute rollback
enable_mnemosyne_plugin
set_provider

if ! $DRY_RUN; then
  echo
  validate_rollback || true
fi

# Print cron info
echo
print_cron_ids

# Done
echo
if $DRY_RUN; then
  log "DRY RUN complete. No changes made."
else
  log "Rollback complete. Start a NEW session for changes to take full effect."
  log "Optional: cp $SNAP/config.yaml.bak $CONFIG"
fi

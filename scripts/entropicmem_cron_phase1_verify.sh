#!/usr/bin/env bash
set -euo pipefail
OUT=$(python3 "$HOME/.hermes/scripts/entropicmem_cron_remember.py" "Phase1 cron-context verify $(date -Iseconds)" --domain Knowledge --importance 0.85 --source phase1_cron_context)
echo "$OUT"
echo "$OUT" | grep -q '"verified_recall": true'
echo "$OUT" | grep -q '"ok": true'
echo "PHASE1_CRON_VERIFY_OK"

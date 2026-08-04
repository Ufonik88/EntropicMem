#!/usr/bin/env bash
# entropicmem_index_refresh.sh — vault index freshness watchdog (v2.1.8).
#
# index.db is only written by `entropicmem init`, the remember→vault path,
# and `project_to_vault`. Notes written by anything else (wiki.py, Obsidian,
# vault auto-commit) never reach it, so the health check's index-freshness
# check goes WARN and the stability gate can never pass.
#
# This watchdog rebuilds the index when the vault has notes newer than the
# last index build. Silent (no output) when the index is already fresh —
# designed for a no_agent cron that delivers stdout verbatim.
#
# Paths are hard-pinned to the dataset the health check monitors
# (~/.hermes/entropicmem/vault → index.db). Do NOT read
# $ENTROPICMEM_VAULT_PATH/$ENTROPICMEM_INDEX_DB here: ~/.hermes/.env has
# historically carried stale entries pointing at dead /tmp dirs, and any
# process started before the env was cleaned still carries them in memory.
# The CLI fallback can also land on the Obsidian vault, a different dataset
# from the one index.db tracks.
set -u

VAULT="$HOME/.hermes/entropicmem/vault"
INDEX_DB="$HOME/.hermes/entropicmem/index.db"
CLI="$HOME/Documents/Coding Projects/EntropicMem/skills/entropicmem/scripts/entropicmem.py"

if [ ! -d "$VAULT" ]; then
  echo "index-refresh: vault missing: $VAULT"
  exit 1
fi
if [ ! -f "$CLI" ]; then
  echo "index-refresh: CLI missing: $CLI"
  exit 1
fi

# Newest vault note mtime vs index.db mtime. Fresh index → stay silent.
newest_note="$(find "$VAULT" -name '*.md' -printf '%T@\n' 2>/dev/null | sort -n | tail -1)"
newest_note="${newest_note%.*}"
if [ -z "${newest_note:-}" ]; then
  exit 0  # empty vault, nothing to index
fi

if [ -f "$INDEX_DB" ]; then
  index_mtime="$(stat -c '%Y' "$INDEX_DB")"
  if [ "$index_mtime" -ge "${newest_note:-0}" ]; then
    exit 0  # index is current — silent success
  fi
fi

# Stale (or missing): rebuild. The CLI env overrides pin the dataset.
out="$(ENTROPICMEM_VAULT_PATH="$VAULT" ENTROPICMEM_INDEX_DB="$INDEX_DB" \
  python3 "$CLI" index rebuild 2>&1)"
rc=$?
if [ $rc -ne 0 ]; then
  echo "index-refresh FAILED (exit $rc): $out"
  exit $rc
fi
echo "index-refresh: $out"

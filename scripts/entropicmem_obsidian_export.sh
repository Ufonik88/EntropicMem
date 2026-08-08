#!/usr/bin/env bash
# entropicmem_obsidian_export.sh — mirror EntropicMem vault notes into the
# Obsidian vault (v2.2.0 G6).
#
# The EntropicMem runtime vault (~/.hermes/entropicmem/vault) is the engine's
# source of truth. This cron mirrors new/updated notes into
# ~/Documents/Obsidian Vault/EntropicMem/ (humanized filenames preserved) so
# the human second brain sees fresh EntropicMem content without the engine
# depending on Obsidian.
#
# no_agent cron pattern: silent (empty stdout) when nothing changed; prints a
# one-line summary when notes were copied.
set -u

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SRC="$HERMES_HOME/entropicmem/vault"
OBSIDIAN="${OBSIDIAN_VAULT_PATH:-$HOME/Documents/Obsidian Vault}"
DEST="$OBSIDIAN/EntropicMem"

if [ ! -d "$SRC" ]; then
  echo "obsidian-export: EntropicMem vault missing: $SRC" >&2
  exit 1
fi
if [ ! -d "$OBSIDIAN" ]; then
  echo "obsidian-export: Obsidian vault missing: $OBSIDIAN" >&2
  exit 1
fi

mkdir -p "$DEST"
# Mirror all .md files (and preserve relative folders). --ignore-existing is
# NOT used: updated engine notes must overwrite stale copies. Delete nothing
# in Obsidian (engine vault is the source; Obsidian may hold human edits).
copied=$(rsync -a --include='*/' --include='*.md' --exclude='*' \
  "$SRC/" "$DEST/" 2>/dev/null)

# Count changed files for the summary line.
before=$(find "$DEST" -name '*.md' | wc -l)
rsync -a --include='*/' --include='*.md' --exclude='*' "$SRC/" "$DEST/"
after=$(find "$DEST" -name '*.md' | wc -l)

if [ "$before" != "$after" ] || [ -n "$copied" ]; then
  echo "obsidian-export: $after notes mirrored to $DEST"
fi
# silent when nothing changed
exit 0

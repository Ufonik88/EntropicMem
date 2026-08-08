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
# Single rsync pass with --itemize-changes; grep keeps only the itemized
# transfer lines (11-char status field + filename), excluding the
# "sending incremental file list" header, so `changes` is non-empty exactly
# when a note was transferred.
changes=$(rsync -a --itemize-changes --include='*/' --include='*.md' --exclude='*' \
  "$SRC/" "$DEST/" 2>/dev/null | grep -E '^[^ ]{11} ' || true)

if [ -n "$changes" ]; then
  count=$(find "$DEST" -name '*.md' | wc -l)
  echo "obsidian-export: $count notes mirrored to $DEST"
fi
# silent when nothing changed
exit 0

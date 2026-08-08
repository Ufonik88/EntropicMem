#!/usr/bin/env bash
set -u

# v2.2.0 G2: the server refresh rebuilds index.db from the vault FIRST
# (its rebuild() deletes graph_edges), so triple extraction + edge sync must
# run AFTER the refresh — otherwise the rebuild wipes the synced triple edges
# and the health check's split-brain check goes WARN.
URL="${ENTROPICMEM_GRAPH_URL:-http://127.0.0.1:8075/refresh}"
TIMEOUT="${ENTROPICMEM_GRAPH_TIMEOUT:-60}"
ENV_FILE="${ENTROPICMEM_GRAPH_ENV:-$HOME/.hermes/entropicmem/graph_server.env}"
if [ -z "${ENTROPICMEM_GRAPH_TOKEN:-}" ] && [ -f "$ENV_FILE" ]; then
  ENTROPICMEM_GRAPH_TOKEN="$(grep -E '^ENTROPICMEM_GRAPH_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
fi
if [ -z "${ENTROPICMEM_GRAPH_TOKEN:-}" ]; then
  echo 'token missing' >&2
  exit 1
fi
if ! curl -fsS --max-time 5 -o /dev/null "${URL%/refresh}/health"; then
  echo 'health failed' >&2
  exit 1
fi
out="$(curl -fsS --max-time "$TIMEOUT" -X POST "$URL" -H "X-Entropicmem-Token: ${ENTROPICMEM_GRAPH_TOKEN}")" || exit $?
echo "$out"

# v2.2.0 G2: extract + sync triples AFTER the refresh (see header comment).
CLI_PATH="$HOME/.hermes/skills/entropicmem/scripts/entropicmem.py"
if [ -f "$CLI_PATH" ]; then
  python3 "$CLI_PATH" triple extract >/dev/null 2>&1 || true
  python3 "$HOME/.hermes/scripts/entropicmem_triples_sync.py" >/dev/null 2>&1 || true
fi

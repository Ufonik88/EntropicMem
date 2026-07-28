#!/usr/bin/env bash
set -u
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

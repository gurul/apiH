#!/usr/bin/env bash
# Demo: health -> compile -> run (http) -> run force_path=agent.
# Requires the server (uv run uvicorn app.main:app --port 8000) and jq.
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
SLUG="hn-top-stories"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (brew install jq / apt install jq)" >&2
  exit 1
fi

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

step "GET /health"
curl -s "$BASE/health" | jq

step "POST /v1/workflows/$SLUG/compile"
curl -s -X POST "$BASE/v1/workflows/$SLUG/compile" \
  -H 'content-type: application/json' \
  -d '{"engine": "auto", "activate": true}' | jq

step "POST /v1/workflows/$SLUG/run  (default: http path)"
RUN_HTTP=$(curl -s -X POST "$BASE/v1/workflows/$SLUG/run" \
  -H 'content-type: application/json' \
  -d '{"input": {"limit": 5}}')
echo "$RUN_HTTP" | jq
echo "$RUN_HTTP" | jq -r '"path=\(.meta.path)  latency_ms=\(.meta.latency_ms)"'

step "POST /v1/workflows/$SLUG/run  (force_path=agent)"
RUN_AGENT=$(curl -s -X POST "$BASE/v1/workflows/$SLUG/run" \
  -H 'content-type: application/json' \
  -d '{"input": {"limit": 3}, "force_path": "agent"}')
echo "$RUN_AGENT" | jq
echo "$RUN_AGENT" | jq -r '"path=\(.meta.path)  latency_ms=\(.meta.latency_ms)"'

step "Contrast"
jq -n --argjson h "$RUN_HTTP" --argjson a "$RUN_AGENT" \
  '{http: {path: $h.meta.path, latency_ms: $h.meta.latency_ms},
    agent: {path: $a.meta.path, latency_ms: $a.meta.latency_ms}}'

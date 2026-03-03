#!/usr/bin/env bash
# HydroMAS + EvoMap Evolution Bridge
# Runs evolver on HydroMAS logs and generates evolution prompts
# Usage: bash hydromas_evolve.sh [run|solidify|status|loop]

set -euo pipefail

START_TS=$(date +%s)

resolve_notify_target() {
  if [[ -n "${HYDROMAS_USER_OPENID:-}" ]]; then
    printf '%s' "$HYDROMAS_USER_OPENID"
  elif [[ -n "${OPENCLAW_TRIGGER_USER_OPENID:-}" ]]; then
    printf '%s' "$OPENCLAW_TRIGGER_USER_OPENID"
  elif [[ -n "${OPENCLAW_USER_OPENID:-}" ]]; then
    printf '%s' "$OPENCLAW_USER_OPENID"
  elif [[ -n "${OPENCLAW_SENDER_ID:-}" ]]; then
    printf '%s' "$OPENCLAW_SENDER_ID"
  elif [[ -n "${FEISHU_DEFAULT_OPENID:-}" ]]; then
    printf '%s' "$FEISHU_DEFAULT_OPENID"
  else
    printf ''
  fi
}

notify_feishu() {
  local status="$1"
  local summary="$2"
  local duration="$3"
  local target
  target="$(resolve_notify_target)"
  local payload
  payload=$(printf '{"status":"%s","summary":"%s","duration":%s}' \
    "$status" "${summary//\"/\\\"}" "$duration")

  if [[ -n "$target" ]]; then
    openclaw message send --channel feishu --target "$target" --message "$payload" >/dev/null 2>&1 && return 0
  fi
  openclaw system event --text "$payload" --mode now >/dev/null 2>&1 || true
}

EVOLVER_DIR="/home/admin/evolver"
HYDROMAS_DIR="/home/admin/hydromas"
WORKSPACE="/home/admin/.openclaw/workspace"

export MEMORY_DIR="${WORKSPACE}/memory"
export EVOLUTION_DIR="${WORKSPACE}/memory/evolution"
export EVOLVER_LOGS_DIR="${WORKSPACE}/logs"
export EVOLVE_STRATEGY="${EVOLVE_STRATEGY:-balanced}"
export EVOLVE_LOAD_MAX=10.0
export EVOLVE_REPORT_TOOL=message

CMD="${1:-run}"

on_exit() {
  local exit_code=$?
  local end_ts
  end_ts=$(date +%s)
  local duration=$((end_ts - START_TS))
  if [[ $exit_code -eq 0 ]]; then
    notify_feishu "success" "HydroMAS evolve script succeeded: $CMD" "$duration"
  else
    notify_feishu "failed" "HydroMAS evolve script failed (exit=${exit_code}): $CMD" "$duration"
  fi
}
trap on_exit EXIT

case "$CMD" in
  run)
    echo "[HydroMAS-EvoMap] Running evolution cycle..."
    cd "$EVOLVER_DIR" && node index.js run
    ;;
  solidify)
    shift
    echo "[HydroMAS-EvoMap] Solidifying evolution..."
    cd "$EVOLVER_DIR" && node index.js solidify "$@"
    ;;
  status)
    echo "[HydroMAS-EvoMap] Evolution status:"
    echo "  Evolver: ${EVOLVER_DIR}"
    echo "  HydroMAS: ${HYDROMAS_DIR}"
    echo "  Strategy: ${EVOLVE_STRATEGY}"
    echo "  Logs: ${EVOLVER_LOGS_DIR}"
    # Show recent evolution events
    if [ -f "${EVOLVER_DIR}/assets/gep/events.jsonl" ]; then
      EVENTS=$(wc -l < "${EVOLVER_DIR}/assets/gep/events.jsonl")
      echo "  Events: ${EVENTS}"
      echo "  Last event:"
      tail -1 "${EVOLVER_DIR}/assets/gep/events.jsonl" | python3 -c "
import json,sys
try:
    e=json.loads(sys.stdin.read())
    print(f'    Intent: {e.get(\"intent\",\"?\")}')
    print(f'    Gene: {e.get(\"genes_used\",[\"?\"])[0]}')
    print(f'    Outcome: {e.get(\"outcome\",{}).get(\"status\",\"?\")}')
    print(f'    Time: {e.get(\"meta\",{}).get(\"at\",\"?\")}')
except: print('    (parse error)')
"
    else
      echo "  Events: 0 (no history)"
    fi
    # Show HydroMAS test status
    echo "  HydroMAS tests: $(cd ${HYDROMAS_DIR} && source .venv/bin/activate && python -m pytest -q 2>&1 | tail -1)"
    ;;
  loop)
    echo "[HydroMAS-EvoMap] Starting continuous evolution loop..."
    cd "$EVOLVER_DIR" && node index.js --loop
    ;;
  test)
    echo "[HydroMAS-EvoMap] Running HydroMAS E2E validation..."
    cd "$HYDROMAS_DIR" && source .venv/bin/activate
    python -m pytest -q 2>&1 | tail -3
    echo ""
    echo "API health:"
    curl -s http://localhost:8000/api/gateway/health | python3 -c "import json,sys; r=json.load(sys.stdin); print(f'  Status: {r[\"status\"]}, Agents: {r[\"agents_registered\"]}')" 2>&1
    ;;
  *)
    echo "Usage: $0 {run|solidify|status|loop|test}"
    exit 1
    ;;
esac

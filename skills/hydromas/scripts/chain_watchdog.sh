#!/usr/bin/env bash
set -euo pipefail

# HydroMAS/OpenClaw/Feishu chain watchdog with guarded auto-repair.
# Usage:
#   bash chain_watchdog.sh --notify-target "user:ou_xxx"
#   bash chain_watchdog.sh --notify-target "user:ou_xxx" --feishu-ping-target "user:ou_xxx"

HYDRO_HEALTH_URL="${HYDRO_HEALTH_URL:-http://127.0.0.1:8000/api/gateway/health}"
HYDRO_REPO="${HYDRO_REPO:-/home/admin/hydromas}"
HYDRO_LOG="${HYDRO_LOG:-/tmp/hydromas_uvicorn.log}"
AUDIT_SCRIPT="${AUDIT_SCRIPT:-/home/admin/.openclaw/workspace/skills/hydromas/scripts/codex_hydromas_audit.sh}"
STATE_FILE="${STATE_FILE:-/tmp/hydromas_chain_watchdog_state.env}"
MAIN_SESS_DIR="${MAIN_SESS_DIR:-/home/admin/.openclaw/agents/main/sessions}"

NOTIFY_TARGET="${NOTIFY_TARGET:-}"
NOTIFY_CHANNEL="${NOTIFY_CHANNEL:-feishu}"
FEISHU_PING_TARGET="${FEISHU_PING_TARGET:-}"

CODEX_COOLDOWN_SEC="${CODEX_COOLDOWN_SEC:-3600}"
FEISHU_PING_COOLDOWN_SEC="${FEISHU_PING_COOLDOWN_SEC:-1800}"
ERROR_THRESHOLD="${ERROR_THRESHOLD:-3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --notify-target) NOTIFY_TARGET="${2:-}"; shift 2 ;;
    --notify-channel) NOTIFY_CHANNEL="${2:-feishu}"; shift 2 ;;
    --feishu-ping-target) FEISHU_PING_TARGET="${2:-}"; shift 2 ;;
    --codex-cooldown-sec) CODEX_COOLDOWN_SEC="${2:-3600}"; shift 2 ;;
    --error-threshold) ERROR_THRESHOLD="${2:-3}"; shift 2 ;;
    *) echo "[watchdog] unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { echo "[watchdog] $*"; }

load_state() {
  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
  fi
  LAST_CODEX_TS="${LAST_CODEX_TS:-0}"
  LAST_FEISHU_PING_TS="${LAST_FEISHU_PING_TS:-0}"
  LAST_SCANNED_FILE="${LAST_SCANNED_FILE:-}"
  LAST_SCANNED_LINE="${LAST_SCANNED_LINE:-0}"
}

save_state() {
  cat > "$STATE_FILE" <<STATE
LAST_CODEX_TS=${LAST_CODEX_TS}
LAST_FEISHU_PING_TS=${LAST_FEISHU_PING_TS}
LAST_SCANNED_FILE=${LAST_SCANNED_FILE}
LAST_SCANNED_LINE=${LAST_SCANNED_LINE}
STATE
}

notify() {
  local msg="$1"
  [[ -z "$msg" ]] && return 0
  [[ -z "$NOTIFY_TARGET" ]] && return 0
  openclaw message send --channel "$NOTIFY_CHANNEL" --target "$NOTIFY_TARGET" --message "$msg" >/dev/null 2>&1 || true
}

restart_hydromas() {
  log "restarting hydromas uvicorn"
  pkill -f "uvicorn web.app:app --host 0.0.0.0 --port 8000" >/dev/null 2>&1 || true
  cd "$HYDRO_REPO"
  nohup .venv/bin/python -m uvicorn web.app:app --host 0.0.0.0 --port 8000 > "$HYDRO_LOG" 2>&1 &
  sleep 2
}

hydro_health_ok() {
  local out
  out="$(curl -fsS --max-time 5 "$HYDRO_HEALTH_URL" 2>/dev/null || true)"
  [[ -n "$out" ]] && echo "$out" | rg -q '"status"\s*:\s*"?healthy"?'
}

openclaw_health_ok() {
  local out
  out="$(openclaw gateway call health --json 2>/dev/null || true)"
  [[ -n "$out" ]] && echo "$out" | rg -q '"ok"\s*:\s*true|"agents"\s*:'
}

feishu_ping() {
  local target="$FEISHU_PING_TARGET"
  [[ -z "$target" ]] && return 0
  local now
  now="$(date +%s)"
  if (( now - LAST_FEISHU_PING_TS < FEISHU_PING_COOLDOWN_SEC )); then
    return 0
  fi
  openclaw message send --channel feishu --target "$target" --message "HydroMAS链路心跳: $(date '+%F %T')" >/dev/null 2>&1 || return 1
  LAST_FEISHU_PING_TS="$now"
  save_state
  return 0
}

recent_new_error_score() {
  local latest
  latest="$(ls -1t "$MAIN_SESS_DIR"/*.jsonl 2>/dev/null | head -n 1 || true)"
  [[ -z "$latest" ]] && { echo 0; return 0; }

  local total
  total="$(wc -l < "$latest" | tr -d ' ')"
  total="${total:-0}"

  # First run baseline: do not score historical lines.
  if [[ -z "$LAST_SCANNED_FILE" ]]; then
    LAST_SCANNED_FILE="$latest"
    LAST_SCANNED_LINE="$total"
    save_state
    echo 0
    return 0
  fi

  local start=1
  if [[ "$latest" == "$LAST_SCANNED_FILE" ]]; then
    if (( LAST_SCANNED_LINE >= 1 )) && (( LAST_SCANNED_LINE < total )); then
      start=$((LAST_SCANNED_LINE + 1))
    elif (( LAST_SCANNED_LINE >= total )); then
      # No new lines or file rotated/truncated.
      LAST_SCANNED_LINE="$total"
      save_state
      echo 0
      return 0
    fi
  fi

  local score
  score="$(
    sed -n "${start},${total}p" "$latest" \
      | rg -n "run_controller\(\) got an unexpected keyword argument 'case_id'|Parameter _extra_context|cannot start with '_'|gateway closed \(1008\): pairing required|thread=true unavailable|报告打不开|还没完成真正部署" \
      | wc -l | tr -d ' '
  )"

  LAST_SCANNED_FILE="$latest"
  LAST_SCANNED_LINE="$total"
  save_state
  echo "${score:-0}"
}

maybe_trigger_codex_repair() {
  local score="$1"
  local now
  now="$(date +%s)"

  if (( score < ERROR_THRESHOLD )); then
    return 0
  fi

  if pgrep -f "codex exec -C /home/admin/hydromas" >/dev/null 2>&1; then
    log "codex already running; skip trigger"
    return 0
  fi

  if (( now - LAST_CODEX_TS < CODEX_COOLDOWN_SEC )); then
    log "codex cooldown active; skip trigger"
    return 0
  fi

  log "triggering codex auto-repair, score=$score"
  notify "链路告警：检测到重复错误(score=$score)，已触发Codex自动审计修复。"

  local target_arg=()
  if [[ -n "$NOTIFY_TARGET" ]]; then
    target_arg=(--notify-target "$NOTIFY_TARGET")
  fi

  nohup bash "$AUDIT_SCRIPT" --fast --progress-interval 20 --notify-channel feishu "${target_arg[@]}" >/tmp/hydromas-chain-codex.log 2>&1 &
  LAST_CODEX_TS="$now"
  save_state
}

main() {
  load_state

  local repaired=0
  local msgs=()

  if hydro_health_ok; then
    msgs+=("HydroMAS=OK")
  else
    msgs+=("HydroMAS=FAIL(restarted)")
    restart_hydromas
    repaired=1
    if ! hydro_health_ok; then
      msgs+=("HydroMAS仍不可用")
    fi
  fi

  if openclaw_health_ok; then
    msgs+=("OpenClaw=OK")
  else
    msgs+=("OpenClaw=FAIL")
    repaired=1
  fi

  if feishu_ping; then
    msgs+=("FeishuDM=OK")
  else
    if [[ -n "$FEISHU_PING_TARGET" ]]; then
      msgs+=("FeishuDM=FAIL")
      repaired=1
    else
      msgs+=("FeishuDM=SKIP(no target)")
    fi
  fi

  local score
  score="$(recent_new_error_score)"
  msgs+=("ErrorScore=${score}")
  maybe_trigger_codex_repair "$score"

  local summary
  summary="HydroMAS链路巡检: $(IFS=' | '; echo "${msgs[*]}")"
  log "$summary"

  if (( repaired == 1 )); then
    notify "$summary"
  fi
}

main "$@"

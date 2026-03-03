#!/usr/bin/env bash
# Run Codex audit against HydroMAS with strict preflight checks and progress push.
# Usage examples:
#   bash codex_hydromas_audit.sh
#   bash codex_hydromas_audit.sh --fast
#   bash codex_hydromas_audit.sh --notify-channel feishu --notify-target "user:ou_xxx"
#   bash codex_hydromas_audit.sh --prompt "custom prompt"

set -euo pipefail

REPO="/home/admin/hydromas"
OUT_DIR="/tmp/hydromas-codex-audit"
CUSTOM_PROMPT=""
MODEL=""
FAST_MODE=0
PROGRESS_INTERVAL=25

NOTIFY_CHANNEL="${NOTIFY_CHANNEL:-}"
NOTIFY_TARGET="${NOTIFY_TARGET:-}"
NOTIFY_ACCOUNT="${NOTIFY_ACCOUNT:-}"

resolve_notify_target() {
  if [[ -n "${NOTIFY_TARGET:-}" ]]; then
    printf '%s' "$NOTIFY_TARGET"
    return 0
  fi
  if [[ -n "${HYDROMAS_USER_OPENID:-}" ]]; then
    printf 'user:%s' "$HYDROMAS_USER_OPENID"
    return 0
  fi
  if [[ -n "${OPENCLAW_TRIGGER_USER_OPENID:-}" ]]; then
    printf 'user:%s' "$OPENCLAW_TRIGGER_USER_OPENID"
    return 0
  fi
  if [[ -n "${OPENCLAW_USER_OPENID:-}" ]]; then
    printf 'user:%s' "$OPENCLAW_USER_OPENID"
    return 0
  fi
  if [[ -n "${OPENCLAW_SENDER_ID:-}" ]]; then
    printf '%s' "$OPENCLAW_SENDER_ID"
    return 0
  fi
  printf ''
}

notify() {
  local msg="${1:-}"
  if [[ -z "$msg" ]]; then
    return 0
  fi
  local channel target
  channel="${NOTIFY_CHANNEL:-feishu}"
  target="$(resolve_notify_target)"
  if [[ -z "$target" ]]; then
    return 0
  fi

  local cmd=(openclaw message send --channel "$channel" --target "$target" --message "$msg")
  if [[ -n "$NOTIFY_ACCOUNT" ]]; then
    cmd+=(--account "$NOTIFY_ACCOUNT")
  fi
  (
    "${cmd[@]}" >/dev/null 2>&1 || true
  ) &
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --prompt)
      CUSTOM_PROMPT="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --fast)
      FAST_MODE=1
      shift
      ;;
    --progress-interval)
      PROGRESS_INTERVAL="${2:-25}"
      shift 2
      ;;
    --notify-channel)
      NOTIFY_CHANNEL="${2:-}"
      shift 2
      ;;
    --notify-target)
      NOTIFY_TARGET="${2:-}"
      shift 2
      ;;
    --notify-account)
      NOTIFY_ACCOUNT="${2:-}"
      shift 2
      ;;
    *)
      echo "[codex-audit] unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$REPO" ]]; then
  echo "[codex-audit] repo_not_found: $REPO" >&2
  exit 3
fi
if ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[codex-audit] not_git_repo: $REPO" >&2
  exit 4
fi
for required_dir in core agents web; do
  if [[ ! -d "$REPO/$required_dir" ]]; then
    echo "[codex-audit] missing_required_dir: $REPO/$required_dir" >&2
    exit 5
  fi
done
if ! command -v codex >/dev/null 2>&1; then
  echo "[codex-audit] codex_cli_missing" >&2
  exit 6
fi

mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$OUT_DIR/codex-audit-$TS.log"
META_FILE="$OUT_DIR/codex-audit-$TS.meta"

DEFAULT_PROMPT="Audit this repository end-to-end and complete three deliverables in one run:
1) write architecture analysis to ARCHITECTURE_AUDIT.md;
2) write a prioritized roadmap to ROADMAP.md;
3) implement the first high-priority refactor with tests/docs updates as needed.

Constraints:
- Work only inside this repository.
- Keep explanation concise.
- Do not claim success without actual file changes.
- At the end print: RESULT_OK plus changed file list."

FAST_PROMPT="Fast audit mode:
1) create/refresh ARCHITECTURE_AUDIT.md (concise);
2) create/refresh ROADMAP.md (concise, prioritized);
3) if time allows, apply one small safe refactor with tests.

Constraints:
- Prioritize speed and correctness.
- Keep output concise.
- End with RESULT_OK."

PROMPT="$DEFAULT_PROMPT"
if [[ $FAST_MODE -eq 1 ]]; then
  PROMPT="$FAST_PROMPT"
fi
if [[ -n "$CUSTOM_PROMPT" ]]; then
  PROMPT="$CUSTOM_PROMPT"
fi
if [[ -z "$MODEL" && $FAST_MODE -eq 1 ]]; then
  MODEL="gpt-5-codex"
fi

echo "[codex-audit] repo=$REPO" | tee "$META_FILE"
echo "[codex-audit] out_dir=$OUT_DIR" | tee -a "$META_FILE"
echo "[codex-audit] log_file=$LOG_FILE" | tee -a "$META_FILE"
echo "[codex-audit] fast_mode=$FAST_MODE" | tee -a "$META_FILE"
echo "[codex-audit] model=${MODEL:-default}" | tee -a "$META_FILE"
echo "[codex-audit] notify_channel=${NOTIFY_CHANNEL:-feishu}" | tee -a "$META_FILE"
echo "[codex-audit] notify_target=$(resolve_notify_target || true)" | tee -a "$META_FILE"

notify "HydroMAS Codex任务启动：repo=$REPO"

CMD=(codex exec -C "$REPO" --dangerously-bypass-approvals-and-sandbox)
if [[ -n "$MODEL" ]]; then
  CMD+=(-m "$MODEL")
fi
CMD+=("$PROMPT")

set +e
"${CMD[@]}" >"$LOG_FILE" 2>&1 &
CODEX_PID=$!
set -e

START_TS="$(date +%s)"
SENT_SESSION=0
LAST_PROGRESS_HASH=""

while kill -0 "$CODEX_PID" >/dev/null 2>&1; do
  sleep "$PROGRESS_INTERVAL"

  SESSION_ID_NOW="$(rg -o 'session id: [^[:space:]]+' "$LOG_FILE" | tail -n1 | awk '{print $3}' || true)"
  if [[ -n "$SESSION_ID_NOW" && $SENT_SESSION -eq 0 ]]; then
    notify "HydroMAS Codex会话已建立：session_id=$SESSION_ID_NOW"
    SENT_SESSION=1
  fi

  ELAPSED=$(( $(date +%s) - START_TS ))
  LAST_LINE="$(tail -n 1 "$LOG_FILE" | tr -d '\r' | cut -c1-140)"
  if [[ -z "$LAST_LINE" ]]; then
    LAST_LINE="(no output yet)"
  fi
  CUR_HASH="$(printf '%s' "$LAST_LINE" | sha1sum | awk '{print $1}')"
  if [[ "$CUR_HASH" != "$LAST_PROGRESS_HASH" ]]; then
    notify "HydroMAS Codex进行中：${ELAPSED}s，日志：$LAST_LINE"
    LAST_PROGRESS_HASH="$CUR_HASH"
  fi
done

set +e
wait "$CODEX_PID"
EXIT_CODE=$?
set -e

SESSION_ID="$(rg -o 'session id: [^[:space:]]+' "$LOG_FILE" | tail -n1 | awk '{print $3}' || true)"
echo "[codex-audit] session_id=${SESSION_ID:-missing}" | tee -a "$META_FILE"
echo "[codex-audit] exit_code=$EXIT_CODE" | tee -a "$META_FILE"

if [[ $EXIT_CODE -ne 0 ]]; then
  notify "HydroMAS Codex任务失败：exit_code=$EXIT_CODE，log=$LOG_FILE"
  echo "[codex-audit] codex_failed" >&2
  exit "$EXIT_CODE"
fi

if [[ ! -f "$REPO/ROADMAP.md" ]]; then
  notify "HydroMAS Codex失败：ROADMAP.md 未生成，log=$LOG_FILE"
  echo "[codex-audit] roadmap_missing: $REPO/ROADMAP.md" >&2
  exit 7
fi
if [[ ! -f "$REPO/ARCHITECTURE_AUDIT.md" ]]; then
  notify "HydroMAS Codex失败：ARCHITECTURE_AUDIT.md 未生成，log=$LOG_FILE"
  echo "[codex-audit] architecture_audit_missing: $REPO/ARCHITECTURE_AUDIT.md" >&2
  exit 8
fi

CHANGED_COUNT="$(git -C "$REPO" status --short | wc -l | tr -d ' ')"
notify "HydroMAS Codex完成：session_id=${SESSION_ID:-unknown}，变更数=$CHANGED_COUNT，log=$LOG_FILE"
echo "[codex-audit] OK session_id=${SESSION_ID:-unknown} log=$LOG_FILE"

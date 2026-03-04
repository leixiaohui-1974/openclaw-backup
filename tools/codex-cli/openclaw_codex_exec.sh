#!/usr/bin/env bash
set -euo pipefail

WORKDIR="${OPENCLAW_WORKDIR:-/home/admin/.openclaw/workspace}"
OUTDIR="${OPENCLAW_CODEX_OUTDIR:-/home/admin/.openclaw/tmp/codex-cli}"
mkdir -p "$OUTDIR"

usage() {
  cat <<'USAGE'
Usage:
  openclaw_codex_exec.sh "<task prompt>" [workdir]
  echo "<task prompt>" | openclaw_codex_exec.sh - [workdir]

Behavior:
- Runs codex-cli non-interactively in workspace-write sandbox
- Writes final answer to ~/.openclaw/tmp/codex-cli/<timestamp>.last.txt
- Streams codex jsonl events to ~/.openclaw/tmp/codex-cli/<timestamp>.jsonl
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "" ]]; then
  usage
  exit 2
fi

TASK="$1"
if [[ "$TASK" == "-" ]]; then
  TASK="$(cat)"
fi

if [[ "${2:-}" != "" ]]; then
  WORKDIR="$2"
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "[codex-cli-wrapper] ERROR: codex command not found" >&2
  exit 127
fi

TS="$(date +%Y%m%d-%H%M%S)"
LAST_MSG="$OUTDIR/$TS.last.txt"
EVENTS_JSONL="$OUTDIR/$TS.jsonl"

# Keep prompt deterministic and action-oriented for sub-agent usage.
PROMPT=$'You are invoked by OpenClaw as a specialist coding sub-agent.\\n'
PROMPT+=$'Complete the task with concrete file edits/commands when needed.\\n'
PROMPT+=$'Return: 1) what changed, 2) key outputs, 3) next action.\\n\\n'
PROMPT+="$TASK"

set -x
codex exec \
  --cd "$WORKDIR" \
  --sandbox workspace-write \
  --full-auto \
  --skip-git-repo-check \
  --json \
  -o "$LAST_MSG" \
  "$PROMPT" | tee "$EVENTS_JSONL"
set +x

echo "[codex-cli-wrapper] last_message=$LAST_MSG"
echo "[codex-cli-wrapper] events_jsonl=$EVENTS_JSONL"

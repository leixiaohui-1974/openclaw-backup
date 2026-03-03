---
name: codex-auto-fix-gate
description: |
  Call Codex CLI for automatic code fixes only when justified by a gate policy.
  Use when user asks to auto-fix code with Codex, and avoid over-calling Codex.
  Provides cooldown, daily budget, circuit breaker, complexity threshold, and duplicate suppression.
---

# Codex Auto Fix Gate

Use this skill to decide whether OpenClaw should call Codex CLI for automatic repairs.

## Workflow

1. Build a JSON request payload (error/task context).
2. Run gate decision first.
3. Only when `should_call=true`, run Codex CLI via gate script.
4. Read JSON result and report outcome.

## Commands

Decision only:

```bash
python3 {baseDir}/scripts/codex_fix_gate.py decide --input /path/to/fix_request.json
```

Decision + execution:

```bash
python3 {baseDir}/scripts/codex_fix_gate.py run --input /path/to/fix_request.json --prompt-file /path/to/codex_prompt.txt
```

Quick status:

```bash
python3 {baseDir}/scripts/codex_fix_gate.py status
```

## Request JSON Schema (practical)

```json
{
  "task": "short task summary",
  "severity": "low|medium|high|critical",
  "changed_files": 0,
  "failing_tests": 0,
  "has_stacktrace": false,
  "recent_failures": 0,
  "cwd": "/repo/path"
}
```

Only `task` is required; other fields improve decision quality.

## Gate Policy (default)

- Cooldown: 30 minutes between Codex calls
- Daily budget: max 4 Codex calls/day
- Circuit breaker: opens for 90 minutes after 2 consecutive failures
- Complexity threshold: call Codex only when score >= 6
- Duplicate suppression: same task fingerprint in 6h is skipped unless severity is high/critical

## Safety

- Includes recursion guard (`OPENCLAW_CODEX_GATE_ACTIVE`) to avoid Codex→OpenClaw→Codex loops.
- If decision is `skip`, no Codex process is started.
- State is local only: `~/.openclaw/workspace/.state/codex-auto-fix-gate-state.json`.

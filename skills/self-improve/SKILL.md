---
name: self-improve
description: Self-improvement skill for OpenClaw. Analyze recent runtime issues and trigger safe evolution/repair cycles with auditable checkpoints.
tags: [meta, self-improvement, evolver, repair]
---

# Self Improve

Use this skill when the user asks the agent to self-optimize, self-repair, or evolve behavior.

## Safe entrypoints

```bash
# Check evolution status first
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py evolve status

# Run one bounded evolution cycle
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py evolve run
```

## Continuous mode (optional)

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py evolve daemon-start
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py evolve daemon-stop
```

## Guardrails

- Prefer single-cycle `evolve run` by default; do not start infinite loops unless the user explicitly asks.
- Report concrete evidence after each run: status, changed files, and log path.
- If repository is dirty, avoid risky broad refactors; prioritize small repair-only changes.

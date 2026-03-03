---
name: compaction-checkpoint
description: "Persist append-only checkpoint metadata after each compaction"
metadata:
  {
    "openclaw":
      {
        "emoji": "🧷",
        "events": ["after_compaction"],
        "requires": { "config": ["workspace.dir"] }
      }
  }
---

# Compaction Checkpoint Hook

Writes a durable append-only checkpoint after every `after_compaction` event.

## Output

- `memory/compaction/YYYY-MM-DD.jsonl`
- `memory/compaction/latest.json`

## Notes

- Lightweight and append-only write path.
- Falls back to `~/.openclaw/workspace` if workspace context is unavailable.

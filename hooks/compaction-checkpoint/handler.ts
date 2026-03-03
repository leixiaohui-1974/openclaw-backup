import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

type LooseEvent = {
  action?: string;
  timestamp?: Date | string | number;
  sessionKey?: string;
  context?: {
    workspaceDir?: string;
    cfg?: {
      agents?: {
        defaults?: {
          workspace?: string;
        };
      };
    };
    sessionId?: string;
    agentId?: string;
    commandSource?: string;
  };
  payload?: {
    messageCount?: number;
    tokenCount?: number;
    compactedCount?: number;
    sessionFile?: string;
  };
};

function toIso(timestamp: LooseEvent["timestamp"]): string {
  if (timestamp instanceof Date) return timestamp.toISOString();
  if (typeof timestamp === "string" || typeof timestamp === "number") {
    const parsed = new Date(timestamp);
    if (!Number.isNaN(parsed.valueOf())) return parsed.toISOString();
  }
  return new Date().toISOString();
}

function resolveWorkspaceDir(event: LooseEvent): string {
  const byContext = event.context?.workspaceDir;
  if (byContext && byContext.trim()) return byContext;

  const byConfig = event.context?.cfg?.agents?.defaults?.workspace;
  if (byConfig && byConfig.trim()) return byConfig;

  return path.join(os.homedir(), ".openclaw", "workspace");
}

const handler = async (event: LooseEvent): Promise<void> => {
  if (event.action !== "after_compaction") return;

  try {
    const nowIso = toIso(event.timestamp);
    const day = nowIso.slice(0, 10);
    const workspaceDir = resolveWorkspaceDir(event);
    const outDir = path.join(workspaceDir, "memory", "compaction");

    const checkpoint = {
      ts: nowIso,
      kind: "after_compaction",
      sessionKey: event.sessionKey ?? "unknown",
      sessionId: event.context?.sessionId ?? "unknown",
      agentId: event.context?.agentId ?? "unknown",
      source: event.context?.commandSource ?? "unknown",
      messageCount: event.payload?.messageCount ?? null,
      tokenCount: event.payload?.tokenCount ?? null,
      compactedCount: event.payload?.compactedCount ?? null,
      sessionFile: event.payload?.sessionFile ?? null
    };

    await fs.mkdir(outDir, { recursive: true });
    await fs.appendFile(path.join(outDir, `${day}.jsonl`), `${JSON.stringify(checkpoint)}\n`, "utf8");
    await fs.writeFile(path.join(outDir, "latest.json"), `${JSON.stringify(checkpoint, null, 2)}\n`, "utf8");
  } catch {
    // Never throw from hooks; compaction should not be blocked by telemetry writes.
  }
};

export default handler;

export type Status = "waiting_approval" | "waiting_input" | "error" | "running" | "done" | "ended";

export interface Session {
  session_id: string;
  source: string;
  status: Status;
  status_since: string;
  started_at: string;
  last_event_at: string;
  ended_at?: string | null;
  agent?: { name: string; model?: string | null } | null;
  workspace: { cwd?: string | null; branch?: string | null };
  host?: { app: string; confidence: number; via: string[] } | null;
  summary?: string | null;
  request?: { kind: string; tool?: string | null; input?: string | null } | null;
  capabilities: string[];
  pid?: number | null;
  needs_you: boolean;
}

export type StreamMessage =
  | { type: "snapshot"; sessions: Session[] }
  | { type: "session"; session: Session };

export type Connection = "connecting" | "live" | "down" | "unauthorized";

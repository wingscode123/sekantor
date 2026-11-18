import type { Kind } from "./office/model";

export type Status = "waiting_approval" | "waiting_input" | "error" | "running" | "reported" | "done" | "ended";

/** The `status--*` modifier in site/app.css for each status. */
export const STATUS_CLASS: Record<Status, string> = {
  waiting_approval: "approval", waiting_input: "input", error: "error", running: "running", reported: "reported", done: "done", ended: "ended",
};

export interface Subagent {
  id: string;
  type: string;
  status: "working" | "reported";
  activity: { tool: string; kind: "read" | "edit" | "run" | "web" | "other" } | null;
  summary: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface Session {
  project?: { name: string; kind: Kind; signals: string[] } | null;
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
  request?: { kind: string; tool?: string | null; input?: string | null; id?: string | null } | null;
  capabilities: string[];
  pid?: number | null;
  activity?: { tool: string; kind: "read" | "edit" | "run" | "web" | "other" } | null;
  subagents?: Subagent[];
  needs_you: boolean;
  report_pending?: boolean;
  acknowledged_at?: string | null;
  source_label: string;
  host_label?: string | null;
  snoozed_until?: string | null;
  open_label?: string | null;
}

export type StreamMessage =
  | { type: "snapshot"; sessions: Session[] }
  | { type: "session"; session: Session };

export type Connection = "connecting" | "live" | "down" | "unauthorized";

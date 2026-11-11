import { useState } from "react";

interface TimelineEvent {
  event_id: string;
  ts: string;
  type: string;
  status?: string | null;
  summary?: string | null;
}

const STATUS_CLASS: Record<string, string> = {
  waiting_approval: "approval", waiting_input: "input", error: "error", running: "running", done: "done", ended: "ended",
};
const TYPE_TEXT: Record<string, string> = {
  session_started: "Started", status_changed: "", message: "Note", session_ended: "Ended",
};

/** FR-13: the last 50 events of a session, loaded when opened. */
export function Timeline({ sessionId }: { sessionId: string }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      const r = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/events?limit=50`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setEvents(((await r.json()).events as TimelineEvent[]).reverse());
    } catch {
      setError("Could not load the timeline.");
    }
  };

  return (
    <details className="timeline" onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) void load(); }}>
      <summary>Timeline</summary>
      {error && <p className="card__error" role="alert">{error}</p>}
      {!events && !error && <p className="timeline__note" aria-busy="true">Loading</p>}
      {events && events.length === 0 && <p className="timeline__note">No events kept for this session.</p>}
      {events && events.length > 0 && (
        <ol className="timeline__list">
          {events.map((e) => (
            <li key={e.event_id}>
              <time dateTime={e.ts}>{new Date(e.ts).toLocaleTimeString()}</time>
              <span className={`status status--${STATUS_CLASS[e.status ?? ""] ?? "done"}`}>
                {TYPE_TEXT[e.type] || (e.status ?? "").replace("_", " ")}
              </span>
              <span className="timeline__text">{e.summary ?? ""}</span>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { GHOST_MS, isGhost } from "./office/model";
import type { Connection, Session, StreamMessage } from "./types";

const PRIORITY: Record<Session["status"], number> = {
  waiting_approval: 0, waiting_input: 1, error: 2, running: 3, reported: 4, done: 5, ended: 6,
};

/** FR-10: status priority, then the longest wait first (same rule as the hub). */
export function sessionOrder(sessions: Iterable<Session>): Session[] {
  return [...sessions].sort(
    (a, b) => PRIORITY[a.status] - PRIORITY[b.status] || a.status_since.localeCompare(b.status_since),
  );
}

/** Live sessions over WS /v1/stream, reconnecting with backoff. Auth rides on the hub's cookie. */
export function useSessions(): {
  sessions: Session[]; connection: Connection; loaded: boolean;
} {
  const [byId, setById] = useState<Map<string, Session>>(new Map());
  const [connection, setConnection] = useState<Connection>("connecting");
  const [loaded, setLoaded] = useState(false);
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/v1/stream`);
      ws.onopen = () => { retry.current = 0; setConnection("live"); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as StreamMessage;
        if (msg.type === "snapshot") {
          setById(new Map(msg.sessions.map((s) => [s.session_id, s])));
          setLoaded(true);
        } else if (msg.type === "session") {
          setById((prev) => new Map(prev).set(msg.session.session_id, msg.session));
        }
      };
      ws.onclose = async (e) => {
        if (stopped) return;
        if (e.code === 4401 || e.code === 4403) { setConnection("unauthorized"); return; }
        // A refused upgrade does not say why: ask the API whether the cookie is the problem.
        try {
          const r = await fetch("/v1/health", { cache: "no-store" });
          if (r.status === 401) { setConnection("unauthorized"); return; }
        } catch { /* hub down */ }
        setConnection("down");
        const delay = Math.min(1000 * 2 ** retry.current, 10000);
        retry.current += 1;
        timer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => { stopped = true; window.clearTimeout(timer); ws?.close(); };
  }, []);

  const sessions = useMemo(() => sessionOrder(byId.values()), [byId]);
  return { sessions, connection, loaded };
}

/** Re-render every `ms` so "time in status" keeps moving. */
export function useNow(ms = 1000, enabled = true): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms, enabled]);
  return enabled ? now : Date.now();
}

/** One wake-up for the next departure expiry, with no recurring page clock. */
export function useGhostNow(sessions: Session[]): number {
  const [revision, expire] = useState(0);
  const now = useMemo(() => Date.now(), [sessions, revision]);
  useEffect(() => {
    const expiries = sessions.filter(s => isGhost(s, now)).map(s => Date.parse(s.ended_at!) + GHOST_MS);
    if (!expiries.length) return;
    const timer = window.setTimeout(() => expire(n => n + 1), Math.max(0, Math.min(...expiries) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [sessions, now]);
  return now;
}

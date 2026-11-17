import { useEffect, useRef } from "react";
import { Timeline } from "../Timeline";
import { SessionMenu } from "../SessionMenu";
import { useNow } from "../useSessions";
import { STATUS_CLASS, type Session } from "../types";
import type { Avatar } from "./model";

export const statusText = (s: Session) => ({ waiting_approval: "Waiting for approval", waiting_input: "Waiting for you", running: "Running", error: "Error", done: "Done", ended: "Ended" })[s.status];
export function AvatarCard({ session: s, avatar, onClose }: { session: Session; avatar: Avatar; onClose: () => void }) {
  const now = useNow(1000);
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    card.current?.focus();
    return () => { previous?.focus(); };
  }, []);
  return <section ref={card} tabIndex={-1} className="avatar-card" role="dialog" aria-label={`${avatar.name} details`} onKeyDown={e => { if (e.key === "Escape") onClose(); }}>
    <button type="button" className="ctl avatar-card__close" onClick={onClose}>Close</button>
    <h2>{avatar.name}</h2><p>{s.host_label || avatar.app} · {avatar.project}{s.workspace.branch ? ` / ${s.workspace.branch}` : ""}</p>
    <p className={`status status--${STATUS_CLASS[s.status]}`}>{statusText(s)} · <time dateTime={s.status_since} title={new Date(s.status_since).toLocaleString()}>since {new Date(s.status_since).toLocaleTimeString()} ({Math.max(0, Math.floor((now - Date.parse(s.status_since)) / 60000))}m)</time></p>
    {s.summary && <p>{s.summary}</p>}
    {s.activity && <p>Activity: {s.activity.tool} ({s.activity.kind})</p>}
    <SessionMenu s={s} now={now} /><Timeline sessionId={s.session_id} />
  </section>;
}

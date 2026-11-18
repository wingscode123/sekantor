import { useEffect, useRef, useState } from "react";
import { sessionApi } from "../api";
import { Timeline } from "../Timeline";
import { SessionMenu } from "../SessionMenu";
import { useNow } from "../useSessions";
import { STATUS_CLASS, type Session } from "../types";
import { subagentReportExpiry, type Avatar } from "./model";

export const statusText = (s: Session) => ({ waiting_approval: "Waiting for approval", waiting_input: s.needs_you ? "Waiting for you" : "Idle", running: "Running", error: "Error", reported: s.report_pending ? "Report ready" : "Report accepted", done: "Done", ended: "Ended" })[s.status];
export function AvatarCard({ session: s, avatar, onClose }: { session: Session; avatar: Avatar; onClose: () => void }) {
  const now = useNow(1000);
  const juniors = (s.subagents ?? []).filter(a => now < subagentReportExpiry(a));
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState(false);
  async function acceptReport() {
    setAccepting(true);
    setAcceptError(false);
    const result = await sessionApi(s.session_id, "acknowledge", "POST");
    setAccepting(false);
    setAcceptError(!result?.ok);
  }
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
    {s.report_pending && <button type="button" className="ctl" disabled={accepting} onClick={acceptReport}>Accept</button>}
    {s.report_pending && acceptError && <p role="alert">Could not accept the report. Try again.</p>}
    {juniors.length > 0 && <section aria-label="Subagents">
      <h3>Subagents</h3>
      <ul>{juniors.map(junior => <li key={junior.id}>
        <strong>{junior.type}</strong> {junior.status === "working" ? "Working" : "Reported"}
        {junior.summary && <p>{junior.summary}</p>}
      </li>)}</ul>
    </section>}
    <SessionMenu s={s} now={now} /><Timeline sessionId={s.session_id} />
  </section>;
}

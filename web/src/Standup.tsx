import { useEffect, useMemo, useState } from "react";
import "./standup.css";

export type Range = "today" | "8h";
const RANGES: { id: Range; label: string }[] = [{ id: "today", label: "Today" }, { id: "8h", label: "Last 8 h" }];
const REFRESH_MS = 60_000;

export interface DigestSession {
  session_id: string;
  agent: string | null;
  model: string | null;
  project: { name: string; kind: string } | null;
  floor: string;
  branch: string | null;
  first_at: string | null;
  last_at: string | null;
  turns: number;
  tools: Record<string, number>;
  asked: number;
  wait_s: number;
  errors: number;
  summary: string;
  status: string;
  status_since: string | null;
  waiting: boolean;
  needs_you: boolean;
}

export interface Digest {
  since: string;
  until: string;
  totals: { agents: number; turns: number; asked: number; wait_s: number; longest_wait_s: number; errors: number; waiting_now: number };
  sessions: DigestSession[];
}

/** 45s, 12m, 1h 05m. */
export function formatSpan(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

/** The waiting-for-you sessions first, then one group per project in the order the hub sent them. */
export function groupDigest(sessions: DigestSession[]): { title: string; waiting: boolean; sessions: DigestSession[] }[] {
  const groups: { title: string; waiting: boolean; sessions: DigestSession[] }[] = [];
  const waiting = sessions.filter(s => s.waiting);
  if (waiting.length) groups.push({ title: "Waiting for you now", waiting: true, sessions: waiting });
  const byProject = new Map<string, DigestSession[]>();
  for (const s of sessions) {
    if (s.waiting) continue;
    const name = s.project?.name ?? "No project";
    byProject.set(name, [...(byProject.get(name) ?? []), s]);
  }
  for (const [title, list] of byProject) groups.push({ title, waiting: false, sessions: list });
  return groups;
}

function toolsText(tools: Record<string, number>): string {
  const parts = Object.entries(tools).sort((a, b) => b[1] - a[1]).map(([kind, n]) => `${kind} ${n}`);
  return parts.length ? parts.join(" · ") : "no tool use";
}

export function Standup({ onOpen, openable, onClose }: {
  onOpen: (sessionId: string) => void;
  openable: (sessionId: string) => boolean;
  onClose: () => void;
}) {
  const [range, setRange] = useState<Range>("today");
  const [data, setData] = useState<Digest | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setFailed(false);
    const load = async () => {
      try {
        const r = await fetch(`/v1/digest?since=${range}`, { cache: "no-store" });
        if (!r.ok) throw new Error(String(r.status));
        const body = await r.json() as Digest;
        if (!cancelled) { setData(body); setFailed(false); }
      } catch {
        if (!cancelled) setFailed(true);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [range]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const groups = useMemo(() => groupDigest(data?.sessions ?? []), [data]);
  const t = data?.totals;
  return <section className="standup" aria-label="Rapat, the daily standup">
    <div className="standup__head">
      <h2>Rapat</h2>
      <div className="standup__range" role="group" aria-label="Time range">
        {RANGES.map(({ id, label }) => <button key={id} type="button" className="floor-selector__button"
          aria-pressed={range === id} onClick={() => setRange(id)}>{label}</button>)}
      </div>
      <button type="button" className="standup__close" onClick={onClose}>Close</button>
    </div>
    {failed && !data && <p role="alert">The hub did not answer. Try again in a moment.</p>}
    {!data && !failed && <p role="status">Gathering the day…</p>}
    {t && <>
      <p className="standup__totals" data-testid="standup-totals">
        <b>{t.agents}</b> {t.agents === 1 ? "agent" : "agents"} · <b>{t.turns}</b> turns finished · asked you <b>{t.asked}</b>×
        · waited <b>{formatSpan(t.wait_s)}</b> (longest {formatSpan(t.longest_wait_s)}) · <b>{t.errors}</b> {t.errors === 1 ? "error" : "errors"}
        {t.waiting_now > 0 && <> · <b className="standup__now">{t.waiting_now} waiting now</b></>}
      </p>
      {!groups.length && <p>No agent was active in this range.</p>}
      {groups.map(group => <div key={group.title} className={`standup__group${group.waiting ? " standup__group--waiting" : ""}`}>
        <h3>{group.title}</h3>
        <ul>{group.sessions.map(s => {
          const body = <>
            <span className="standup__who">{s.agent ?? "agent"}{s.branch ? <small> / {s.branch}</small> : null}</span>
            <span className="standup__status">{s.status.replace("_", " ")}</span>
            <span className="standup__line">{s.turns} turns · asked you {s.asked}× ({formatSpan(s.wait_s)}){s.errors ? ` · ${s.errors} errors` : ""} · {toolsText(s.tools)}</span>
            {s.summary && <span className="standup__summary">{s.summary}</span>}
          </>;
          return <li key={s.session_id}>{openable(s.session_id)
            ? <button type="button" className="standup__row" onClick={() => onOpen(s.session_id)}>{body}</button>
            : <div className="standup__row standup__row--gone" title="Not in the office any more">{body}</div>}</li>;
        })}</ul>
      </div>)}
    </>}
  </section>;
}

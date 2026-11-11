import { useEffect } from "react";
import { ApprovalControls, ReplyForm } from "./Actions";
import { Timeline } from "./Timeline";
import { SessionMenu, isSnoozed } from "./SessionMenu";
import type { Action, Connection, Session } from "./types";
import { useInbox, useNow } from "./useInbox";

const SOURCES: Record<string, string> = { "claude-code": "Claude Code", codex: "Codex", opencode: "opencode", gemini: "Gemini", aider: "Aider" };
const HOSTS: Record<string, string> = {
  orca: "Orca", openbot: "OpenBot", "claude-desktop": "Claude desktop", vscode: "VS Code", cursor: "Cursor",
  jetbrains: "JetBrains", tmux: "tmux", "windows-terminal": "Windows Terminal", iterm: "iTerm2",
  "apple-terminal": "Terminal.app", wezterm: "WezTerm", ghostty: "Ghostty", kitty: "kitty", terminal: "Terminal",
};
const STATUS_TEXT: Record<Session["status"], string> = {
  waiting_approval: "Waiting for approval", waiting_input: "Waiting for you", error: "Error",
  running: "Running", done: "Done", ended: "Ended",
};
const STATUS_CLASS: Record<Session["status"], string> = {
  waiting_approval: "approval", waiting_input: "input", error: "error", running: "running", done: "done", ended: "ended",
};
const NEEDS = new Set(["waiting_approval", "waiting_input", "error"]);

function since(iso: string, now: number): string {
  const s = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d`;
}

function project(cwd?: string | null): string {
  if (!cwd) return "unknown";
  const parts = cwd.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || cwd;
}

function Source({ s }: { s: Session }) {
  const host = s.host ? HOSTS[s.host.app] ?? s.host.app : null;
  const hostTitle = s.host ? `Host: ${host}, confidence ${s.host.confidence}, via ${s.host.via.join(", ")}` : undefined;
  return (
    <>
      <span className="card__source">{s.source === "openbot" && s.agent?.name ? s.agent.name : SOURCES[s.source] ?? s.source}</span>
      {host && <>{" "}<span className="card__host" title={hostTitle}>in {host}</span></>}
    </>
  );
}

function Card({ s, now, action }: { s: Session; now: number; action?: Action }) {
  const lit = s.status === "waiting_approval" || s.status === "waiting_input";
  const cmd = s.status === "waiting_approval" ? s.request?.input : null;
  return (
    <article className={lit ? "card card--lit" : "card"} aria-label={`${SOURCES[s.source] ?? s.source}, ${STATUS_TEXT[s.status]}`}>
      <div className="card__head">
        <Source s={s} />
        <time className="card__time" dateTime={s.status_since} title={`Since ${new Date(s.status_since).toLocaleString()}`}>
          {since(s.status_since, now)}
        </time>
      </div>
      <p className={`status status--${STATUS_CLASS[s.status]}`}>{STATUS_TEXT[s.status]}</p>
      {cmd ? (
        <p className="card__msg">Wants to run{s.request?.tool ? ` (${s.request.tool})` : ""} <code>{cmd}</code></p>
      ) : (
        s.summary && <p className="card__msg">{s.summary}</p>
      )}
      <p className="card__where">
        <code title={s.workspace.cwd ?? undefined}>{project(s.workspace.cwd)}</code>
        {s.workspace.branch && <code>{s.workspace.branch}</code>}
      </p>
      {s.status === "waiting_approval" && <ApprovalControls s={s} action={action} />}
      {s.status === "waiting_input" && <ReplyForm s={s} action={action} />}
      <SessionMenu s={s} now={now} />
      <Timeline sessionId={s.session_id} />
    </article>
  );
}

function Table({ rows, now, label }: { rows: Session[]; now: number; label: string }) {
  return (
    <table className="list">
      <thead>
        <tr><th scope="col">Status</th><th scope="col">Agent</th><th scope="col">Project</th><th scope="col">Last message</th><th scope="col" className="list__t">{label}</th></tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.session_id}>
            <td><span className={`status status--${STATUS_CLASS[s.status]}`}>{STATUS_TEXT[s.status]}</span></td>
            <th scope="row"><Source s={s} /><SessionMenu s={s} now={now} /><Timeline sessionId={s.session_id} /></th>
            <td>
              <code title={s.workspace.cwd ?? undefined}>{project(s.workspace.cwd)}</code>{" "}
              {s.workspace.branch && <code className="list__branch">{s.workspace.branch}</code>}
            </td>
            <td className="list__msg"><span>{s.summary ?? ""}</span></td>
            <td className="card__time list__t">{since(s.status_since, now)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Group({ id, title, count, h1, children }: { id: string; title: string; count: number; h1?: boolean; children: React.ReactNode }) {
  const H = h1 ? "h1" : "h2";
  return (
    <section className="group" aria-labelledby={id}>
      <div className="group__head"><H id={id} className="group__title">{title}</H><span className="group__count num">{count}</span></div>
      {children}
    </section>
  );
}

const HUB_TEXT: Record<Connection, string> = {
  connecting: "Connecting to the hub", live: `Connected to ${location.host}`, down: "Hub not reachable, retrying",
  unauthorized: "Not signed in",
};

export default function App() {
  const { sessions, connection, loaded, actions } = useInbox();
  const now = useNow(1000);
  const awake = sessions.filter((s) => !isSnoozed(s, now) || s.status === "ended");
  const needs = awake.filter((s) => NEEDS.has(s.status));
  const running = awake.filter((s) => s.status === "running");
  const snoozed = sessions.filter((s) => isSnoozed(s, now) && s.status !== "ended");
  const done = awake.filter((s) => s.status === "done" || s.status === "ended");

  useEffect(() => {
    document.title = needs.length ? `(${needs.length}) Ronda` : "Ronda";
  }, [needs.length]);

  let body: React.ReactNode;
  if (connection === "unauthorized") {
    body = (
      <section className="state" aria-labelledby="st">
        <h1 id="st" className="state__title">Open Ronda from its link.</h1>
        <p>Sign-in links work once and expire after 10 minutes. Run the command below for a fresh one.</p>
        <pre className="state__cmd"><code>ronda open</code></pre>
      </section>
    );
  } else if (connection === "down" && !loaded) {
    body = (
      <section className="state" aria-labelledby="st">
        <h1 id="st" className="state__title">The hub is not answering.</h1>
        <p>Nothing on {location.host}. Your agents keep working and show their own prompts. Start the hub and this page reconnects by itself.</p>
        <pre className="state__cmd"><code>ronda up</code></pre>
      </section>
    );
  } else if (!loaded) {
    body = (
      <section className="group" aria-label="Loading sessions" aria-busy="true">
        <p className="group__title">Needs you</p>
        <div className="needs"><div className="skel" /><div className="skel" /></div>
        <p className="group__title">Running</p>
        <div className="skel skel--row" /><div className="skel skel--row" />
      </section>
    );
  } else if (sessions.length === 0) {
    body = (
      <section className="state" aria-labelledby="st">
        <h1 id="st" className="state__title">Nobody needs you.</h1>
        <p>Sessions appear here on their first event. If an agent is running and nothing shows, the hooks are not installed in that project yet.</p>
        <pre className="state__cmd"><code>ronda install claude --project</code></pre>
      </section>
    );
  } else {
    body = (
      <>
        <Group id="g-needs" title="Needs you" count={needs.length} h1>
          {needs.length ? (
            <div className="needs">{needs.map((s) => <Card key={s.session_id} s={s} now={now} action={s.request?.id ? actions.get(s.request.id) : undefined} />)}</div>
          ) : (
            <p className="group__empty">Nobody is waiting for you.</p>
          )}
        </Group>
        {running.length > 0 && (
          <Group id="g-running" title="Running" count={running.length}><Table rows={running} now={now} label="For" /></Group>
        )}
        {snoozed.length > 0 && (
          <Group id="g-snoozed" title="Snoozed" count={snoozed.length}><Table rows={snoozed} now={now} label="For" /></Group>
        )}
        {done.length > 0 && (
          <Group id="g-done" title="Done" count={done.length}><Table rows={done} now={now} label="Ago" /></Group>
        )}
      </>
    );
  }

  return (
    <>
      <a className="skip" href="#main">Skip to the inbox</a>
      <header className="bar">
        <div className="shell bar__inner">
          <a className="bar__home" href="/" aria-label="Ronda, home"><img src="/lockup.svg" width="97" height="24" alt="" /></a>
          <p className={connection === "down" || connection === "unauthorized" ? "bar__hub bar__hub--down" : "bar__hub"} role="status">
            {HUB_TEXT[connection]}
          </p>
        </div>
      </header>
      <main id="main" className="shell inbox-page">{body}</main>
    </>
  );
}

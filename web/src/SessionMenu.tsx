import { useState } from "react";
import { sessionApi } from "./api";
import type { Session } from "./types";

const SNOOZE: { label: string; minutes: number | null }[] = [
  { label: "30 minutes", minutes: 30 },
  { label: "2 hours", minutes: 120 },
  { label: "8 hours", minutes: 480 },
  { label: "Until I unmute", minutes: null },
];

export function isSnoozed(s: Session, now: number): boolean {
  return !!s.snoozed_until && Date.parse(s.snoozed_until) > now;
}

function until(iso: string): string {
  const d = new Date(iso);
  if (d.getFullYear() - new Date().getFullYear() > 1) return "until you unmute it";
  return `until ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

async function call(s: Session, path: string, method: string, body?: unknown) {
  const answer = await sessionApi(s.session_id, path, method, body);
  if (!answer) return "The hub did not answer.";
  return answer.ok ? null : (answer.data.message ?? answer.data.detail ?? "Did not work.");
}

/** FR-14 open in source, FR-15 snooze. */
export function SessionMenu({ s, now }: { s: Session; now: number }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const snoozed = isSnoozed(s, now);

  const run = async (path: string, method: string, body?: unknown) => {
    setBusy(true);
    setError(await call(s, path, method, body));
    setBusy(false);
  };

  return (
    <div className="smenu">
      {s.open_label && (
        <button className="ctl" type="button" disabled={busy} onClick={() => run("open", "POST")}>{s.open_label}</button>
      )}
      {snoozed ? (
        <>
          <span className="smenu__note">Snoozed {until(s.snoozed_until!)}</span>
          <button className="ctl" type="button" disabled={busy} onClick={() => run("snooze", "DELETE")}>Unmute</button>
        </>
      ) : (
        <details className="smenu__snooze">
          <summary className="ctl">Snooze</summary>
          <ul role="list">
            {SNOOZE.map((o) => (
              <li key={o.label}>
                <button className="ctl" type="button" disabled={busy}
                        onClick={(e) => {
                          (e.currentTarget.closest("details") as HTMLDetailsElement).open = false;
                          void run("snooze", "POST", { minutes: o.minutes });
                        }}>{o.label}</button>
              </li>
            ))}
          </ul>
        </details>
      )}
      {error && <p className="card__error" role="alert">{error}</p>}
    </div>
  );
}

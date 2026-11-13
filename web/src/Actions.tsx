import { useId, useState } from "react";
import { sessionApi } from "./api";
import type { Action, Session } from "./types";

async function postAction(s: Session, body: Record<string, unknown>) {
  const answer = await sessionApi(s.session_id, "actions", "POST", { request_id: s.request?.id, ...body });
  return answer ?? { ok: false, status: 0, data: { message: "The hub did not answer. Nothing was sent." } };
}

const SENT: Record<Action["type"], string> = { approve: "Approved", deny: "Denied", reply: "Reply sent" };

function live(action: Action | undefined, s: Session): action is Action {
  return !!action && action.request_id === s.request?.id && (action.outcome === "pending" || action.outcome === "delivered");
}

/** What happened to the last action for this request. */
function Sent({ action }: { action: Action }) {
  const how = action.outcome === "pending" ? "waiting for the agent to pick it up." : "the agent has it.";
  return <p className="card__note" role="status">{SENT[action.type]} from Ronda, {how}</p>;
}

export function ApprovalControls({ s, action }: { s: Session; action?: Action }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [risky, setRisky] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  if (!s.request?.id || !(s.capabilities.includes("approve") || s.capabilities.includes("deny"))) return null;
  if (live(action, s)) return <Sent action={action} />;

  const send = async (type: "approve" | "deny", confirm = false) => {
    setBusy(type);
    setError(null);
    const r = await postAction(s, { type, confirm });
    setBusy(null);
    if (r.status === 409 && r.data.error === "confirm_required") {
      setRisky(true);
      return;
    }
    if (!r.ok) setError(r.data.message ?? "Not sent.");
    else setRisky(false);
  };

  if (risky) {
    return (
      <div className="confirm" role="alertdialog" aria-labelledby={titleId}>
        <p id={titleId}>This command matches a risky pattern. Approve it anyway?</p>
        <div className="card__actions">
          <button className="ctl ctl--danger" type="button" disabled={!!busy} aria-busy={busy === "approve"}
                  onClick={() => send("approve", true)}>Approve anyway</button>
          <button className="ctl" type="button" disabled={!!busy} onClick={() => setRisky(false)}>Cancel</button>
        </div>
        {error && <p className="card__error" role="alert">{error}</p>}
      </div>
    );
  }
  return (
    <>
      <div className="card__actions">
        {s.capabilities.includes("approve") && (
          <button className="ctl ctl--go" type="button" disabled={!!busy} aria-busy={busy === "approve"}
                  onClick={() => send("approve")}>Approve</button>
        )}
        {s.capabilities.includes("deny") && (
          <button className="ctl" type="button" disabled={!!busy} aria-busy={busy === "deny"}
                  onClick={() => send("deny")}>Deny</button>
        )}
      </div>
      {error && <p className="card__error" role="alert">{error}</p>}
    </>
  );
}

export function ReplyForm({ s, action }: { s: Session; action?: Action }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();
  if (!s.request?.id || s.request.kind !== "input" || !s.capabilities.includes("reply")) return null;
  if (live(action, s)) return <Sent action={action} />;

  const send = async () => {
    if (!text.trim()) {
      setError("Write a reply first.");
      return;
    }
    setBusy(true);
    setError(null);
    const r = await postAction(s, { type: "reply", text });
    setBusy(false);
    if (!r.ok) setError(r.data.message ?? "Not sent.");
    else setText("");
  };

  return (
    <form className="reply" onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <label htmlFor={fieldId}>Reply to this session</label>
      <div className="reply__row">
        <textarea id={fieldId} name="reply" rows={2} value={text} disabled={busy}
                  aria-invalid={error ? true : undefined}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      void send();
                    }
                  }} />
        <button className="ctl ctl--go" type="submit" disabled={busy} aria-busy={busy}>Send reply</button>
      </div>
      <p className="reply__help" aria-live="polite">{error ?? "Ctrl+Enter sends."}</p>
    </form>
  );
}

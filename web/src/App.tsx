import { useEffect } from "react";
import { useSessions } from "./useSessions";
import { OfficeView } from "./office/OfficeView";
import "./office/office.css";

export default function App() {
  const { sessions, connection, loaded } = useSessions();
  const needs = sessions.filter(s => s.needs_you).length;
  useEffect(() => { document.title = needs ? `(${needs}) SeKantor` : "SeKantor"; }, [needs]);
  return <>
    <a className="skip" href="#main">Skip to the office</a>
    <header className="bar"><div className="shell bar__inner">
      <a className="bar__home" href="/" aria-label="SeKantor, home"><img src="/lockup.svg" width="97" height="24" alt="" /></a>
      <p className="office-counts">{sessions.filter(s => s.status === "running").length} busy · {needs} needs you · {sessions.filter(s => s.status === "error").length} errors</p>
      <p className={`bar__hub ${connection === "down" || connection === "unauthorized" ? "bar__hub--down" : ""}`} role="status">{connection === "live" ? "Connected" : connection === "connecting" ? "Connecting to the hub" : connection === "down" ? "Hub not reachable, retrying" : "Not signed in"}</p>
    </div></header>
    <main id="main" className="office-page">
      {connection === "down" && <div className="office-banner" role="alert">The hub is not answering. Reconnecting; showing the last office.</div>}
      {connection === "unauthorized" && <div className="office-banner" role="alert">Open SeKantor from its link. Sign-in links work once and expire after 10 minutes. Run <code>sekantor open</code> for a fresh one.</div>}
      {!loaded && <p role="status">Waiting for sessions…</p>}
      <OfficeView sessions={sessions} />
    </main>
  </>;
}

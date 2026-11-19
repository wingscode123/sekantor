import { useEffect, useMemo, useState } from "react";
import { useGhostNow, useNow, useSessions } from "./useSessions";
import { isSnoozed } from "./SessionMenu";
import { queueSummary, useAttentionSignals, waitLevel } from "./attention";
import { OfficeView } from "./office/OfficeView";
import { defaultFloor, floorAttention, floorOf, floors, rememberFloor } from "./office/floors";
import { isGhost } from "./office/model";
import type { Floor, Session } from "./types";
import "./office/office.css";
import "./attention.css";
import lockupUrl from "./assets/lockup.svg";

export default function App() {
  const { sessions, connection, loaded } = useSessions();
  const layoutNow = useGhostNow(sessions);
  const now = useNow(1000, sessions.some(s => s.status !== "ended" && (isSnoozed(s, Date.now()) || s.needs_you)));
  const awake = sessions.filter(s => s.status !== "ended" && !isSnoozed(s, now));
  const needs = awake.filter(s => s.needs_you).length;
  const groups = useMemo(() => {
    const result: Record<Floor, Session[]> = { claude: [], orca: [], openbot: [] };
    for (const session of sessions) {
      if (session.status !== "ended" || isGhost(session, layoutNow)) result[floorOf(session)].push(session);
    }
    return result;
  }, [sessions, layoutNow]);
  const available = floors.filter(floor => groups[floor.id].length).map(floor => ({
    ...floor, ...floorAttention(groups[floor.id], now),
  }));
  const [chosen, setChosen] = useState<Floor>();
  const active = available.some(floor => floor.id === chosen) ? chosen : defaultFloor(available);
  if (active && active !== chosen) setChosen(active);
  const radar = queueSummary(sessions, now);
  useAttentionSignals(radar?.count ?? 0);
  const [open, setOpen] = useState<{ id: string; n: number; floor: Floor } | null>(null);
  useEffect(() => { if (open) setOpen(null); }, [open]);
  const openLongest = () => {
    if (!radar) return;
    const floor = floorOf(radar.longest);
    setChosen(floor); rememberFloor(floor);
    setOpen(previous => ({ id: radar.longest.session_id, n: (previous?.n ?? 0) + 1, floor }));
  };
  return <>
    <a className="skip" href="#main">Skip to the office</a>
    <header className="bar"><div className="shell bar__inner">
      <a className="bar__home" href="/" aria-label="SeKantor, home"><img src={lockupUrl} width="118" height="32" alt="" /></a>
      <p className="office-counts">{awake.filter(s => s.status === "running").length} busy · {needs} need you · {awake.filter(s => s.report_pending).length} reports · {awake.filter(s => s.status === "error").length} errors</p>
      {radar && <button type="button" className={`queue-pill queue-pill--${waitLevel(radar.longestMs)}`} onClick={openLongest}>{radar.text}</button>}
      <p className={`bar__hub${connection === "down" || connection === "unauthorized" ? "bar__hub--down" : ""}`} role="status">{connection === "live" ? "Connected" : connection === "connecting" ? "Connecting to the hub" : connection === "down" ? "Hub not reachable, retrying" : "Not signed in"}</p>
    </div></header>
    <main id="main" className="office-page">
      {connection === "down" && <div className="office-banner" role="alert">The hub is not answering. Reconnecting; showing the last office.{!loaded && <p>Start the hub with <code>sekantor up</code>.</p>}</div>}
      {connection === "unauthorized" && <div className="office-banner" role="alert">Open SeKantor from its link. Sign-in links work once and expire after 10 minutes. Run <code>sekantor open</code> for a fresh one.</div>}
      {!loaded && <p role="status">Waiting for sessions…</p>}
      {available.length > 0 && <nav className="floor-selector" aria-label="Office floors">
        {available.map(({ id, label, alerts }) => <button key={id} type="button" className="floor-selector__button"
          aria-pressed={active === id} onClick={() => { setChosen(id); rememberFloor(id); }}>
          {label}{alerts > 0 && <span className="floor-selector__badge" aria-label={`${alerts} need your attention`}>{alerts}</span>}
        </button>)}
      </nav>}
      <OfficeView key={active ?? chosen ?? "claude"} open={open?.floor === (active ?? "claude") ? open : null} sessions={groups[active ?? "claude"]} loaded={loaded} now={now} layoutNow={layoutNow} />
    </main>
  </>;
}

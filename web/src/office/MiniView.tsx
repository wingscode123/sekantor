import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { isSnoozed } from "../SessionMenu";
import { useGhostNow, useNow, useSessions } from "../useSessions";
import { layoutOffice, type Office } from "./model";
import { startRenderer } from "./render";
import { defaultTheme, TILE, type Theme } from "./sprites";
import "./mini.css";

// Keep the original floor and characters, with only your desk in this close-up.
const miniTheme: Theme = { ...defaultTheme, furniture(kind, ctx, x, y, frame) {
  if (kind === "your_desk") defaultTheme.furniture(kind, ctx, x, y, frame);
} };
const openFullOffice = (url: string) => window.location.assign(url);

export function MiniView({ navigate = openFullOffice }: { navigate?: (url: string) => void }) {
  const { sessions, connection, loaded } = useSessions();
  const layoutNow = useGhostNow(sessions);
  const now = useNow(1000, sessions.some(s => s.status !== "ended" && isSnoozed(s, Date.now())));
  const awake = sessions.filter(s => s.status !== "ended" && !isSnoozed(s, now));
  const waiting = awake.filter(s => s.needs_you && s.status !== "error");
  const waitingIds = new Set(waiting.map(s => s.session_id));
  const busy = awake.filter(s => s.status === "running").length;
  const reports = awake.filter(s => s.report_pending).length;
  const latest = [...waiting].sort((a, b) => b.last_event_at.localeCompare(a.last_event_at) || b.status_since.localeCompare(a.status_since)).find(s => s.summary);
  const office = useMemo(() => layoutOffice(sessions, layoutNow), [sessions, layoutNow]);
  // Preserve full-office identities and looks, with space to gather around your desk.
  const avatars = office.avatars.filter(a => waitingIds.has(a.sessionId));
  const rows = Math.ceil(avatars.length / 18);
  const height = Math.max(7, rows * 2 + 3);
  const yourDesk = { x: 10, y: height - 2 };
  const door = { x: 1, y: height - 2 };
  const scene: Office = { ...office, width: 20, height, clusters: [], rooms: [], places: [], yourDesk, door,
    lobby: { x: 0, y: 0, w: 0, h: 0, yourDesk, door, corridorY: 0 },
    avatars: avatars.map((a, i) => ({ ...a, place: "desk", deskTile: { x: 1 + i % 18, y: 2 + Math.floor(i / 18) * 2 }, targetTile: { x: 1 + i % 18, y: 2 + Math.floor(i / 18) * 2 } })) };
  const current = useRef(scene);
  const canvas = useRef<HTMLCanvasElement>(null);
  // Compare the full visual scene, including membership/poses/slots, rather than
  // waking the renderer for clock ticks or changes to summary text alone.
  const sceneKey = JSON.stringify(scene);
  useLayoutEffect(() => {
    current.current = scene;
    canvas.current?.dispatchEvent(new Event("officechange"));
  }, [sceneKey]);
  useEffect(() => startRenderer(canvas.current!, () => current.current, miniTheme), []);
  const summary = latest?.summary || (waiting.length ? "An agent needs you." : loaded ? "Nobody is waiting for you." : "Connecting to the office…");
  const connectionText = connection === "down" ? "Hub disconnected" : connection === "unauthorized" ? "Not signed in" : "";
  const label = `${busy} busy, ${waiting.length} need you, ${reports} reports. ${waiting.map(s => s.agent?.name || s.source_label).join(", ")}. ${summary}${connectionText ? ` ${connectionText}.` : ""} Open full office`;
  return <button type="button" className="mini-office" aria-label={label} onClick={() => navigate("/")}>
    <span className="mini-office__scene"><canvas ref={canvas} width={scene.width * TILE} height={scene.height * TILE} aria-hidden="true" /></span>
    <span className="mini-office__counts">{busy} busy · {waiting.length} need you · {reports} reports{connectionText && ` · ${connectionText}`}</span>
    <span className="mini-office__summary">{summary}</span>
  </button>;
}

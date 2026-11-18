import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { isSnoozed } from "../SessionMenu";
import type { Session } from "../types";
import { CORRIDOR_WIDTH, layoutOffice, roomSignWidth, ROOM_WIDTH, type PlaceLabel } from "./model";
import { startRenderer, type FramePositions } from "./render";
import { CHARACTER_HEIGHT, TILE } from "./sprites";

import { AvatarCard, statusText } from "./AvatarCard";

const placeSigns: Record<PlaceLabel["kind"], { label: string; description: string }> = {
  your_desk: { label: "Your desk: permissions, questions, reports", description: "Agents come here for approval, to ask for input, or to deliver a report for you to review." },
  rack: { label: "Server rack: running commands", description: "Agents gather at their project’s rack while running commands." },
  pantry: { label: "Pantry: idle", description: "Agents wait here when they have no work that needs your attention." },
  door: { label: "Exit: session ended", description: "Agents leave through this door when their sessions end." },
};

export function OfficeView({ sessions, loaded = true, now = Date.now(), layoutNow = now }: { sessions: Session[]; loaded?: boolean; now?: number; layoutNow?: number }) {
  const awake = sessions.filter(s => s.status !== "ended" && !isSnoozed(s, now));
  const [cols, setCols] = useState(2);
  const office = useMemo(() => layoutOffice(sessions, layoutNow, cols * (ROOM_WIDTH + CORRIDOR_WIDTH) - CORRIDOR_WIDTH), [sessions, layoutNow, cols]);
  const sceneKey = JSON.stringify(office);
  const current = useRef(office);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const hits = useRef<FramePositions>(new Map());
  const byId = useMemo(() => new Map(sessions.map(s => [s.session_id, s])), [sessions]);
  const [size, setSize] = useState({ tilePixels: TILE / 2, dpr: 1, inset: 0 });
  const tileSize = size.tilePixels / size.dpr;
  const width = office.width * size.tilePixels / size.dpr;
  const height = office.height * size.tilePixels / size.dpr;
  const scale = tileSize / TILE;
  const [selected, setSelected] = useState<string | null>(null);
  useLayoutEffect(() => {
    current.current = office;
    const node = canvas.current;
    if (node && node.width !== office.width * size.tilePixels) node.width = office.width * size.tilePixels;
    if (node && node.height !== office.height * size.tilePixels) node.height = office.height * size.tilePixels;
    canvas.current?.dispatchEvent(new Event("officechange"));
  }, [sceneKey, size.tilePixels, office.width, office.height]);
  useLayoutEffect(() => {
    const measure = () => {
      const box = viewport.current;
      if (!box?.clientWidth) return;
      const dpr = window.devicePixelRatio || 1;
      const width = Math.floor(box.clientWidth * dpr);
      const availableTiles = Math.floor(box.clientWidth / TILE);
      const fitCols = Math.max(2, Math.floor((availableTiles + CORRIDOR_WIDTH) / (ROOM_WIDTH + CORRIDOR_WIDTH)));
      setCols(currentCols => {
        if (fitCols > currentCols) return fitCols;
        if (fitCols < currentCols) {
          const minTilesForCurrent = currentCols * ROOM_WIDTH + (currentCols - 1) * CORRIDOR_WIDTH;
          if (availableTiles < minTilesForCurrent - 2) return fitCols;
          return currentCols;
        }
        return currentCols;
      });

      const fit = Math.max(1, Math.floor(width / office.width));
      // Use whole native-pixel multiples for enlargement and whole device pixels per tile for reduction.
      const tilePixels = fit >= TILE ? TILE * Math.floor(fit / TILE) : fit;
      const inset = Math.floor((width - office.width * tilePixels) / 2) / dpr;
      setSize(previous => previous.tilePixels === tilePixels && previous.dpr === dpr && previous.inset === inset
        ? previous : { tilePixels, dpr, inset });
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (viewport.current) observer?.observe(viewport.current);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [office.width]);
  useEffect(() => {
    const node = canvas.current!;
    return startRenderer(node, () => current.current, undefined, positions => { hits.current = positions; });
  }, []);
  const session = byId.get(selected ?? "");
  const avatar = office.avatars.find(a => a.sessionId === selected);
  return <>
    <div className="office-viewport" ref={viewport}>
      <div className="office-floor" style={{ marginLeft: size.inset, width, height }}>
        <canvas ref={canvas} role="img" aria-label={`Office with ${awake.length} agents: ${awake.filter(s => s.status === "running").length} busy, ${awake.filter(s => s.needs_you).length} need you, ${awake.filter(s => s.report_pending).length} reports, ${awake.filter(s => s.status === "error").length} errors`} style={{ width, height }} onClick={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
          const hit = [...hits.current].reverse().find(([, p]) => x >= p.x && x < p.x + TILE && y >= p.y && y < p.y + CHARACTER_HEIGHT);
          if (hit && byId.has(hit[0])) setSelected(hit[0]);
        }} />
        {office.rooms.map(room => <span className="office-sign office-sign--room" key={room.project}
          title={room.project} style={{
            left: (room.sign.x + 0.5) * tileSize, top: (room.sign.y + 0.5) * tileSize,
            maxWidth: roomSignWidth(room) * tileSize - 4,
          }}>{room.project}</span>)}
        {office.places.map(({ kind, at, room }) => {
          const sign = placeSigns[kind];
          const columns = kind === "your_desk" ? 14 : kind === "door" ? 10 : 6;
          const isRoomPlace = Boolean(room);
          const left = isRoomPlace ? (at.x + 1.1) * tileSize : (at.x + 0.5) * tileSize;
          const top = isRoomPlace ? (at.y + 0.5) * tileSize : (at.y - 0.4) * tileSize;
          const transform = isRoomPlace ? "translateY(-50%)" : "translate(-50%, -50%)";
          return <span className="office-sign" aria-hidden="true" key={JSON.stringify([room, kind])}
            style={{ left, top, transform, maxWidth: (columns - (isRoomPlace ? 1.2 : 0)) * tileSize }}>
            {sign.label}
          </span>;
        })}
        {office.avatars.filter(a => a.pose !== "leave").map(a =>
          <button type="button" className="office-plate" data-testid="name-plate" key={a.key} tabIndex={-1}
            hidden={tileSize < 20}
            style={{
              left: (a.deskTile.x + 0.5) * tileSize,
              top: (a.deskTile.y - (CHARACTER_HEIGHT - TILE) / TILE) * tileSize,
              maxWidth: 3 * tileSize,
            }}
            onClick={() => setSelected(a.sessionId)}>
            {a.name}<small>{a.app} · {a.project}{byId.get(a.sessionId)?.workspace.branch ? ` / ${byId.get(a.sessionId)!.workspace.branch}` : ""}</small>
          </button>)}
      </div>
    </div>
    {loaded && !office.avatars.length && <p className="office-empty">Your office is quiet. Agents appear when their sessions connect. If an agent is running, install its hooks with <code>sekantor install claude --project</code>.</p>}
    <div className="office-accessible">
      <details className="office-legend">
        <summary>What the places mean</summary>
        <dl>
          {Object.entries(placeSigns).map(([kind, { label, description }]) => (
            <div key={kind}>
              <dt>{label}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
      </details>
      <ul aria-label="Office agents">{office.avatars.filter(a => a.pose !== "leave").map(a => {
        const s = byId.get(a.sessionId)!;
        return <li key={a.key}><button type="button" onClick={() => setSelected(a.sessionId)}>{a.name}, {a.app}, {a.project}, {statusText(s)}</button></li>;
      })}</ul>
    </div>
    {session && avatar && <AvatarCard key={session.session_id} session={session} avatar={avatar} onClose={() => setSelected(null)} />}
  </>;
}

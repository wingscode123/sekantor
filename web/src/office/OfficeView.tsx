import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { isSnoozed } from "../SessionMenu";
import type { Session } from "../types";
import { layoutOffice, roomSignWidth, type PlaceLabel } from "./model";
import { startRenderer, type FramePositions } from "./render";
import { CHARACTER_HEIGHT, JUNIOR_SCALE, TILE } from "./sprites";

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
  const office = useMemo(() => layoutOffice(sessions, layoutNow, cols), [sessions, layoutNow, cols]);
  const sceneKey = JSON.stringify(office);
  const current = useRef(office);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const hits = useRef<FramePositions>(new Map());
  const plates = useRef(new Map<string, HTMLButtonElement>());
  const byId = useMemo(() => new Map(sessions.map(s => [s.session_id, s])), [sessions]);
  const [size, setSize] = useState({ tilePixels: TILE / 2, dpr: 1, inset: 0, insetY: 0 });
  const tileSize = size.tilePixels / size.dpr;
  const width = office.width * size.tilePixels / size.dpr;
  const height = office.height * size.tilePixels / size.dpr;
  const scale = tileSize / TILE;
  const plateScale = useRef(scale);
  plateScale.current = scale;
  const [selected, setSelected] = useState<string | null>(null);
  useLayoutEffect(() => {
    current.current = office;
    const node = canvas.current;
    if (node && node.width !== office.width * size.tilePixels) node.width = office.width * size.tilePixels;
    if (node && node.height !== office.height * size.tilePixels) node.height = office.height * size.tilePixels;
    canvas.current?.dispatchEvent(new Event("officechange"));
  }, [sceneKey, size.tilePixels, office.width, office.height]);
  const latest = useRef({ sessions, layoutNow });
  latest.current = { sessions, layoutNow };
  const measure = () => {
      const { sessions, layoutNow } = latest.current;
      const box = viewport.current;
      if (!box?.clientWidth) return;
      const dpr = window.devicePixelRatio || 1;
      const width = Math.floor(box.clientWidth * dpr);
      // jsdom and detached boxes report no height: then only the width constrains the fit.
      const height = box.clientHeight ? Math.floor(box.clientHeight * dpr) : Infinity;
      const maxCols = Math.max(2, Math.ceil(layoutOffice(sessions, layoutNow).rooms.length / 2));
      // Contain: the biggest whole-device-pixel tile for which the whole office fits both ways.
      let best: { cols: number; tilePixels: number; w: number; h: number } | null = null;
      for (let c = 2; c <= maxCols; c++) {
        const layout = layoutOffice(sessions, layoutNow, c);
        const fit = Math.max(1, Math.min(Math.floor(width / layout.width), Math.floor(height / layout.height)));
        // Native-pixel multiples when they lose under 10%, otherwise the exact fit.
        const multiple = fit >= TILE ? TILE * Math.floor(fit / TILE) : fit;
        const tilePixels = multiple >= 0.9 * fit ? multiple : fit;
        if (!best || tilePixels > best.tilePixels) best = { cols: c, tilePixels, w: layout.width, h: layout.height };
      }
      const { cols: nextCols, tilePixels, w, h } = best!;
      const inset = Math.floor((width - w * tilePixels) / 2) / dpr;
      const insetY = Number.isFinite(height) ? Math.floor((height - h * tilePixels) / 2) / dpr : 0;
      setCols(nextCols);
      setSize(previous => previous.tilePixels === tilePixels && previous.dpr === dpr && previous.inset === inset && previous.insetY === insetY
        ? previous : { tilePixels, dpr, inset, insetY });
    };
  const measureRef = useRef(measure);
  measureRef.current = measure;
  // Rooms added, removed or resized: refit. Status-only updates leave this signature alone.
  const layoutSignature = JSON.stringify([office.rooms.map(r => [r.project, r.w, r.h, r.desks.length]), office.lobby.h]);
  useLayoutEffect(() => { measureRef.current(); }, [layoutSignature]);
  useLayoutEffect(() => {
    const run = () => measureRef.current();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(run) : null;
    if (viewport.current) observer?.observe(viewport.current);
    window.addEventListener("resize", run);
    return () => { observer?.disconnect(); window.removeEventListener("resize", run); };
  }, []);
  useEffect(() => {
    const node = canvas.current!;
    return startRenderer(node, () => current.current, undefined, positions => {
      hits.current = positions;
      for (const [key, plate] of plates.current) {
        const position = positions.get(key);
        if (!position) continue;
        plate.style.left = `${(position.x + TILE / 2) * plateScale.current}px`;
        // Most poses have 8 native pixels of padding above the head.
        plate.style.top = `${(position.y + 6) * plateScale.current}px`;
      }
    });
  }, []);
  const session = byId.get(selected ?? "");
  const mainAvatars = office.avatars.filter(a => !a.junior);
  const avatar = mainAvatars.find(a => a.sessionId === selected);
  return <>
    <div className="office-viewport" ref={viewport}>
      <div className="office-floor" style={{ marginLeft: size.inset, marginTop: size.insetY, width, height }}>
        <canvas ref={canvas} role="img" aria-label={`Office with ${awake.length} agents: ${awake.filter(s => s.status === "running").length} busy, ${awake.filter(s => s.needs_you).length} need you, ${awake.filter(s => s.report_pending).length} reports, ${awake.filter(s => s.status === "error").length} errors`} style={{ width, height }} onClick={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
          const hit = [...hits.current].reverse().find(([key, p]) => {
            const size = byId.has(key) ? 1 : JUNIOR_SCALE;
            return x >= p.x && x < p.x + TILE * size && y >= p.y && y < p.y + CHARACTER_HEIGHT * size;
          });
          const clicked = hit && office.avatars.find(a => a.key === hit[0]);
          if (clicked) setSelected(clicked.sessionId);
        }} />
        {office.rooms.map(room => <span className="office-sign office-sign--room" key={room.project}
          title={room.project} style={{
            left: (room.sign.x + 0.5) * tileSize, top: (room.sign.y + 0.5) * tileSize,
            maxWidth: roomSignWidth(room) * tileSize - 4,
          }}>{room.project}</span>)}
        {office.places.map(({ kind, at, room }) => {
          const sign = placeSigns[kind];
          const furnitureRoom = office.rooms.find(r => r.project === room);
          const columns = kind === "your_desk" ? 14 : kind === "door" ? 10 : Math.floor(((furnitureRoom?.w ?? 14) - 2) / 2);
          const isRoomPlace = Boolean(room);
          const left = isRoomPlace ? (at.x + 1.1) * tileSize : (at.x + 0.5) * tileSize;
          const top = isRoomPlace ? (at.y + 0.5) * tileSize : (at.y - 0.4) * tileSize;
          const transform = isRoomPlace ? "translateY(-50%)" : "translate(-50%, -50%)";
          return <span className="office-sign" aria-hidden="true" key={JSON.stringify([room, kind])}
            style={{ left, top, transform, maxWidth: (columns - (isRoomPlace ? 1.2 : 0)) * tileSize }}>
            {sign.label}
          </span>;
        })}
        {mainAvatars.filter(a => a.pose !== "leave").map(a =>
          <button type="button" className="office-plate" data-testid="name-plate" key={a.key} tabIndex={-1}
            ref={node => {
              if (node) plates.current.set(a.key, node);
              else plates.current.delete(a.key);
            }}
            hidden={tileSize < 20}
            style={{
              left: (a.deskTile.x + 0.5) * tileSize,
              top: (a.deskTile.y + (TILE - CHARACTER_HEIGHT + 6) / TILE) * tileSize,
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
      <ul aria-label="Office agents">{mainAvatars.filter(a => a.pose !== "leave").map(a => {
        const s = byId.get(a.sessionId)!;
        return <li key={a.key}><button type="button" onClick={() => setSelected(a.sessionId)}>{a.name}, {a.app}, {a.project}, {statusText(s)}</button></li>;
      })}</ul>
    </div>
    {session && avatar && <AvatarCard key={session.session_id} session={session} avatar={avatar} onClose={() => setSelected(null)} />}
  </>;
}

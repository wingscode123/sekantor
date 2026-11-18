import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { isSnoozed } from "../SessionMenu";
import type { Session } from "../types";
import { layoutOffice } from "./model";
import { startRenderer, type FramePositions } from "./render";

import { AvatarCard, statusText } from "./AvatarCard";

export function OfficeView({ sessions, loaded = true, now = Date.now(), layoutNow = now }: { sessions: Session[]; loaded?: boolean; now?: number; layoutNow?: number }) {
  const awake = sessions.filter(s => s.status !== "ended" && !isSnoozed(s, now));
  const office = useMemo(() => layoutOffice(sessions, layoutNow), [sessions, layoutNow]);
  const sceneKey = JSON.stringify(office);
  const current = useRef(office);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const hits = useRef<FramePositions>(new Map());
  const byId = useMemo(() => new Map(sessions.map(s => [s.session_id, s])), [sessions]);
  const [scale, setScale] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  useLayoutEffect(() => {
    current.current = office;
    const node = canvas.current;
    if (node && node.width !== office.width * 16) node.width = office.width * 16;
    if (node && node.height !== office.height * 16) node.height = office.height * 16;
    canvas.current?.dispatchEvent(new Event("officechange"));
  }, [sceneKey]);
  useEffect(() => {
    const measure = () => {
      const box = viewport.current;
      if (box) setScale(Math.max(1, Math.floor(box.clientWidth / (office.width * 16))));
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (viewport.current) observer?.observe(viewport.current);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [office.width, office.height]);
  useEffect(() => {
    const node = canvas.current!;
    return startRenderer(node, () => current.current, undefined, positions => { hits.current = positions; });
  }, []);
  const session = byId.get(selected ?? "");
  const avatar = office.avatars.find(a => a.sessionId === selected);
  return <>
    <div className="office-viewport" ref={viewport}>
      <div className="office-floor" style={{ width: office.width * 16 * scale, height: office.height * 16 * scale }}>
        <canvas ref={canvas} role="img" aria-label={`Office with ${awake.length} agents: ${awake.filter(s => s.status === "running").length} busy, ${awake.filter(s => s.needs_you).length} needs you, ${awake.filter(s => s.report_pending).length} reports, ${awake.filter(s => s.status === "error").length} errors`} style={{ width: office.width * 16 * scale, height: office.height * 16 * scale }} onClick={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
          const hit = [...hits.current].reverse().find(([, p]) => x >= p.x && x < p.x + 16 && y >= p.y && y < p.y + 24);
          if (hit && byId.has(hit[0])) setSelected(hit[0]);
        }} />
        {office.avatars.map(a => <button type="button" className="office-plate" data-testid="name-plate" key={a.key} tabIndex={-1} hidden={scale < 2 || byId.get(a.sessionId)?.status === "ended"} style={{ left: (a.deskTile.x * 16 + 8) * scale, top: (a.deskTile.y * 16 - 20) * scale, maxWidth: 46 * scale }} onClick={() => setSelected(a.sessionId)}>{a.name}<small>{a.app} · {a.project}{byId.get(a.sessionId)?.workspace.branch ? ` / ${byId.get(a.sessionId)!.workspace.branch}` : ""}</small></button>)}
      </div>
    </div>
    {loaded && !office.avatars.length && <p className="office-empty">Your office is quiet. Agents appear when their sessions connect. If an agent is running, install its hooks with <code>sekantor install claude --project</code>.</p>}
    <ul className="office-accessible" aria-label="Office agents">{office.avatars.filter(a => a.pose !== "leave").map(a => {
      const s = byId.get(a.sessionId)!;
      return <li key={a.key}><button type="button" onClick={() => setSelected(a.sessionId)}>{a.name}, {a.app}, {a.project}, {statusText(s)}</button></li>;
    })}</ul>
    {session && avatar && <AvatarCard key={session.session_id} session={session} avatar={avatar} onClose={() => setSelected(null)} />}
  </>;
}

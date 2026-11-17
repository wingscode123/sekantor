import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Session } from "../types";
import { layoutOffice, type Look } from "./model";
import { startRenderer } from "./render";
import { defaultTheme } from "./sprites";
import { AvatarCard, statusText } from "./AvatarCard";

export function OfficeView({ sessions }: { sessions: Session[] }) {
  const office = useMemo(() => layoutOffice(sessions), [sessions]);
  const current = useRef(office);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const hits = useRef(new Map<Look, { x: number; y: number }>());
  const [scale, setScale] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  useLayoutEffect(() => {
    current.current = office;
    const node = canvas.current;
    if (node && node.width !== office.width * 16) node.width = office.width * 16;
    if (node && node.height !== office.height * 16) node.height = office.height * 16;
    canvas.current?.dispatchEvent(new Event("officechange"));
  }, [office]);
  useEffect(() => {
    const measure = () => {
      const box = viewport.current;
      if (box) setScale(Math.max(1, Math.floor(Math.min(box.clientWidth / (office.width * 16), box.clientHeight / (office.height * 16)))));
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (viewport.current) observer?.observe(viewport.current);
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [office.width, office.height]);
  useEffect(() => {
    const node = canvas.current!;
    return startRenderer(node, () => current.current, { ...defaultTheme,
      furniture(kind, ctx, x, y, frame) {
        if (kind === "rack") hits.current.clear();
        defaultTheme.furniture(kind, ctx, x, y, frame);
      },
      character(look, pose, frame, ctx, x, y) {
        // Capture the actual rendered position, including walks and re-targets.
        hits.current.set(look, { x, y });
        defaultTheme.character(look, pose, frame, ctx, x, y);
      },
    });
  }, []);
  const session = sessions.find(s => s.session_id === selected);
  const avatar = office.avatars.find(a => a.sessionId === selected);
  return <>
    <div className="office-viewport" ref={viewport}>
      <div className="office-floor" style={{ width: office.width * 16 * scale, height: office.height * 16 * scale }}>
        <canvas ref={canvas} role="img" aria-label={`Office with ${sessions.length} agents: ${sessions.filter(s => s.status === "running").length} busy, ${sessions.filter(s => s.needs_you).length} needs you, ${sessions.filter(s => s.status === "error").length} errors`} style={{ width: office.width * 16 * scale, height: office.height * 16 * scale }} onClick={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
          const hit = [...current.current.avatars].reverse().find(a => {
            const p = hits.current.get(a.look);
            return p && x >= p.x && x < p.x + 16 && y >= p.y && y < p.y + 24;
          });
          if (hit) setSelected(hit.sessionId);
        }} />
        {office.avatars.map(a => <button type="button" className="office-plate" data-testid="name-plate" key={a.key} hidden={scale < 2} style={{ left: (a.deskTile.x * 16 + 8) * scale, top: (a.deskTile.y * 16 - 16) * scale, maxWidth: 46 * scale }} onClick={() => setSelected(a.sessionId)}>{a.name}<small>{a.app} · {a.project}{sessions.find(s => s.session_id === a.sessionId)?.workspace.branch ? ` / ${sessions.find(s => s.session_id === a.sessionId)!.workspace.branch}` : ""}</small></button>)}
      </div>
    </div>
    {!sessions.length && <p className="office-empty">Your office is quiet. Agents appear when their sessions connect.</p>}
    <ul className="office-accessible" aria-label="Office agents">{office.avatars.map(a => {
      const s = sessions.find(s => s.session_id === a.sessionId)!;
      return <li key={a.key}><button type="button" onClick={() => setSelected(a.sessionId)} onKeyDown={e => { if (e.key === "Enter") setSelected(a.sessionId); }}>{a.name}, {a.app}, {a.project}, {statusText(s)}</button></li>;
    })}</ul>
    {session && avatar && <AvatarCard key={session.session_id} session={session} avatar={avatar} onClose={() => setSelected(null)} />}
  </>;
}


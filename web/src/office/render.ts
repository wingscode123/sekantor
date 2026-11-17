import type { Avatar, Office } from "./model";
import { Departures, step, type Pt } from "./motion";
import { defaultTheme, type Theme } from "./sprites";

/** Dispatch `officechange` on the canvas after replacing an empty office, or restart this renderer. */
export function startRenderer(canvas: HTMLCanvasElement, getOffice: () => Office, theme: Theme = defaultTheme): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false, frame = 0, last = performance.now();
  let positions = new Map<string, Pt>();
  const retained = new Map<string, Avatar>(), departures = new Departures(), finished = new Set<string>();
  function tick() {
    timer = undefined;
    if (stopped || document.hidden) return;
    const office = getOffice(), now = performance.now(), dt = Math.min(250, now - last);
    last = now;
    const live = new Set(office.avatars.map(a => a.key));
    for (const key of finished) if (!live.has(key)) finished.delete(key);
    for (const avatar of office.avatars) {
      if (avatar.pose !== "leave") { finished.delete(avatar.key); departures.cancel(avatar.key); }
      if (!finished.has(avatar.key)) retained.set(avatar.key, avatar);
    }
    const targets = new Map<string, Pt>();
    for (const [key, avatar] of retained) {
      const leaving = !live.has(key) || avatar.pose === "leave";
      if (leaving) departures.mark(key);
      const target = leaving ? office.door : avatar.place === "desk" ? avatar.deskTile
        : avatar.place === "your_desk" ? office.yourDesk : avatar.place === "rack" ? office.rack
        : avatar.place === "pantry" ? office.pantry : office.door;
      targets.set(key, target);
      if (!positions.has(key)) positions.set(key, { ...office.door });
    }
    positions = step(positions, targets, dt);
    for (const [key, position] of positions) if (departures.leaving(key)) {
      departures.arrive(key, position, office.door);
      if (!departures.leaving(key)) { retained.delete(key); positions.delete(key); finished.add(key); }
    }
    // Keep a native-resolution backing store even in a smaller CSS viewport.
    if (canvas.width < office.width * 16) canvas.width = office.width * 16;
    if (canvas.height < office.height * 16) canvas.height = office.height * 16;
    const scale = Math.max(1, Math.floor(Math.min(canvas.width / (office.width * 16), canvas.height / (office.height * 16))));
    ctx!.setTransform(1, 0, 0, 1, 0, 0); ctx!.clearRect(0, 0, canvas.width, canvas.height);
    ctx!.setTransform(scale, 0, 0, scale, 0, 0); ctx!.imageSmoothingEnabled = false;
    for (let y = 0; y < office.height; y++) for (let x = 0; x < office.width; x++) theme.tile(y === 0 ? "wall" : "floor", ctx!, x * 16, y * 16);
    for (const cluster of office.clusters) for (const desk of cluster.desks) {
      theme.furniture("chair", ctx!, desk.x * 16, desk.y * 16 + 8);
      theme.furniture("desk", ctx!, desk.x * 16, desk.y * 16);
    }
    const drawnDesks = new Set(office.clusters.flatMap(c => c.desks.map(d => `${d.x},${d.y}`)));
    for (const avatar of retained.values()) if (!drawnDesks.has(`${avatar.deskTile.x},${avatar.deskTile.y}`)) {
      theme.furniture("desk", ctx!, avatar.deskTile.x * 16, avatar.deskTile.y * 16);
      drawnDesks.add(`${avatar.deskTile.x},${avatar.deskTile.y}`);
    }
    for (const [kind, point] of [["your_desk", office.yourDesk], ["rack", office.rack], ["coffee", office.pantry], ["door", office.door]] as const)
      theme.furniture(kind, ctx!, point.x * 16, point.y * 16, frame);
    theme.furniture("plant", ctx!, Math.max(0, office.width - 2) * 16, 16);
    for (const [key, avatar] of [...retained].sort((a, b) => positions.get(a[0])!.y - positions.get(b[0])!.y)) {
      const p = positions.get(key)!, target = targets.get(key)!;
      const moving = p.x !== target.x || p.y !== target.y;
      theme.character(avatar.look, moving ? "run" : avatar.pose, frame, ctx!, p.x * 16, p.y * 16 - 8);
    }
    frame++;
    if (office.avatars.some(a => !finished.has(a.key)) || retained.size) timer = setTimeout(tick, Math.ceil(1000 / 12));
  }
  function wake() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined; last = performance.now();
    if (!stopped && !document.hidden) tick();
  }
  const changed = () => { if (timer === undefined) wake(); };
  document.addEventListener("visibilitychange", wake); canvas.addEventListener("officechange", changed);
  tick();
  return () => { stopped = true; if (timer !== undefined) clearTimeout(timer); document.removeEventListener("visibilitychange", wake); canvas.removeEventListener("officechange", changed); };
}



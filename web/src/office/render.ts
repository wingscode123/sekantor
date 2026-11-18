import { isCorridorTile, route, type Avatar, type Office } from "./model";
import { Departures, followRoute, type Pt } from "./motion";
import { CHARACTER_HEIGHT, defaultTheme, TILE, type Theme } from "./sprites";

/** Native-pixel avatar top-left positions (32x48 sprites), keyed by avatar.key in paint order. */
export type FramePositions = ReadonlyMap<string, Readonly<Pt>>;

/** Dispatch `officechange` on the canvas after replacing an empty office, or restart this renderer. */
export function startRenderer(canvas: HTMLCanvasElement, getOffice: () => Office, theme: Theme = defaultTheme, onFrame?: (positions: FramePositions) => void): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false, frame = 0, last = performance.now();
  const positions = new Map<string, Pt>();
  const paths = new Map<string, { target: Pt; waypoints: Pt[] }>();
  let geometry: string | undefined;
  let previousOffice: Office | undefined;
  const retained = new Map<string, Avatar>(), departures = new Departures(), finished = new Set<string>();
  const live = new Set<string>(), targets = new Map<string, Pt>(), sorted: Avatar[] = [];
  const layer = document.createElement("canvas"), layerCtx = layer.getContext("2d");
  const layout: number[] = [], previousLayout: number[] = [];
  let lastOffice: Office | undefined, architecture = "", previousArchitecture = "";
  function addDesk(point: Pt) {
    for (let i = 10; i < layout.length; i += 2) if (layout[i] === point.x && layout[i + 1] === point.y) return;
    layout.push(point.x, point.y);
  }
  function staticLayer(office: Office) {
    const lobby = theme.room && theme.lobby && office.lobby.w > 0 ? office.lobby : undefined;
    const rooms = office.rooms;
    if (lastOffice !== office) {
      lastOffice = office;
      architecture = lobby ? JSON.stringify([lobby, rooms]) : "";
    }
    layout.length = 0;
    layout.push(office.width, office.height, office.yourDesk.x, office.yourDesk.y,
      office.rack.x, office.rack.y, office.pantry.x, office.pantry.y, office.door.x, office.door.y);
    if (lobby) {
      for (const room of rooms) for (const desk of room.desks) addDesk(desk);
    } else {
      for (const cluster of office.clusters) for (const desk of cluster.desks) addDesk(desk);
    }
    for (const avatar of retained.values()) addDesk(avatar.deskTile);
    let changed = architecture !== previousArchitecture || layout.length !== previousLayout.length;
    for (let i = 0; !changed && i < layout.length; i++) changed = layout[i] !== previousLayout[i];
    if (!changed || !layerCtx) return;
    previousArchitecture = architecture;
    previousLayout.length = 0;
    for (const value of layout) previousLayout.push(value);
    layer.width = office.width * TILE; layer.height = office.height * TILE;
    layerCtx.imageSmoothingEnabled = false;
    for (let y = 0; y < office.height; y++) for (let x = 0; x < office.width; x++) {
      const tile = lobby && isCorridorTile(lobby, x, y) ? "corridor" : !lobby && y === 0 ? "wall" : "floor";
      theme.tile(tile, layerCtx, x * TILE, y * TILE);
    }
    if (lobby) {
      for (const room of rooms) theme.room!(room.kind, layerCtx, room);
      theme.lobby!(layerCtx, lobby);
      for (const { pantry } of rooms) theme.furniture("coffee", layerCtx, pantry.x * TILE, pantry.y * TILE);
    } else for (let x = 0; x < office.width; x++) {
      const panel = x % 7;
      if (panel === 2 || panel === 3) {
        theme.furniture("window", layerCtx, x * TILE, 0);
        theme.furniture("sunlight", layerCtx, x * TILE, TILE);
      }
      if (panel === 1 || panel === 4) theme.furniture("lamp", layerCtx, x * TILE, 0);
      if (panel === 6) theme.furniture("bookshelf", layerCtx, x * TILE, 0);
    }
    for (let i = 10; i < layout.length; i += 2) {
      const x = layout[i] * TILE, y = layout[i + 1] * TILE;
      theme.furniture("rug", layerCtx, x, y + TILE / 2);
      theme.furniture("chair", layerCtx, x, y + TILE / 2);
      theme.furniture("desk", layerCtx, x, y);
    }
    if (lobby) return;
    theme.furniture("rug", layerCtx, office.door.x * TILE, (office.door.y + 1) * TILE);
    theme.furniture("rug", layerCtx, office.pantry.x * TILE, (office.pantry.y + 1) * TILE);
    theme.furniture("chair", layerCtx, office.yourDesk.x * TILE, office.yourDesk.y * TILE + TILE / 2);
    theme.furniture("your_desk", layerCtx, office.yourDesk.x * TILE, office.yourDesk.y * TILE);
    theme.furniture("coffee", layerCtx, office.pantry.x * TILE, office.pantry.y * TILE);
    theme.furniture("door", layerCtx, office.door.x * TILE, office.door.y * TILE);
    theme.furniture("plant", layerCtx, Math.max(0, office.width - 2) * TILE, TILE);
    theme.furniture("plant", layerCtx, (office.pantry.x + 1) * TILE, office.pantry.y * TILE);
  }
  function tick() {
    timer = undefined;
    if (stopped || document.hidden) return;
    const office = getOffice(), now = performance.now(), dt = Math.min(250, now - last);
    last = now;
    live.clear();
    for (const avatar of office.avatars) live.add(avatar.key);
    for (const key of finished) if (!live.has(key)) finished.delete(key);
    for (const avatar of office.avatars) {
      if (avatar.pose !== "leave") { finished.delete(avatar.key); departures.cancel(avatar.key); }
      if (!finished.has(avatar.key)) retained.set(avatar.key, avatar);
    }
    if (office !== previousOffice) {
      const nextGeometry = JSON.stringify([office.width, office.height, office.lobby,
        office.rooms.map(({ x, y, w, h, door }) => [x, y, w, h, door])]);
      if (nextGeometry !== geometry) {
        paths.clear();
        geometry = nextGeometry;
      }
      previousOffice = office;
    }
    targets.clear();
    for (const [key, avatar] of retained) {
      const leaving = !live.has(key) || avatar.pose === "leave";
      if (leaving) departures.mark(key);
      const target = leaving ? office.door : avatar.targetTile ? avatar.targetTile : avatar.place === "desk" ? avatar.deskTile
        : avatar.place === "your_desk" ? office.yourDesk : avatar.place === "rack" ? office.rack
        : avatar.place === "pantry" ? office.pantry : office.door;
      targets.set(key, target);
      let position = positions.get(key) ?? office.door;
      let path = paths.get(key);
      if (!path || path.target.x !== target.x || path.target.y !== target.y) {
        const waypoints = route(office, position, target);
        // A reflow can leave a previous position outside the new walkable layout.
        if (!waypoints.length) position = target;
        path = { target, waypoints };
        paths.set(key, path);
      }
      positions.set(key, followRoute(position, path.waypoints, dt));
    }
    for (const [key, position] of positions) if (departures.leaving(key)) {
      departures.arrive(key, position, office.door);
      if (!departures.leaving(key)) { retained.delete(key); positions.delete(key); paths.delete(key); finished.add(key); }
    }
    ctx!.setTransform(1, 0, 0, 1, 0, 0); ctx!.clearRect(0, 0, canvas.width, canvas.height);
    ctx!.setTransform(canvas.width / (office.width * TILE), 0, 0, canvas.height / (office.height * TILE), 0, 0); ctx!.imageSmoothingEnabled = false;
    staticLayer(office);
    ctx!.drawImage(layer, 0, 0);
    // Working racks blink; themed decor stays in the static layer.
    if (office.lobby.w > 0 && theme.room && theme.lobby) {
      for (const { rack } of office.rooms) theme.furniture("rack", ctx!, rack.x * TILE, rack.y * TILE, frame);
    } else {
      theme.furniture("rack", ctx!, office.rack.x * TILE, office.rack.y * TILE, frame);
    }
    sorted.length = 0;
    for (const avatar of retained.values()) sorted.push(avatar);
    sorted.sort((a, b) => positions.get(a.key)!.y - positions.get(b.key)!.y);
    const framePositions = onFrame ? new Map<string, Pt>() : undefined;
    for (const avatar of sorted) {
      const p = positions.get(avatar.key)!, target = targets.get(avatar.key)!;
      const moving = p.x !== target.x || p.y !== target.y;
      const x = p.x * TILE, y = p.y * TILE - (CHARACTER_HEIGHT - TILE);
      framePositions?.set(avatar.key, { x, y });
      theme.character(avatar.look, moving ? "run" : avatar.pose, frame, ctx!, x, y);
    }
    if (framePositions) onFrame!(framePositions);
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

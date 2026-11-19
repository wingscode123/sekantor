import { isCorridorTile, isWalkable, route, SUBAGENT_REPORT_MS, type Avatar, type Office } from "./model";
import { Departures, followRoute, type Pt } from "./motion";
import { drawWaitMark } from "./waitmark";
import { CHARACTER_HEIGHT, defaultTheme, TILE, type Theme } from "./sprites";

/** Native-pixel avatar top-left positions (32x48 sprites), keyed by avatar.key in paint order. */
export type FramePositions = ReadonlyMap<string, Readonly<Pt>>;

const walkedReports = new Map<string, number>();

function claimTeamReport(sessionId: string, since: string): boolean {
  const now = Date.now(), started = Date.parse(since), expiry = started + SUBAGENT_REPORT_MS;
  if (!(started <= now && now < expiry)) return false;
  const id = JSON.stringify([sessionId, since]);
  if (walkedReports.has(id)) return false;
  for (const [key, until] of walkedReports) if (until <= now) walkedReports.delete(key);
  walkedReports.set(id, expiry);
  return true;
}

/** Dispatch `officechange` on the canvas after replacing an empty office, or restart this renderer. */
export function startRenderer(canvas: HTMLCanvasElement, getOffice: () => Office, theme: Theme = defaultTheme, onFrame?: (positions: FramePositions) => void, onJuniorDeparture?: (keys: string[]) => void): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false, frame = 0, last = performance.now();
  const positions = new Map<string, Pt>();
  const paths = new Map<string, { target: Pt; waypoints: Pt[] }>();
  let geometry: string | undefined;
  let previousOffice: Office | undefined;
  const handoffs = new Map<string, { remaining: number; delivered: boolean; since?: string }>();
  const receiving = new Set<string>();
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
      for (const avatar of retained.values()) {
        const room = rooms.find(r => r.project === avatar.project);
        if (room && !avatar.junior && avatar.deskTile.x > room.x && avatar.deskTile.x < room.x + room.w - 1 &&
            avatar.deskTile.y > room.y && avatar.deskTile.y < room.y + room.h - 1) {
          addDesk(avatar.deskTile);
        }
      }
    } else {
      for (const cluster of office.clusters) for (const desk of cluster.desks) addDesk(desk);
      for (const avatar of retained.values()) addDesk(avatar.deskTile);
    }
    let changed = architecture !== previousArchitecture || layout.length !== previousLayout.length;
    for (let i = 0; !changed && i < layout.length; i++) changed = layout[i] !== previousLayout[i];
    if (!changed || !layerCtx) return;
    previousArchitecture = architecture;
    previousLayout.length = 0;
    for (const value of layout) previousLayout.push(value);
    layer.width = office.width * TILE; layer.height = office.height * TILE;
    layerCtx.imageSmoothingEnabled = false;
    for (let y = 0; y < office.height; y++) for (let x = 0; x < office.width; x++) {
      if (lobby) {
        if (isCorridorTile(lobby, x, y)) {
          theme.tile("corridor", layerCtx, x * TILE, y * TILE);
        } else if (rooms.some(r => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h)) {
          theme.tile("floor", layerCtx, x * TILE, y * TILE);
        }
      } else {
        theme.tile(y === 0 ? "wall" : "floor", layerCtx, x * TILE, y * TILE);
      }
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
    const juniorDepartures: string[] = [];
    live.clear();
    for (const avatar of office.avatars) live.add(avatar.key);
    for (const key of finished) if (!live.has(key)) finished.delete(key);
    for (const avatar of office.avatars) {
      if (avatar.junior?.status === "reported" && !retained.has(avatar.key) && !finished.has(avatar.key)) {
        // A junior first seen as reported has already handed off.
        finished.add(avatar.key);
        juniorDepartures.push(avatar.key);
      }
      if (avatar.pose !== "leave" && avatar.junior?.status !== "reported") {
        finished.delete(avatar.key);
        departures.cancel(avatar.key);
        if (!avatar.teamReport) handoffs.delete(avatar.key);
      }
      if (!finished.has(avatar.key)) retained.set(avatar.key, avatar);
    }
    if (office !== previousOffice) {
      const nextGeometry = JSON.stringify([office.width, office.height, office.lobby,
        office.rooms.map(({ x, y, w, h, door }) => [x, y, w, h, door])]);
      if (nextGeometry !== geometry) {
        if (previousOffice) {
          const roomOf = (o: Office, project: string) => o.rooms.find(r => r.project === project);
          const inLobby = (o: Office, p: Pt) => p.x >= o.lobby.x && p.x < o.lobby.x + o.lobby.w && p.y >= o.lobby.y && p.y < o.lobby.y + o.lobby.h;
          for (const [key, avatar] of retained) {
            const prevRoom = roomOf(previousOffice, avatar.project), nextRoom = roomOf(office, avatar.project);
            const roomShift = prevRoom && nextRoom ? { x: nextRoom.x - prevRoom.x, y: nextRoom.y - prevRoom.y } : undefined;
            const lobbyShift = { x: office.lobby.x - previousOffice.lobby.x, y: office.lobby.y - previousOffice.lobby.y };
            // Departing avatars still carry the old layout's desk: move it with its room.
            if (!live.has(key) && roomShift) {
              retained.set(key, { ...avatar, deskTile: { x: avatar.deskTile.x + roomShift.x, y: avatar.deskTile.y + roomShift.y } });
            }
            const pos = positions.get(key);
            if (!pos) continue;
            const shift = inLobby(previousOffice, pos) || !roomShift ? lobbyShift : roomShift;
            const translated = { x: pos.x + shift.x, y: pos.y + shift.y };
            if (isWalkable(office, { x: Math.round(translated.x), y: Math.round(translated.y) })) positions.set(key, translated);
            else positions.set(key, avatar.targetTile ?? avatar.deskTile);
          }
        }
        paths.clear();
        geometry = nextGeometry;
      }
      previousOffice = office;
    }
    targets.clear();
    receiving.clear();
    for (const [key, avatar] of retained) {
      const junior = avatar.junior;
      const report = avatar.teamReport;
      const isLive = live.has(key);
      let handoff = handoffs.get(key);
      if (isLive && !handoff && junior?.status === "reported") {
        handoff = { remaining: 750, delivered: false };
        handoffs.set(key, handoff);
      }
      if (isLive && report && handoff?.since !== report.since) {
        handoff = { remaining: 750, delivered: !claimTeamReport(avatar.sessionId, report.since), since: report.since };
        handoffs.set(key, handoff);
      }
      const leaving = !isLive || avatar.pose === "leave" || (junior && handoff?.delivered);
      if (leaving) departures.mark(key);
      const exit = junior && (isLive ? junior.door : office.rooms.find(r => r.project === avatar.project)?.door);
      const meeting = handoff && !handoff.delivered ? (report?.meeting ?? junior?.meeting) : undefined;
      const target = leaving ? exit || office.door
        : meeting ?? (avatar.targetTile ? avatar.targetTile : avatar.place === "desk" ? avatar.deskTile
        : avatar.place === "your_desk" ? office.yourDesk : avatar.place === "rack" ? office.rack
        : avatar.place === "pantry" ? office.pantry : office.door);
      targets.set(key, target);
      let position = positions.get(key) ?? (junior || report ? avatar.deskTile : office.door);
      let path = paths.get(key);
      if (!path || path.target.x !== target.x || path.target.y !== target.y) {
        const waypoints = route(office, position, target);
        // A reflow can leave a previous position outside the new walkable layout.
        if (!waypoints.length && (position.x !== target.x || position.y !== target.y)) position = target;
        path = { target, waypoints };
        paths.set(key, path);
      }
      const wasAtMeeting = handoff && !leaving && position.x === target.x && position.y === target.y;
      position = followRoute(position, path.waypoints, dt);
      positions.set(key, position);
      if (handoff && meeting && !leaving && position.x === target.x && position.y === target.y) {
        const recipient = report ? report.lead : avatar.sessionId;
        if (recipient) receiving.add(recipient);
        if (wasAtMeeting) handoff.remaining -= dt;
        handoff.delivered = handoff.remaining <= 0;
      }
    }
    for (const [key, position] of positions) if (departures.leaving(key)) {
      departures.arrive(key, position, targets.get(key)!);
      if (!departures.leaving(key)) {
        if (retained.get(key)?.junior) juniorDepartures.push(key);
        retained.delete(key);
        positions.delete(key);
        paths.delete(key);
        handoffs.delete(key);
        finished.add(key);
      }
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
      const x = p.x * TILE;
      const y = (p.y + 1) * TILE - CHARACTER_HEIGHT;
      framePositions?.set(avatar.key, { x, y });
      const handoff = handoffs.get(avatar.key);
      const pose = avatar.junior
        ? departures.leaving(avatar.key) ? "leave"
          : avatar.pose === "deliver" && !moving ? "report" : avatar.pose
        : avatar.teamReport && handoff && !handoff.delivered && !departures.leaving(avatar.key) ? moving ? "deliver" : "report"
        : receiving.has(avatar.sessionId) ? "receive" : moving ? "run" : avatar.pose;
      if (avatar.junior) theme.character(avatar.look, pose, frame, ctx!, x, y, true);
      else theme.character(avatar.look, pose, frame, ctx!, x, y);
      if (avatar.waitingSince && pose === "ask") drawWaitMark(ctx!, x, y, Date.now() - Date.parse(avatar.waitingSince), frame);
    }
    if (framePositions) onFrame!(framePositions);
    if (juniorDepartures.length) onJuniorDeparture?.(juniorDepartures);
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

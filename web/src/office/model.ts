import type { Session } from "../types";
import type { Pt } from "./motion";

export type Kind = "web" | "backend" | "data" | "mobile" | "game" | "infra" | "docs" | "other";
export type Place = "desk" | "your_desk" | "rack" | "pantry" | "door";
export type Pose = "type" | "read" | "run" | "web" | "work" | "ask" | "smoke" | "coffee" | "leave" | "report";
export interface Look { body: number; hair: number; shirt: number; accessory: number }
export interface Avatar {
  key: string; sessionId: string; identity: string; seat: number; look: Look;
  place: Place; pose: Pose; targetTile?: { x: number; y: number }; deskTile: { x: number; y: number }; name: string; app: string; project: string;
}
export interface Cluster { project: string; origin: { x: number; y: number }; desks: { x: number; y: number }[] }
export interface Room {
  project: string; kind: Kind; x: number; y: number; w: number; h: number;
  door: Pt; sign: Pt; desks: Pt[]; rack: Pt; pantry: Pt;
}
const VALID_KINDS = new Set<Kind>(["web", "backend", "data", "mobile", "game", "infra", "docs", "other"]);
export function normaliseKind(kind: unknown): Kind {
  return typeof kind === "string" && VALID_KINDS.has(kind as Kind) ? (kind as Kind) : "other";
}
export interface Lobby { x: number; y: number; w: number; h: number; yourDesk: Pt; door: Pt; corridorY: number; numCols?: number }
export interface PlaceLabel { kind: Exclude<Place, "desk">; at: Pt; room?: string }
export interface Office {
  rooms: Room[]; lobby: Lobby; places: PlaceLabel[];
  width: number; height: number; clusters: Cluster[]; yourDesk: { x: number; y: number };
  rack: { x: number; y: number }; pantry: { x: number; y: number }; door: { x: number; y: number }; avatars: Avatar[];
}

function isOpenBot(s: Session): boolean { return s.source === "openbot" || s.host?.app === "openbot"; }
function projectOf(s: Session): string {
  if (isOpenBot(s)) return "OpenBot agents";
  return s.project?.name || s.workspace?.cwd?.split(/[\\/]+/).filter(Boolean).at(-1) || "unknown";
}
function appOf(s: Session): string { return s.host?.app || s.source || "unknown"; }
export function identityOf(s: Session): string {
  return `${appOf(s)}|${isOpenBot(s) ? s.agent?.name || "unknown" : projectOf(s)}`;
}
export function poseFor(s: Session): { place: Place; pose: Pose } {
  switch (s.status) {
    case "waiting_approval": return { place: "your_desk", pose: "ask" };
    case "waiting_input":
      return s.needs_you ? { place: "your_desk", pose: "ask" } : { place: "pantry", pose: "coffee" };
    case "reported":
      return s.report_pending ? { place: "your_desk", pose: "report" } : { place: "pantry", pose: "coffee" };
    case "error": return { place: "desk", pose: "smoke" };
    case "done": return { place: "pantry", pose: "coffee" };
    case "ended": return { place: "door", pose: "leave" };
  }
  switch (s.activity?.kind) {
    case "read": return { place: "desk", pose: "read" };
    case "edit": return { place: "desk", pose: "type" };
    case "run": return { place: "rack", pose: "run" };
    case "web": return { place: "desk", pose: "web" };
    default: return { place: "desk", pose: "work" };
  }
}
export function lookFor(identity: string, seat: number): Look {
  let hash = 2166136261;
  for (const c of identity) hash = Math.imul(hash ^ c.charCodeAt(0), 16777619) >>> 0;
  // Offset the palette tuple by seat so neighbouring colleagues always differ.
  const value = (hash + seat) >>> 0;
  return { body: Math.floor(value / 8) % 4, hair: Math.floor(value / 32) % 8,
    shirt: value % 8, accessory: Math.floor(value / 256) % 4 };
}
const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;
export const GHOST_MS = 20_000;
export function isGhost(s: Session, now: number): boolean {
  const ended = Date.parse(s.ended_at || "");
  return s.status === "ended" && ended <= now && now < ended + GHOST_MS;
}
export const ROOM_WIDTH = 14;
export const CORRIDOR_WIDTH = 3;
const slot = (anchor: Pt, i: number): Pt => ({
  x: anchor.x + i % 6, y: anchor.y + 1 + Math.floor(i / 6),
});

export function layoutOffice(sessions: Session[], now = Date.now(), availableWidth?: number): Office {
  const ordered = sessions.filter(s => s.status !== "ended" || isGhost(s, now))
    .sort((a, b) => compare(a.started_at, b.started_at) || compare(a.session_id, b.session_id));
  const membersByProject = new Map<string, Session[]>();
  for (const s of ordered) {
    const project = projectOf(s);
    const members = membersByProject.get(project) ?? [];
    members.push(s);
    membersByProject.set(project, members);
  }

  const numCols = availableWidth !== undefined
    ? Math.max(2, Math.floor((availableWidth + CORRIDOR_WIDTH) / (ROOM_WIDTH + CORRIDOR_WIDTH)))
    : 2;
  const officeWidth = numCols * ROOM_WIDTH + (numCols - 1) * CORRIDOR_WIDTH;
  const centre = Math.floor(officeWidth / 2);

  const rooms: Room[] = [], avatars: Avatar[] = [], places: PlaceLabel[] = [];
  const projects = [...membersByProject.keys()].sort(compare);
  let y = 0, rowHeight = 0;
  for (const [index, project] of projects.entries()) {
    const members = membersByProject.get(project)!;
    const col = index % numCols;
    const x = col * (ROOM_WIDTH + CORRIDOR_WIDTH);
    const furnitureY = y + 3 + Math.ceil(members.length / 4) * 2;
    const h = furnitureY - y + Math.ceil(members.length / 6) + 2;
    const doorOnRight = col === 0 || (col < numCols - 1 && col % 2 === 0);
    const doorX = doorOnRight ? x + ROOM_WIDTH - 1 : x;
    const room: Room = {
      project, kind: normaliseKind(members.find(s => s.project)?.project?.kind), x, y, w: ROOM_WIDTH, h,
      door: { x: doorX, y: y + h - 2 },
      sign: { x: x + Math.floor(ROOM_WIDTH / 2), y },
      desks: [],
      rack: { x: x + 1, y: furnitureY },
      pantry: { x: x + 7, y: furnitureY },
    };
    rooms.push(room);
    places.push({ kind: "rack", at: room.rack, room: project }, { kind: "pantry", at: room.pantry, room: project });
    const seats = new Map<string, number>();
    let rackCount = 0, pantryCount = 0;
    for (const [i, s] of members.entries()) {
      const deskTile = { x: x + 2 + i % 4 * 3, y: y + 2 + Math.floor(i / 4) * 2 };
      room.desks.push(deskTile);
      const identity = identityOf(s);
      const seat = seats.get(identity) ?? 0;
      seats.set(identity, seat + 1);
      const { place, pose } = poseFor(s);
      const targetTile = place === "rack" ? slot(room.rack, rackCount++)
        : place === "pantry" ? slot(room.pantry, pantryCount++) : deskTile;
      avatars.push({ key: s.session_id, sessionId: s.session_id, identity, seat, look: lookFor(identity, seat),
        place, pose, deskTile, targetTile, name: s.agent?.name || s.source_label || appOf(s), app: s.host_label || appOf(s), project });
    }
    rowHeight = Math.max(h, rowHeight);
    if (col === numCols - 1) {
      y += rowHeight + 1;
      rowHeight = 0;
    }
  }

  const lobbyY = y + (rowHeight ? rowHeight + 1 : 1);
  const lobbyRows = Math.ceil(avatars.length / 6);
  const lobby: Lobby = {
    x: centre - 8, y: lobbyY, w: 17, h: 5 + lobbyRows,
    yourDesk: { x: centre, y: lobbyY + 2 },
    door: { x: centre, y: lobbyY + 4 + lobbyRows },
    corridorY: lobbyY - 1,
    numCols,
  };
  places.push({ kind: "your_desk", at: lobby.yourDesk }, { kind: "door", at: lobby.door });
  const bySession = new Map(avatars.map(a => [a.sessionId, a]));
  let waiting = 0;
  for (const s of ordered) {
    const avatar = bySession.get(s.session_id)!;
    if (avatar.place === "your_desk") {
      const point = slot(lobby.yourDesk, waiting++);
      avatar.targetTile = { x: point.x - 2, y: point.y };
    }
    if (avatar.place === "door") avatar.targetTile = lobby.door;
  }

  return {
    width: officeWidth, height: lobby.y + lobby.h, rooms, lobby, places, avatars,
    clusters: rooms.map(room => ({ project: room.project, origin: room.desks[0], desks: room.desks })),
    yourDesk: lobby.yourDesk, door: lobby.door,
    rack: rooms[0]?.rack ?? { x: lobby.x + 1, y: lobby.y + 2 },
    pantry: rooms[0]?.pantry ?? { x: lobby.x + lobby.w - 2, y: lobby.y + 2 },
  };
}

export function roomSignWidth(room: Room): number {
  return 2 * Math.min(2, room.sign.x - room.x - 1, room.x + room.w - 2 - room.sign.x) + 1;
}

export function isCorridorTile(lobby: Lobby, x: number, y: number): boolean {
  if (y > lobby.corridorY) return false;
  if (!lobby.numCols || lobby.numCols <= 2) {
    return Math.abs(x - lobby.door.x) <= (CORRIDOR_WIDTH - 1) / 2;
  }
  const numCorridors = lobby.numCols - 1;
  for (let k = 0; k < numCorridors; k++) {
    const corrX = (k + 1) * ROOM_WIDTH + k * CORRIDOR_WIDTH;
    if (x >= corrX && x < corrX + CORRIDOR_WIDTH) return true;
  }
  if (y === lobby.corridorY) {
    const minX = Math.min(ROOM_WIDTH, lobby.door.x - 1);
    const maxX = Math.max(numCorridors * (ROOM_WIDTH + CORRIDOR_WIDTH) - 1, lobby.door.x + 1);
    if (x >= minX && x <= maxX) return true;
  }
  return false;
}

export function isWalkable(office: Office, point: Pt): boolean {
  if (point.x < 0 || point.y < 0 || point.x >= office.width || point.y >= office.height) return false;
  const bounds = [...office.rooms, office.lobby].find(({ x, y, w, h }) =>
    point.x >= x && point.x < x + w && point.y >= y && point.y < y + h);
  if (!bounds) {
    if (!office.lobby.w) return true; // The mini office has an open floor.
    return isCorridorTile(office.lobby, point.x, point.y);
  }
  if (point.x === bounds.door.x && point.y === bounds.door.y) return true;
  if (bounds === office.lobby && point.x === bounds.door.x && point.y === bounds.y) return true;
  return point.x > bounds.x && point.x < bounds.x + bounds.w - 1
    && point.y > bounds.y && point.y < bounds.y + bounds.h - 1;
}

function bfsPath(office: Office, start: Pt, to: Pt): Pt[] | null {
  if (!isWalkable(office, start) || !isWalkable(office, to)) return null;
  if (start.x === to.x && start.y === to.y) return [];
  const key = ({ x, y }: Pt) => y * office.width + x;
  const parents = new Map<number, Pt | null>([[key(start), null]]);
  const queue = [start];
  for (let i = 0; i < queue.length; i++) {
    const point = queue[i];
    if (point.x === to.x && point.y === to.y) {
      const path: Pt[] = [];
      for (let p = point; p !== start; p = parents.get(key(p))!) path.push(p);
      return path.reverse();
    }
    for (const next of [
      { x: point.x + 1, y: point.y }, { x: point.x - 1, y: point.y },
      { x: point.x, y: point.y + 1 }, { x: point.x, y: point.y - 1 },
    ]) {
      const id = key(next);
      if (parents.has(id) || !isWalkable(office, next)) continue;
      parents.set(id, point);
      queue.push(next);
    }
  }
  return null;
}

/** Return axis-aligned waypoints, excluding the starting tile. */
export function route(office: Office, from: Pt, to: Pt): Pt[] {
  if (!isWalkable(office, to)) return [];
  const isIntX = Math.abs(from.x - Math.round(from.x)) < 1e-6;
  const isIntY = Math.abs(from.y - Math.round(from.y)) < 1e-6;
  if (isIntX && isIntY) {
    const start = { x: Math.round(from.x), y: Math.round(from.y) };
    const path = bfsPath(office, start, to);
    return path ?? [];
  }
  const x1 = Math.floor(from.x), x2 = Math.ceil(from.x);
  const y1 = Math.floor(from.y), y2 = Math.ceil(from.y);
  const p1 = { x: x1, y: y1 };
  const p2 = isIntX ? { x: x1, y: y2 } : { x: x2, y: y1 };

  const candidates: { first: Pt; path: Pt[]; cost: number }[] = [];
  for (const p of [p1, p2]) {
    if (!isWalkable(office, p)) continue;
    const distToP = Math.abs(from.x - p.x) + Math.abs(from.y - p.y);
    const subPath = bfsPath(office, p, to);
    if (subPath !== null) {
      candidates.push({
        first: p,
        path: subPath,
        cost: distToP + subPath.length,
      });
    }
  }
  if (!candidates.length) return [];
  candidates.sort((a, b) => a.cost - b.cost);
  const best = candidates[0];
  if (Math.abs(from.x - best.first.x) > 1e-6 || Math.abs(from.y - best.first.y) > 1e-6) {
    return [best.first, ...best.path];
  }
  return best.path;
}

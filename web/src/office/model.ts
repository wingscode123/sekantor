import type { Session } from "../types";
import type { Pt } from "./motion";

export type Kind = "web" | "backend" | "data" | "mobile" | "game" | "infra" | "docs" | "other";
export interface Room {
  project: string; kind: Kind; x: number; y: number; w: number; h: number;
  door: Pt; sign: Pt; desks: Pt[]; rack: Pt; pantry: Pt;
}
export interface Lobby {
  x: number; y: number; w: number; h: number; yourDesk: Pt; door: Pt; corridorY: number;
}

export type Place = "desk" | "your_desk" | "rack" | "pantry" | "door";
export type Pose = "type" | "read" | "run" | "web" | "work" | "ask" | "smoke" | "coffee" | "leave" | "report";
export interface Look { body: number; hair: number; shirt: number; accessory: number }
export interface Avatar {
  key: string; sessionId: string; identity: string; seat: number; look: Look;
  place: Place; pose: Pose; targetTile?: { x: number; y: number }; deskTile: { x: number; y: number }; name: string; app: string; project: string;
}
export interface Cluster { project: string; origin: { x: number; y: number }; desks: { x: number; y: number }[] }
export interface Office {
  rooms?: Room[]; lobby?: Lobby;
  width: number; height: number; clusters: Cluster[]; yourDesk: { x: number; y: number };
  rack: { x: number; y: number }; pantry: { x: number; y: number }; door: { x: number; y: number }; avatars: Avatar[];
}

function isOpenBot(s: Session): boolean { return s.source === "openbot" || s.host?.app === "openbot"; }
function projectOf(s: Session): string {
  if (isOpenBot(s)) return "OpenBot agents";
  return s.workspace?.cwd?.split(/[\\/]+/).filter(Boolean).at(-1) || "unknown";
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
export function layoutOffice(sessions: Session[], now = Date.now()): Office {
  const clusters: Cluster[] = [];
  const avatars: Avatar[] = [];
  const seats = new Map<string, number>();
  const assigned = new Map<string, number>();
  // Recent leavers reserve their desk and cluster until the departure grace expires.
  const ordered = sessions.filter(s => s.status !== "ended" || isGhost(s, now)).sort((a, b) => compare(a.started_at, b.started_at) || compare(a.session_id, b.session_id));
  for (const s of ordered) {
    const identity = identityOf(s);
    const seat = seats.get(identity) || 0;
    assigned.set(s.session_id, seat);
    seats.set(identity, seat + 1);
  }
  const projects = [...new Set(ordered.map(projectOf))].sort(compare);
  for (const project of projects) {
    const members = ordered.filter(s => projectOf(s) === project);
    for (let start = 0; start < members.length; start += 8) {
      const index = clusters.length;
      const origin = { x: 2 + (index % 2) * 14, y: 4 + Math.floor(index / 2) * 8 };
      const cluster: Cluster = { project, origin, desks: [] };
      for (const [i, s] of members.slice(start, start + 8).entries()) {
        const deskTile = { x: origin.x + (i % 4) * 3, y: origin.y + Math.floor(i / 4) * 3 };
        cluster.desks.push(deskTile);
        const identity = identityOf(s);
        const seat = assigned.get(s.session_id) ?? 0;
        avatars.push({ key: s.session_id, sessionId: s.session_id, identity, seat,
          look: lookFor(identity, seat), ...poseFor(s), deskTile,
          name: s.agent?.name || s.source_label || appOf(s), app: s.host_label || appOf(s), project });
      }
      clusters.push(cluster);
    }
  }
  const height = 8 + Math.ceil(clusters.length / 2) * 8;
  const office: Office = { width: 30, height, clusters, avatars, door: { x: 1, y: 1 },
    rack: { x: 2, y: height - 3 }, pantry: { x: 22, y: height - 3 }, yourDesk: { x: 12, y: height - 3 } };
  const bySession = new Map(avatars.map(a => [a.sessionId, a]));
  const slots = new Map<Place, number>();
  // Slot order follows start time/id, independent of project grouping or input order.
  for (const s of ordered) {
    const a = bySession.get(s.session_id)!;
    if (a.place === "desk") { a.targetTile = a.deskTile; continue; }
    if (a.place === "door") { a.targetTile = office.door; continue; }
    const anchor = a.place === "your_desk" ? office.yourDesk : a.place === "rack" ? office.rack : office.pantry;
    const k = slots.get(a.place) || 0;
    slots.set(a.place, k + 1);
    // Separate six-column blocks below the clusters, one row below furniture.
    a.targetTile = { x: anchor.x + k % 6, y: anchor.y + 1 + Math.floor(k / 6) };
    office.height = Math.max(office.height, a.targetTile.y + 2);
  }
  return office;
}

import type { Session } from "../types";

export type Place = "desk" | "your_desk" | "rack" | "pantry" | "door";
export type Pose = "type" | "read" | "run" | "web" | "work" | "ask" | "smoke" | "coffee" | "leave";
export interface Look { body: number; hair: number; shirt: number; accessory: number }
export interface Avatar {
  key: string; sessionId: string; identity: string; seat: number; look: Look;
  place: Place; pose: Pose; targetTile?: { x: number; y: number }; deskTile: { x: number; y: number }; name: string; app: string; project: string;
}
export interface Cluster { project: string; origin: { x: number; y: number }; desks: { x: number; y: number }[] }
export interface Office {
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
    case "waiting_approval": case "waiting_input": return { place: "your_desk", pose: "ask" };
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
export function layoutOffice(sessions: Session[]): Office {
  const clusters: Cluster[] = [];
  const avatars: Avatar[] = [];
  const seats = new Map<string, number>();
  const assigned = new Map<string, number>();
  // Live colleagues take the lowest seats. Ended sessions remain in this snapshot
  // for the renderer to animate leaving, without reserving a live identity seat.
  const ordered = sessions.filter(s => s.status !== "ended").sort((a, b) => compare(a.started_at, b.started_at) || compare(a.session_id, b.session_id));
  for (const s of ordered) {
    if (s.status === "ended") continue;
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
    rack: { x: 5, y: 1 }, pantry: { x: 27, y: 1 }, yourDesk: { x: 15, y: height - 3 } };
  const bySession = new Map(avatars.map(a => [a.sessionId, a]));
  const slots = new Map<Place, number>();
  // Slot order follows start time/id, independent of project grouping or input order.
  for (const s of ordered) {
    const a = bySession.get(s.session_id)!;
    if (a.place === "desk") { a.targetTile = a.deskTile; continue; }
    const anchor = a.place === "your_desk" ? office.yourDesk : a.place === "rack" ? office.rack : office.pantry;
    const k = slots.get(a.place) || 0;
    slots.set(a.place, k + 1);
    const offset = anchor.x - 1 + k;
    a.targetTile = { x: 1 + offset % (office.width - 2), y: anchor.y + Math.floor(offset / (office.width - 2)) };
    office.height = Math.max(office.height, a.targetTile.y + 2);
  }
  return office;
}

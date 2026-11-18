import { describe, expect, it } from "vitest";
import type { Session, Status } from "../types";
import { identityOf, layoutOffice, lookFor, poseFor } from "./model";

const session = (overrides: Partial<Session> = {}): Session => ({
  session_id: "one", source: "claude_code", source_label: "Claude Code",
  status: "running", status_since: "2026-01-01", started_at: "2026-01-01",
  last_event_at: "2026-01-01", workspace: { cwd: "/repos/ronda" },
  host: { app: "orca", confidence: 1, via: [] }, capabilities: [], needs_you: false,
  ...overrides,
});

describe("poseFor", () => {
  const statuses: [Status, string, string][] = [
    ["waiting_approval", "your_desk", "ask"], ["waiting_input", "your_desk", "ask"],
    ["error", "desk", "smoke"], ["done", "pantry", "coffee"], ["ended", "door", "leave"],
  ];
  const activities = ["read", "edit", "run", "web", "other", null] as const;
  for (const kind of activities) {
    const activity = kind ? { kind, tool: "tool" } : null;
    for (const [status, place, pose] of statuses) {
      it(`${status} overrides ${kind}`, () => {
        expect(poseFor(session({ status, activity, needs_you: status === "waiting_input" }))).toEqual({ place, pose });
      });
    }
    it(`running ${kind}`, () => {
      expect(poseFor(session({ activity }))).toEqual({
        place: kind === "run" ? "rack" : "desk",
        pose: kind === "edit" ? "type" : kind === "other" || kind === null ? "work" : kind,
      });
    });
  }
});

it("identifies Claude Code by app/project and OpenBot by app/agent", () => {
  expect(identityOf(session())).toBe("orca|ronda");
  expect(identityOf(session({ source: "openbot", agent: { name: "Builder" } }))).toBe("orca|Builder");
  expect(identityOf(session({ workspace: { cwd: "C:\\repos\\ronda\\" } }))).toBe("orca|ronda");
});

it("assigns seats in start order with distinct stable looks", () => {
  const early = session();
  const late = session({ session_id: "two", started_at: "2026-01-02" });
  const office = layoutOffice([late, early]);
  const a = office.avatars.find(a => a.sessionId === "one")!;
  const b = office.avatars.find(a => a.sessionId === "two")!;
  expect([a.seat, b.seat]).toEqual([0, 1]);
  expect(a.look).not.toEqual(b.look);
  expect(a.look.shirt).not.toBe(b.look.shirt);
  expect(lookFor(a.identity, 0)).toEqual(a.look);
  expect(layoutOffice([early, late])).toEqual(office);
});

it("fits 25 desks across six sorted projects without overlaps", () => {
  const office = layoutOffice(Array.from({ length: 25 }, (_, i) => session({
    session_id: String(i), workspace: { cwd: `/repos/project-${i % 6}` },
  })));
  expect(office.avatars).toHaveLength(25);
  expect(new Set(office.avatars.map(a => `${a.deskTile.x},${a.deskTile.y}`)).size).toBe(25);
  for (const tile of [...office.avatars.map(a => a.deskTile), office.yourDesk, office.rack, office.pantry, office.door]) {
    expect(tile.x).toBeGreaterThanOrEqual(0);
    expect(tile.y).toBeGreaterThanOrEqual(0);
    expect(tile.x).toBeLessThan(office.width);
    expect(tile.y).toBeLessThan(office.height);
  }
  expect(office.clusters.map(c => c.project)).toEqual([...office.clusters.map(c => c.project)].sort());
});

it("overflows a project into additional eight-desk clusters", () => {
  const office = layoutOffice(Array.from({ length: 25 }, (_, i) => session({ session_id: String(i) })));
  expect(office.clusters.map(c => c.desks.length)).toEqual([8, 8, 8, 1]);
  expect(new Set(office.avatars.map(a => JSON.stringify(a.deskTile))).size).toBe(25);
});

it("handles missing metadata for live sessions", () => {
  const office = layoutOffice([session({ workspace: {}, host: null, agent: null })]);
  const avatar = office.avatars[0];
  expect(avatar.project).toBe("unknown");
  expect(avatar.name.length).toBeGreaterThan(0);
  expect(avatar.deskTile).toBeDefined();
  expect(avatar.look).toEqual(lookFor(avatar.identity, avatar.seat));
  expect(avatar.place).toBe("desk");
  expect(layoutOffice([]).avatars).toEqual([]);
});

it("ignores 50 retained ended sessions when allocating two live desks", () => {
  const ended = Array.from({ length: 50 }, (_, i) => session({ session_id: `ended-${i}`, status: "ended", workspace: { cwd: `/old/${i}` } }));
  const office = layoutOffice([...ended, session(), session({ session_id: "two" })]);
  expect(office.avatars).toHaveLength(2);
  expect(office.clusters.flatMap(c => c.desks)).toHaveLength(2);
  expect(layoutOffice(ended).avatars).toEqual([]);
  expect(layoutOffice(ended).clusters).toEqual([]);
});

it("assigns distinct bounded shared-place slots in stable start/id order", () => {
  const sessions = Array.from({ length: 9 }, (_, i) => session({ session_id: `pantry-${i}`, status: "done" })).concat(
    Array.from({ length: 3 }, (_, i) => session({ session_id: `waiting-${i}`, status: "waiting_input" })),
    Array.from({ length: 35 }, (_, i) => session({ session_id: `rack-${i}`, activity: { kind: "run", tool: "Bash" } })),
  );
  const office = layoutOffice(sessions);
  for (const place of ["pantry", "your_desk", "rack"]) {
    const avatars = office.avatars.filter(a => a.place === place);
    expect(new Set(avatars.map(a => JSON.stringify(a.targetTile))).size).toBe(avatars.length);
    for (const a of avatars) {
      expect(a.targetTile!.x).toBeGreaterThanOrEqual(0);
      expect(a.targetTile!.x).toBeLessThan(office.width);
      expect(a.targetTile!.y).toBeGreaterThanOrEqual(0);
      expect(a.targetTile!.y).toBeLessThan(office.height);
    }
  }
  const targets = office.avatars.map(a => JSON.stringify(a.targetTile));
  expect(new Set(targets).size).toBe(sessions.length);
  const furniture = new Set([...office.clusters.flatMap(c => c.desks), office.door, office.rack, office.pantry, office.yourDesk, { x: office.width - 2, y: 1 }].map(p => JSON.stringify(p)));
  for (const a of office.avatars) {
    const anchor = a.place === "pantry" ? office.pantry : a.place === "rack" ? office.rack : office.yourDesk;
    const count = office.avatars.filter(b => b.place === a.place).length;
    expect(a.targetTile!.x).toBeGreaterThanOrEqual(anchor.x);
    expect(a.targetTile!.x).toBeLessThan(anchor.x + 6);
    expect(a.targetTile!.y).toBeGreaterThan(anchor.y);
    expect(a.targetTile!.y).toBeLessThanOrEqual(anchor.y + Math.ceil(count / 6));
    expect(furniture.has(JSON.stringify(a.targetTile))).toBe(false);
  }
  expect(layoutOffice([...sessions].reverse())).toEqual(office);
});

it("groups OpenBot source and host sessions together while using friendly app labels", () => {
  const office = layoutOffice([session({ source: "openbot", workspace: { cwd: "/agents/id-1" }, host_label: "Orca" }), session({ session_id: "two", host: { app: "openbot", confidence: 1, via: [] }, workspace: { cwd: "/agents/id-2" } })]);
  expect(office.clusters.map(c => c.project)).toEqual(["OpenBot agents"]);
  expect(office.avatars.map(a => a.project)).toEqual(["OpenBot agents", "OpenBot agents"]);
  expect(office.avatars[0].app).toBe("Orca");
  expect(office.avatars[1].app).toBe("openbot");
});

it("reserves a leaver's desk and seat for 20 seconds before reflowing", () => {
  const now = Date.parse("2026-11-17T12:00:00Z");
  const a = session({ session_id: "a", started_at: "2026-01-01", workspace: { cwd: "/p" } });
  const b = session({ session_id: "b", started_at: "2026-01-02", workspace: { cwd: "/p" } });
  const original = layoutOffice([a, b], now);
  const ended = { ...a, status: "ended" as const, ended_at: new Date(now).toISOString() };
  const ghost = layoutOffice([ended, b], now + 19_999);
  expect(ghost.clusters).toEqual(original.clusters);
  expect(ghost.avatars.find(a => a.key === "b")!.deskTile).toEqual(original.avatars[1].deskTile);
  expect(ghost.avatars.find(a => a.key === "b")!.seat).toBe(1);
  expect(ghost.avatars[0]).toMatchObject({ place: "door", pose: "leave", deskTile: original.avatars[0].deskTile });
  const expired = layoutOffice([ended, b], now + 20_000);
  expect(expired.avatars).toHaveLength(1);
  expect(expired.avatars[0].deskTile).not.toEqual(original.avatars[1].deskTile);
  expect(expired.avatars[0].seat).toBe(0);
});

it("keeps a departed project's cluster until its last ghost expires", () => {
  const now = Date.parse("2026-11-17T12:00:00Z");
  const a = session({ workspace: { cwd: "/a" }, status: "ended", ended_at: new Date(now).toISOString() });
  const b = session({ session_id: "b", workspace: { cwd: "/p" } });
  expect(layoutOffice([a, b], now + 19_999).clusters.map(c => c.project)).toEqual(["a", "p"]);
  expect(layoutOffice([a, b], now + 20_000).clusters.map(c => c.project)).toEqual(["p"]);
});


it("places pending reports at your desk and accepted reports in the pantry", () => {
  expect(poseFor(session({ status: "reported", report_pending: true }))).toEqual({ place: "your_desk", pose: "report" });
  expect(poseFor(session({ status: "reported", report_pending: false }))).toEqual({ place: "pantry", pose: "coffee" });
  expect(poseFor(session({ status: "waiting_input", needs_you: false }))).toEqual({ place: "pantry", pose: "coffee" });
});

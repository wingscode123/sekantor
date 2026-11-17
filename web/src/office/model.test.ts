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
        expect(poseFor(session({ status, activity }))).toEqual({ place, pose });
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

it("keeps ended avatars for their walk and handles missing metadata", () => {
  const office = layoutOffice([session({ workspace: {}, host: null, agent: null, status: "ended" })]);
  const avatar = office.avatars[0];
  expect(avatar.project).toBe("unknown");
  expect(avatar.name.length).toBeGreaterThan(0);
  expect(avatar.deskTile).toBeDefined();
  expect(avatar.look).toEqual(lookFor(avatar.identity, avatar.seat));
  expect(avatar.place).toBe("door");
  expect(layoutOffice([]).avatars).toEqual([]);
});

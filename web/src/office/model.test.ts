import { describe, expect, it } from "vitest";
import type { Session, Status, Subagent } from "../types";
import { identityOf, juniorKey, layoutOffice, lookFor, normaliseKind, poseFor, route } from "./model";

const session = (overrides: Partial<Session> = {}): Session => ({
  session_id: "one", source: "claude_code", source_label: "Claude Code",
  status: "running", status_since: "2026-01-01", started_at: "2026-01-01",
  last_event_at: "2026-01-01", workspace: { cwd: "/repos/ronda" },
  host: { app: "orca", confidence: 1, via: [] }, capabilities: [], needs_you: false,
  ...overrides,
});

it("uses Orca projects for rooms and seats lead desks ahead of grouped worktrees", () => {
  const member = (id: string, worktree: string, role: "lead" | "junior", project = "SeKantor") =>
    session({ session_id: id, project: { name: worktree, kind: "web", signals: [] },
      team: { project, worktree, role, lead: role === "junior" ? "lead" : null, model: null } });
  const office = layoutOffice([
    { ...member("a", "web", "junior"), status: "reported", report_to: "lead" },
    member("b", "hub", "junior"), member("c", "web", "junior"), member("lead", "main", "lead"),
    member("other", "main", "lead", "Other"),
  ]);
  expect(office.rooms.map(r => r.project)).toEqual(["Other", "SeKantor"]);
  const room = office.rooms[1];
  expect(room.worktrees?.map(tree => tree.name)).toEqual(["hub", "web"]);
  const avatar = (id: string) => office.avatars.find(a => a.key === id)!;
  expect(avatar("lead").deskTile.x).toBe(room.sign.x);
  expect(avatar("lead").deskTile.y).toBeLessThan(avatar("b").deskTile.y);
  expect(avatar("b").deskTile.y).toBeLessThan(avatar("a").deskTile.y);
  expect(avatar("a").deskTile.y).toBe(avatar("c").deskTile.y);
  expect(avatar("a").teamReport).toMatchObject({ lead: "lead", meeting: { x: room.sign.x, y: avatar("lead").deskTile.y + 1 } });
  expect(avatar("a").targetTile).toEqual(avatar("a").deskTile);
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
  expect(office.rooms.map(room => room.project)).toEqual(Array.from({ length: 6 }, (_, i) => `project-${i}`));
  expect(office.lobby.x + office.lobby.w / 2).toBe(office.width / 2);
  expect(office.lobby.door.y).toBe(office.height - 1);
  for (const [i, room] of office.rooms.entries()) {
    expect(office.lobby.y).toBeGreaterThanOrEqual(room.y + room.h);
    for (const other of office.rooms.slice(i + 1)) {
      expect(room.x + room.w <= other.x || other.x + other.w <= room.x ||
        room.y + room.h <= other.y || other.y + other.h <= room.y).toBe(true);
    }
    for (const desk of room.desks) {
      expect(desk.x).toBeGreaterThan(room.x);
      expect(desk.x).toBeLessThan(room.x + room.w - 1);
      expect(desk.y).toBeGreaterThan(room.y);
      expect(desk.y).toBeLessThan(room.y + room.h - 1);
    }
  }
});

it("keeps a large project in a single expandable room", () => {
  const office = layoutOffice(Array.from({ length: 25 }, (_, i) => session({ session_id: String(i) })));
  expect(office.rooms.map(room => room.desks.length)).toEqual([25]);
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
    const anchor = a.place === "pantry" ? office.pantry : a.place === "rack" ? office.rack : { x: office.yourDesk.x - 2, y: office.yourDesk.y };
    const count = office.avatars.filter(b => b.place === a.place).length;
    expect(a.targetTile!.x).toBeGreaterThanOrEqual(anchor.x);
    expect(a.targetTile!.x).toBeLessThan(anchor.x + (a.place === "your_desk" ? 6 : Math.floor((office.rooms[0].w - 2) / 2)));
    expect(a.targetTile!.y).toBeGreaterThan(anchor.y);
    expect(a.targetTile!.y).toBeLessThanOrEqual(anchor.y + Math.ceil(count / (a.place === "your_desk" ? 6 : Math.floor((office.rooms[0].w - 2) / 2))));
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

it("uses detected projects and routes through room doors and the corridor without crossing walls", () => {
  const office = layoutOffice([
    session({ project: { name: "Studio", kind: "web", signals: ["react"] }, activity: { kind: "run", tool: "Bash" } }),
    session({ session_id: "two", project: { name: "Warehouse", kind: "data", signals: ["pandas"] }, status: "done" }),
    session({ session_id: "three", project: { name: "Studio", kind: "web", signals: [] }, status: "waiting_approval" }),
  ]);
  const [studio, warehouse] = office.rooms;
  expect(studio).toMatchObject({ project: "Studio", kind: "web" });
  expect(warehouse).toMatchObject({ project: "Warehouse", kind: "data" });
  expect(office.avatars.find(a => a.key === "one")?.targetTile).toEqual({ x: studio.rack.x, y: studio.rack.y + 1 });
  expect(office.avatars.find(a => a.key === "two")?.targetTile).toEqual({ x: warehouse.pantry.x, y: warehouse.pantry.y + 1 });
  const start = studio.desks[0];
  for (const [target, doors] of [
    [warehouse.desks[0], [studio.door, warehouse.door]],
    [office.lobby.door, [studio.door, { x: office.lobby.door.x, y: office.lobby.y }, office.lobby.door]],
  ] as const) {
    const path = route(office, start, target);
    expect(path.at(-1)).toEqual(target);
    expect(path).toEqual(expect.arrayContaining([...doors]));
    expect(path.some(p => p.y === office.lobby.corridorY)).toBe(true);
    for (const [i, point] of path.entries()) {
      const previous = i === 0 ? start : path[i - 1];
      expect(Math.abs(point.x - previous.x) + Math.abs(point.y - previous.y)).toBe(1);
      for (const { x, y, w, h } of [...office.rooms, office.lobby]) {
        const wall = point.x >= x && point.x < x + w && point.y >= y && point.y < y + h
          && (point.x === x || point.x === x + w - 1 || point.y === y || point.y === y + h - 1);
        if (wall) expect(doors).toContainEqual(point);
      }
    }
  }
});

it("normalises unknown project kind to other in model", () => {
  expect(normaliseKind("web")).toBe("web");
  expect(normaliseKind("unknown-kind")).toBe("other");
  expect(normaliseKind(undefined)).toBe("other");
  const office = layoutOffice([session({ project: { name: "Custom", kind: "invalid-kind" as any, signals: [] } })]);
  expect(office.rooms[0].kind).toBe("other");
});

const projects = (count: number) => Array.from({ length: count }, (_, i) =>
  session({ session_id: String(i), workspace: { cwd: `/project-${i}` } }));

it.each([1, 2, 3])("packs %i small rooms into one row and includes the entire lobby", count => {
  const office = layoutOffice(projects(count), undefined, 2);
  const first = office.rooms[0];
  const last = office.rooms.at(-1)!;
  expect(office.rooms).toHaveLength(count);
  expect(office.rooms.every(room => room.y === 0 && room.w < 14)).toBe(true);
  expect(last.x + last.w - first.x).toBe(count * first.w + (count - 1) * 2);
  expect(office.width).toBeLessThanOrEqual(Math.max(office.lobby.w, last.x + last.w - first.x + 1));
  expect(office.lobby.x).toBeGreaterThanOrEqual(0);
  expect(office.lobby.x + office.lobby.w).toBeLessThanOrEqual(office.width);
  expect(office.lobby.y + office.lobby.h).toBe(office.height);
  expect(office.lobby.door.y).toBe(office.height - 1);
});

it("balances longer rows and centres the shorter last row", () => {
  const office = layoutOffice(projects(5), undefined, 3);
  const firstRow = office.rooms.filter(room => room.y === 0);
  const lastRow = office.rooms.filter(room => room.y > 0);
  expect(firstRow).toHaveLength(3);
  expect(lastRow).toHaveLength(2);
  const midpoint = (lastRow[0].x + lastRow[1].x + lastRow[1].w) / 2;
  expect(Math.abs(midpoint - office.width / 2)).toBeLessThanOrEqual(0.5);
});

it("keeps the junior desk until delivery completes, even without an end timestamp", () => {
  const started = "2026-11-17T12:00:00Z";
  const junior: Subagent = {
    id: "junior", type: "Explore", status: "working", activity: { kind: "read", tool: "Read" },
    started_at: started, ended_at: null, summary: null,
  };
  const now = Date.parse(started);
  const working = layoutOffice([session({ subagents: [junior] })], now);
  const [parent, child] = working.avatars;
  expect(child.look).toEqual(parent.look);
  expect(child.pose).toBe("read");
  expect(child.deskTile).toEqual({ x: parent.deskTile.x + 3, y: parent.deskTile.y });
  expect(working.rooms[0].desks).toContainEqual(child.deskTile);

  const reported = session({ subagents: [{ ...junior, status: "reported", ended_at: null }] });
  const reporting = layoutOffice([reported], now);
  const [main, courier] = reporting.avatars;
  expect(reporting.rooms[0].desks).toEqual(working.rooms[0].desks);
  expect(reporting.rooms[0].w).toBe(working.rooms[0].w);
  expect(courier.junior!.meeting).toEqual({ x: main.deskTile.x, y: main.deskTile.y + 1 });
  expect(route(reporting, courier.deskTile, courier.junior!.meeting).at(-1)).toEqual(courier.junior!.meeting);
  expect(route(reporting, courier.junior!.meeting, courier.junior!.door).at(-1)).toEqual(reporting.rooms[0].door);
  const gone = layoutOffice([reported], now, 3, new Set([courier.key]));
  expect(gone.rooms[0].desks).toEqual([gone.avatars[0].deskTile]);
  expect(gone.rooms[0].w).toBeLessThan(reporting.rooms[0].w);

  const sibling: Subagent = { ...junior, id: "sibling", started_at: "2026-11-17T12:00:01Z" };
  const before = layoutOffice([session({ subagents: [junior, sibling] })], now);
  const both = session({ subagents: [sibling, ...reported.subagents!] });
  const after = layoutOffice([both], now, 3, new Set([courier.key]));
  const siblingKey = juniorKey(both.session_id, sibling.id);
  expect(after.avatars.find(a => a.key === siblingKey)?.deskTile).toEqual(before.avatars[2].deskTile);
  expect(after.rooms[0].desks).toEqual([before.avatars[0].deskTile, before.avatars[2].deskTile]);
});

it("routes smoothly from a fractional position without backtracking", () => {
  const office = layoutOffice([session({ project: { name: "Studio", kind: "web", signals: [] } })]);
  const start = office.rooms[0].desks[0];
  // Move horizontally towards desk + 2
  const target = { x: start.x + 2, y: start.y };
  // Fractional position between start and target
  const mid = { x: start.x + 0.5, y: start.y };
  const waypoints = route(office, mid, target);
  expect(waypoints[0].x).toBeGreaterThan(mid.x);
  expect(waypoints.at(-1)).toEqual(target);
});


it.each([1, 2, 3, 4, 5, 6, 7, 8])("connects %i rooms to the lobby through doors without crossing walls", count => {
  const base = projects(count);
  const sessions = [...base, ...Array.from({ length: 4 }, (_, i) =>
    session({ session_id: `extra-${i}`, workspace: base[0].workspace }))];
  for (const columns of [2, 3, 4]) {
    const office = layoutOffice(sessions, undefined, columns);
    for (const room of office.rooms) for (const desk of room.desks) {
      const path = route(office, desk, office.door);
      expect(path.at(-1)).toEqual(office.door);
      expect(path).toContainEqual(room.door);
      const allowed = [room.door, office.door, { x: office.door.x, y: office.lobby.y }];
      for (const [i, point] of path.entries()) {
        const prior = path[i - 1] ?? desk;
        expect(Math.abs(prior.x - point.x) + Math.abs(prior.y - point.y)).toBe(1);
        for (const { x, y, w, h } of [...office.rooms, office.lobby]) {
          const inside = point.x >= x && point.x < x + w && point.y >= y && point.y < y + h;
          if (inside && (point.x === x || point.x === x + w - 1 || point.y === y || point.y === y + h - 1)) {
            expect(allowed).toContainEqual(point);
          }
        }
      }
    }
  }
});

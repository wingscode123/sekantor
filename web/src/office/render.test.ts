// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { startRenderer } from "./render";
import { layoutOffice, type Office } from "./model";
import type { Session, Subagent } from "../types";
import { CHARACTER_HEIGHT, TILE, type Theme } from "./sprites";
const office: Office = { width: 20, height: 10, clusters: [], rooms: [], places: [], lobby: { x: 0, y: 0, w: 0, h: 0, door: { x: 1, y: 1 }, yourDesk: { x: 2, y: 2 }, corridorY: 0 }, yourDesk: { x: 2, y: 2 }, rack: { x: 3, y: 3 }, pantry: { x: 4, y: 4 }, door: { x: 1, y: 1 }, avatars: [] };
const theme: Theme = { palette: [], tile: vi.fn(), furniture: vi.fn(), character: vi.fn() };
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
function setup() {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  const canvas = document.createElement("canvas"); canvas.width = office.width * TILE; canvas.height = office.height * TILE;
  return canvas;
}
it("never schedules while hidden, and cancels and resumes on visibility", () => {
  const canvas = setup(); let hidden = true;
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
  const active = { ...office, avatars: [{ key: "a", sessionId: "a", identity: "a", seat: 0, look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk" as const, pose: "type" as const, deskTile: { x: 5, y: 5 }, name: "a", app: "a", project: "a" }] };
  const stop = startRenderer(canvas, () => active, theme); expect(vi.getTimerCount()).toBe(0);
  hidden = false; document.dispatchEvent(new Event("visibilitychange")); expect(vi.getTimerCount()).toBe(1);
  hidden = true; document.dispatchEvent(new Event("visibilitychange")); expect(vi.getTimerCount()).toBe(0);
  stop(); hidden = false; document.dispatchEvent(new Event("visibilitychange")); expect(vi.getTimerCount()).toBe(0);
});
it("has no timers without sessions and can be woken by officechange", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  let current = office;
  const added = vi.spyOn(canvas, "addEventListener"), removed = vi.spyOn(canvas, "removeEventListener");
  const stop = startRenderer(canvas, () => current, theme); expect(vi.getTimerCount()).toBe(0);
  current = { ...office, avatars: [{ key: "a", sessionId: "a", identity: "a", seat: 0,
    look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk", pose: "type",
    deskTile: { x: 5, y: 5 }, name: "a", app: "a", project: "a" }] };
  canvas.dispatchEvent(new Event("officechange")); expect(vi.getTimerCount()).toBe(1);
  const listener = added.mock.calls.find(call => call[0] === "officechange")![1];
  stop(); expect(removed).toHaveBeenCalledWith("officechange", listener);
  canvas.dispatchEvent(new Event("officechange")); expect(vi.getTimerCount()).toBe(0);
});

it("retains a removed session and its desk until walking to the door", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const avatar = { key: "agent", sessionId: "s", identity: "i", seat: 0, look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk" as const, pose: "type" as const, deskTile: { x: 5, y: 1 }, name: "a", app: "a", project: "a" };
  let current: Office = { ...office, avatars: [avatar] };
  const character = vi.fn(), furniture = vi.fn();
  const stop = startRenderer(canvas, () => current, { ...theme, character, furniture });
  furniture.mockClear();
  vi.advanceTimersByTime(1500);
  current = { ...office, width: office.width + 1, avatars: [] }; character.mockClear(); furniture.mockClear();
  vi.advanceTimersByTime(100);
  expect(character).toHaveBeenCalled();
  expect(furniture.mock.calls.some(call => call[0] === "desk" && call[2] === 5 * TILE)).toBe(true);
  furniture.mockClear();
  vi.advanceTimersByTime(2000); expect(vi.getTimerCount()).toBe(0);
  expect(furniture.mock.calls.some(call => call[0] === "desk")).toBe(false);
  character.mockClear(); vi.advanceTimersByTime(1000); expect(character).not.toHaveBeenCalled(); stop();
});

it("reuses the static layer across frames and equivalent office objects", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const tile = vi.fn(), furniture = vi.fn();
  let current = office;
  const stop = startRenderer(canvas, () => current, { ...theme, tile, furniture });
  expect(tile).toHaveBeenCalledTimes(office.width * office.height);
  tile.mockClear(); furniture.mockClear();
  current = { ...office, door: { ...office.door } };
  canvas.dispatchEvent(new Event("officechange"));
  expect(tile).not.toHaveBeenCalled();
  expect(furniture.mock.calls.every(call => call[0] === "rack")).toBe(true);
  current = { ...office, door: { x: 2, y: 1 } };
  canvas.dispatchEvent(new Event("officechange"));
  expect(tile).toHaveBeenCalledTimes(office.width * office.height); stop();
});

it("paints the corridor and themed rooms on the static layer and invalidates on a kind change", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const room = vi.fn(), lobby = vi.fn(), tile = vi.fn();
  let current: Office = {
    ...office,
    rooms: [{ project: "studio", kind: "web", x: 2, y: 0, w: 6, h: 5,
      door: { x: 4, y: 4 }, sign: { x: 4, y: 0 }, desks: [], rack: { x: 5, y: 1 }, pantry: { x: 6, y: 1 } }],
    lobby: { x: 6, y: 6, w: 8, h: 4, yourDesk: { x: 10, y: 7 }, door: { x: 10, y: 9 }, corridorY: 5 },
  };
  const stop = startRenderer(canvas, () => current, { ...theme, room, lobby, tile });
  expect(room).toHaveBeenCalledWith("web", expect.anything(), current.rooms[0]);
  expect(lobby).toHaveBeenCalledOnce();
  const corridor = tile.mock.calls.filter(([kind]) => kind === "corridor");
  expect(corridor).toHaveLength(3 * (current.lobby.corridorY + 1));
  expect(corridor).toContainEqual(["corridor", expect.anything(), 10 * TILE, 0]);
  expect(corridor).toContainEqual(["corridor", expect.anything(), 10 * TILE, 5 * TILE]);
  current = { ...current, rooms: [{ ...current.rooms[0] }] };
  canvas.dispatchEvent(new Event("officechange"));
  expect(room).toHaveBeenCalledOnce();
  current = { ...current, rooms: [{ ...current.rooms[0], kind: "data" }] };
  canvas.dispatchEvent(new Event("officechange"));
  expect(room).toHaveBeenLastCalledWith("data", expect.anything(), current.rooms[0]);
  stop();
});

it("publishes key-based native positions in paint order across office replacement", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const avatar = { key: "front", sessionId: "front", identity: "i", seat: 0, look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk" as const, pose: "type" as const, deskTile: { x: 5, y: 1 }, targetTile: { x: 5, y: 4 }, name: "a", app: "a", project: "a" };
  let current: Office = { ...office, avatars: [avatar, { ...avatar, key: "back", targetTile: { x: 5, y: 3 } }] };
  const onFrame = vi.fn();
  const stop = startRenderer(canvas, () => current, theme, onFrame);
  vi.advanceTimersByTime(2500);
  const positions = onFrame.mock.lastCall![0] as Map<string, { x: number; y: number }>;
  expect([...positions.keys()]).toEqual(["back", "front"]);
  expect(positions.get("front")).toEqual({ x: 5 * TILE, y: 5 * TILE - CHARACTER_HEIGHT });
  current = { ...current, avatars: current.avatars.map(a => ({ ...a, look: { ...a.look } })) };
  vi.advanceTimersByTime(100);
  expect([...onFrame.mock.lastCall![0]]).toEqual([...positions]);
  stop();
});

it("walks an avatar along route waypoints through doors, not in a straight line", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const room = {
    project: "p", kind: "web" as const, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  const lobby = {
    x: 7, y: 7, w: 17, h: 5, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 11 }, corridorY: 6,
  };
  const avatar = {
    key: "a", sessionId: "a", identity: "a", seat: 0,
    look: { body: 0, hair: 0, shirt: 0, accessory: 0 },
    place: "desk" as const, pose: "type" as const,
    deskTile: { x: 2, y: 2 }, targetTile: { x: 2, y: 2 },
    name: "a", app: "a", project: "p",
  };
  let current: Office = {
    width: 31, height: 12, clusters: [], rooms: [room], places: [],
    lobby, yourDesk: lobby.yourDesk, rack: room.rack, pantry: room.pantry,
    door: lobby.door, avatars: [avatar],
  };
  const visited: { x: number; y: number }[] = [];
  let record = false;
  const stop = startRenderer(canvas, () => current, { ...theme, room: vi.fn(), lobby: vi.fn() }, positions => {
    const p = positions.get("a");
    if (p && record) visited.push({ x: p.x / TILE, y: (p.y + CHARACTER_HEIGHT - TILE) / TILE });
  });
  vi.advanceTimersByTime(5000);
  record = true;
  current = { ...current, avatars: [{ ...avatar, targetTile: lobby.yourDesk }] };
  canvas.dispatchEvent(new Event("officechange"));
  for (let i = 0; i < 40; i++) vi.advanceTimersByTime(100);
  stop();
  const passedDoor = visited.some(p => Math.abs(p.x - room.door.x) < 0.5 && Math.abs(p.y - room.door.y) < 0.5);
  expect(passedDoor).toBe(true);
  const throughWall = visited.some(p => p.x < 13 && p.y > 5 && p.y < 6);
  expect(throughWall).toBe(false);
});

it("re-targets mid-route from a fractional position without a jump", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const room = {
    project: "p", kind: "web" as const, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  const lobby = {
    x: 7, y: 7, w: 17, h: 5, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 11 }, corridorY: 6,
  };
  const avatar = {
    key: "a", sessionId: "a", identity: "a", seat: 0,
    look: { body: 0, hair: 0, shirt: 0, accessory: 0 },
    place: "desk" as const, pose: "work" as const,
    deskTile: { x: 2, y: 2 }, targetTile: { x: 2, y: 2 },
    name: "a", app: "a", project: "p",
  };
  let current: Office = {
    width: 31, height: 12, clusters: [], rooms: [room], places: [],
    lobby, yourDesk: lobby.yourDesk, rack: room.rack, pantry: room.pantry,
    door: lobby.door, avatars: [avatar],
  };
  let lastPos: { x: number; y: number } | undefined;
  const stop = startRenderer(canvas, () => current, { ...theme, room: vi.fn(), lobby: vi.fn() }, positions => {
    const p = positions.get("a");
    if (p) lastPos = { x: p.x / TILE, y: (p.y + CHARACTER_HEIGHT - TILE) / TILE };
  });
  vi.advanceTimersByTime(8000);
  expect(lastPos).toEqual({ x: 2, y: 2 });
  current = { ...current, avatars: [{ ...avatar, targetTile: { x: 10, y: 2 } }] };
  canvas.dispatchEvent(new Event("officechange"));
  vi.advanceTimersByTime(200);
  const midPos = { ...lastPos! };
  expect(midPos.x).toBeGreaterThan(2);
  expect(midPos.x).toBeLessThan(10);
  current = { ...current, avatars: [{ ...avatar, targetTile: { x: 7, y: 4 } }] };
  canvas.dispatchEvent(new Event("officechange"));
  vi.advanceTimersByTime(100);
  expect(Math.abs(lastPos!.x - midPos.x)).toBeLessThan(1.0);
  expect(Math.abs(lastPos!.y - midPos.y)).toBeLessThan(1.0);
  stop();
});

it("translates a walking avatar by its room's offset on reflow instead of snapping to the target", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const room1 = {
    project: "p", kind: "web" as const, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  const lobby1 = {
    x: 7, y: 7, w: 17, h: 5, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 11 }, corridorY: 6,
  };
  const avatar = {
    key: "a", sessionId: "a", identity: "a", seat: 0,
    look: { body: 0, hair: 0, shirt: 0, accessory: 0 },
    place: "desk" as const, pose: "work" as const,
    deskTile: { x: 2, y: 2 }, targetTile: { x: 2, y: 2 },
    name: "a", app: "a", project: "p",
  };
  let current: Office = {
    width: 31, height: 12, clusters: [], rooms: [room1], places: [],
    lobby: lobby1, yourDesk: lobby1.yourDesk, rack: room1.rack, pantry: room1.pantry,
    door: lobby1.door, avatars: [avatar],
  };
  let lastPos: { x: number; y: number } | undefined;
  const stop = startRenderer(canvas, () => current, { ...theme, room: vi.fn(), lobby: vi.fn() }, positions => {
    const p = positions.get("a");
    if (p) lastPos = { x: p.x / TILE, y: (p.y + CHARACTER_HEIGHT - TILE) / TILE };
  });
  vi.advanceTimersByTime(8000);
  expect(lastPos).toEqual({ x: 2, y: 2 });
  current = { ...current, avatars: [{ ...avatar, targetTile: { x: 10, y: 2 } }] };
  canvas.dispatchEvent(new Event("officechange"));
  vi.advanceTimersByTime(400);
  const walking = { ...lastPos! };
  expect(walking.x).toBeGreaterThan(2);
  expect(walking.x).toBeLessThan(10);
  const room2 = { ...room1, y: 4, door: { x: 13, y: 8 }, desks: [{ x: 2, y: 6 }], rack: { x: 1, y: 8 }, pantry: { x: 7, y: 8 } };
  const lobby2 = { ...lobby1, y: 11, corridorY: 10, yourDesk: { x: 15, y: 13 }, door: { x: 15, y: 15 } };
  current = {
    ...current, height: 16, rooms: [room2], lobby: lobby2,
    avatars: [{ ...avatar, deskTile: { x: 2, y: 6 }, targetTile: { x: 10, y: 6 } }],
  };
  canvas.dispatchEvent(new Event("officechange"));
  vi.advanceTimersByTime(90);
  expect(lastPos!.y).toBeCloseTo(walking.y + 4, 5);
  expect(Math.abs(lastPos!.x - walking.x)).toBeLessThan(1);
  stop();
});

it("moves a departing avatar's old desk with its room instead of leaving it in the walls", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const furniture = vi.fn();
  const room1 = {
    project: "p", kind: "web" as const, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  const lobby1 = { x: 7, y: 7, w: 17, h: 5, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 11 }, corridorY: 6 };
  const avatar = {
    key: "a", sessionId: "a", identity: "a", seat: 0, look: { body: 0, hair: 0, shirt: 0, accessory: 0 },
    place: "desk" as const, pose: "work" as const, deskTile: { x: 2, y: 2 }, targetTile: { x: 2, y: 2 }, name: "a", app: "a", project: "p",
  };
  let current: Office = {
    width: 31, height: 12, clusters: [], rooms: [room1], places: [], lobby: lobby1,
    yourDesk: lobby1.yourDesk, rack: room1.rack, pantry: room1.pantry, door: lobby1.door, avatars: [avatar],
  };
  const stop = startRenderer(canvas, () => current, { ...theme, furniture, room: vi.fn(), lobby: vi.fn() });
  vi.advanceTimersByTime(1000);
  const room2 = { ...room1, y: 4, door: { x: 13, y: 8 }, desks: [], rack: { x: 1, y: 8 }, pantry: { x: 7, y: 8 } };
  const lobby2 = { ...lobby1, y: 11, corridorY: 10, yourDesk: { x: 15, y: 13 }, door: { x: 15, y: 15 } };
  furniture.mockClear();
  current = { ...current, height: 16, rooms: [room2], lobby: lobby2, avatars: [], rack: room2.rack, pantry: room2.pantry,
    yourDesk: lobby2.yourDesk, door: lobby2.door };
  canvas.dispatchEvent(new Event("officechange"));
  vi.advanceTimersByTime(100);
  const desks = furniture.mock.calls.filter(c => c[0] === "desk").map(c => [c[2] / TILE, c[3] / TILE]);
  expect(desks).toContainEqual([2, 6]);
  expect(desks).not.toContainEqual([2, 2]);
  stop();
});

it("does not paint walkable-looking floor outside rooms/corridor/lobby", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const tile = vi.fn();
  const room = {
    project: "p", kind: "web" as const, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  const lobby = {
    x: 7, y: 7, w: 17, h: 5, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 11 }, corridorY: 6,
  };
  const current: Office = {
    width: 48, height: 12, clusters: [], rooms: [room], places: [],
    lobby, yourDesk: lobby.yourDesk, rack: room.rack, pantry: room.pantry,
    door: lobby.door, avatars: [],
  };
  const stop = startRenderer(canvas, () => current, { ...theme, tile, room: vi.fn(), lobby: vi.fn() });
  const outsideFloor = tile.mock.calls.some(([kind, , px, py]) => kind === "floor" && px === 35 * TILE && py === 2 * TILE);
  expect(outsideFloor).toBe(false);
  stop();
});



it("animates the junior delivering a paper, pausing while the main receives it, and leaving through the room door", () => {
  const canvas = setup();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const started = "2026-11-17T12:00:00Z";
  const junior: Subagent = { id: "j", type: "Explore", status: "working", activity: { tool: "Read", kind: "read" },
    started_at: started, ended_at: null, summary: null };
  const parent: Session = { session_id: "main", source: "claude_code", source_label: "Claude Code",
    status: "running", status_since: started, started_at: started, last_event_at: started,
    workspace: {}, capabilities: [], needs_you: false, subagents: [junior] };
  const now = Date.parse(started);
  let current = layoutOffice([parent], now);
  const character = vi.fn<Theme["character"]>();
  const departed = vi.fn();
  const stop = startRenderer(canvas, () => current, { ...theme, character }, undefined, departed);
  vi.advanceTimersByTime(5000);
  expect(character.mock.calls.some(([, pose, , , , , junior]) => pose === "read" && junior === true)).toBe(true);

  character.mockClear();
  current = layoutOffice([{ ...parent, subagents: [{ ...junior, status: "reported", ended_at: started }] }], now);
  vi.advanceTimersByTime(1000);
  expect(departed).not.toHaveBeenCalled();
  vi.advanceTimersByTime(4000);
  expect(departed).toHaveBeenCalledExactlyOnceWith([current.avatars[1].key]);
  const calls = character.mock.calls;
  const walk = calls.findIndex(([, pose]) => pose === "deliver");
  const receive = calls.findIndex(([, pose, , , , , scale]) => pose === "receive" && scale === undefined);
  const leave = calls.findIndex(([, pose]) => pose === "leave");
  expect(walk).toBeGreaterThanOrEqual(0);
  expect(receive).toBeGreaterThan(walk);
  expect(leave).toBeGreaterThan(receive);
  const waiting = calls.slice(walk, leave).filter(([, pose]) => pose === "report");
  expect(waiting.length).toBeGreaterThanOrEqual(8);
  const meeting = current.avatars[1].junior!.meeting;
  expect(waiting.every(([, , , , x, y]) => x === meeting.x * TILE &&
    y === (meeting.y + 1) * TILE - CHARACTER_HEIGHT)).toBe(true);
  const [, , , , lastX, lastY] = calls.filter(([, pose]) => pose === "leave").at(-1)!;
  const door = current.rooms[0].door;
  expect(lastX).toBe(door.x * TILE);
  expect(lastY).toBeLessThan((door.y + 1) * TILE - CHARACTER_HEIGHT);
  expect(lastY).toBeGreaterThan(door.y * TILE - CHARACTER_HEIGHT);
  expect(calls.at(-1)?.[6]).toBeUndefined();
  stop();
});

it("does not replay a report that was already complete in the first snapshot", () => {
  const canvas = setup();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const parent = { ...office, avatars: [{
    key: "completed", sessionId: "s", identity: "s", seat: 0,
    look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk", pose: "deliver",
    deskTile: { x: 5, y: 5 }, name: "Explore", app: "claude", project: "project",
    junior: { status: "reported", meeting: { x: 6, y: 5 }, door: office.door },
  }] } satisfies Office;
  const character = vi.fn();
  const departed = vi.fn();
  const stop = startRenderer(canvas, () => parent, { ...theme, character }, undefined, departed);
  vi.advanceTimersByTime(3000);
  expect(character).not.toHaveBeenCalled();
  expect(departed).toHaveBeenCalledExactlyOnceWith(["completed"]);
  stop();
});

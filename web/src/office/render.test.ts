// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { startRenderer } from "./render";
import type { Office } from "./model";
import type { Theme } from "./sprites";
const office: Office = { width: 20, height: 10, clusters: [], yourDesk: { x: 2, y: 2 }, rack: { x: 3, y: 3 }, pantry: { x: 4, y: 4 }, door: { x: 1, y: 1 }, avatars: [] };
const theme: Theme = { palette: [], tile: vi.fn(), furniture: vi.fn(), character: vi.fn() };
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
function setup() {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  const canvas = document.createElement("canvas"); canvas.width = 640; canvas.height = 320;
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
  vi.advanceTimersByTime(1500);
  current = { ...office, avatars: [] }; character.mockClear();
  vi.advanceTimersByTime(100);
  expect(character).toHaveBeenCalled();
  expect(furniture.mock.calls.some(call => call[0] === "desk" && call[2] === 80)).toBe(true);
  vi.advanceTimersByTime(2000); expect(vi.getTimerCount()).toBe(0);
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

it("publishes key-based native positions in paint order across office replacement", () => {
  const canvas = setup(); vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const avatar = { key: "front", sessionId: "front", identity: "i", seat: 0, look: { body: 0, hair: 0, shirt: 0, accessory: 0 }, place: "desk" as const, pose: "type" as const, deskTile: { x: 5, y: 4 }, name: "a", app: "a", project: "a" };
  let current: Office = { ...office, avatars: [avatar, { ...avatar, key: "back", deskTile: { x: 5, y: 3 } }] };
  const onFrame = vi.fn();
  const stop = startRenderer(canvas, () => current, theme, onFrame);
  vi.advanceTimersByTime(2500);
  const positions = onFrame.mock.lastCall![0] as Map<string, { x: number; y: number }>;
  expect([...positions.keys()]).toEqual(["back", "front"]);
  expect(positions.get("front")).toEqual({ x: 80, y: 56 });
  current = { ...current, avatars: current.avatars.map(a => ({ ...a, look: { ...a.look } })) };
  vi.advanceTimersByTime(100);
  expect([...onFrame.mock.lastCall![0]]).toEqual([...positions]);
  stop();
});

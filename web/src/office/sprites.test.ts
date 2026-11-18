// @vitest-environment jsdom
import { expect, it, vi } from "vitest";
import { CHARACTER_HEIGHT, defaultTheme, TILE, characterGrid, furnitureGrid, palette, tileGrid, type FurnitureKind } from "./sprites";
import type { Kind, Pose } from "./model";

const look = { body: 0, hair: 1, shirt: 2, accessory: 3 };
const fixtures: FurnitureKind[] = [
  "desk", "chair", "rack", "coffee", "plant", "door", "your_desk", "window", "lamp", "bookshelf", "rug", "sunlight",
];
const poses: Pose[] = ["type", "read", "run", "web", "work", "ask", "smoke", "coffee", "leave", "report"];

it("uses 32px tiles and 32x48 characters with only palette indexes", () => {
  expect(TILE).toBe(32);
  expect(CHARACTER_HEIGHT).toBe(48);
  const check = (rows: string[], height: number) => {
    expect(rows).toHaveLength(height);
    expect(rows.every(row => row.length === TILE)).toBe(true);
    const colors = new Set(rows.join(""));
    expect(colors.size).toBeGreaterThan(1);
    for (const color of colors) expect(palette[parseInt(color, 36)]).toBeDefined();
  };
  for (let f = 0; f < 4; f++) {
    check(tileGrid("floor", f), TILE);
    check(tileGrid("wall"), TILE);
    for (const kind of fixtures) check(furnitureGrid(kind, f), TILE);
    for (const pose of poses) check(characterGrid(look, pose, f), CHARACTER_HEIGHT);
  }
});

it("varies woodgrain and rack lights and animates every pose", () => {
  expect(tileGrid("floor", 0)).not.toEqual(tileGrid("floor", 1));
  expect(furnitureGrid("rack", 0)).not.toEqual(furnitureGrid("rack", 1));
  for (const pose of poses) {
    const frames = Array.from({ length: 4 }, (_, f) => characterGrid(look, pose, f).join(""));
    expect(new Set(frames).size, pose).toBeGreaterThanOrEqual(pose === "run" || pose === "leave" ? 4 : 2);
  }
});

it("gives the report pose a separate silhouette for its held sheet", () => {
  const report = characterGrid(look, "report", 0);
  for (const pose of poses.filter(pose => pose !== "report")) {
    expect(report, pose).not.toEqual(characterGrid(look, pose, 0));
  }
  expect(report[24][28]).not.toBe("0");
  expect(characterGrid(look, "work", 0)[24][28]).toBe("0");
});

it("draws rooms and lobby for all 8 kinds without throwing", () => {
  const kinds: Kind[] = ["web", "backend", "data", "mobile", "game", "infra", "docs", "other"];
  const ctx = {
    fillStyle: "",
    fillRect: vi.fn(),
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ fillStyle: "", fillRect: vi.fn(), drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  const room = {
    project: "test", kind: "web" as Kind, x: 0, y: 0, w: 14, h: 6,
    door: { x: 13, y: 4 }, sign: { x: 7, y: 0 }, desks: [{ x: 2, y: 2 }],
    rack: { x: 1, y: 4 }, pantry: { x: 7, y: 4 },
  };
  for (const kind of kinds) {
    expect(() => defaultTheme.room!(kind, ctx, { ...room, kind })).not.toThrow();
  }
  expect(ctx.drawImage).toHaveBeenCalled();
  const lobby = {
    x: 7, y: 7, w: 17, h: 6, yourDesk: { x: 15, y: 9 }, door: { x: 15, y: 12 }, corridorY: 6,
  };
  expect(() => defaultTheme.lobby!(ctx, lobby)).not.toThrow();
  vi.restoreAllMocks();
});


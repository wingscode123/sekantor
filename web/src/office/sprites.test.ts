// @vitest-environment jsdom
import { expect, it, vi } from "vitest";
import { CHARACTER_HEIGHT, defaultTheme, floorBackground, FLOOR_PERIOD, TILE, characterGrid, furnitureGrid, palette, tileGrid, type FurnitureKind } from "./sprites";
import type { Kind, Pose } from "./model";

const look = { body: 0, hair: 1, shirt: 2, accessory: 3 };
const fixtures: FurnitureKind[] = [
  "desk", "chair", "rack", "coffee", "plant", "door", "your_desk", "window", "lamp", "bookshelf", "rug", "sunlight",
];
const poses: Pose[] = ["type", "read", "run", "web", "work", "ask", "smoke", "coffee", "leave", "report"];

it("repeats the same four-grain floor tiles as the canvas", () => {
  const extent = FLOOR_PERIOD * TILE;
  const svg = decodeURIComponent(floorBackground.split(",")[1].slice(0, -2));
  const pixels = Array.from({ length: extent }, () => Array<string>(extent));
  for (const [, color, path] of svg.matchAll(/<path fill="([^"]+)" d="([^"]+)"\/>/g)) {
    for (const [, x, y, length] of path.matchAll(/M(\d+) (\d+)h(\d+)v1H\d+z/g)) {
      pixels[Number(y)].fill(color, Number(x), Number(x) + Number(length));
    }
  }
  for (let y = 0; y < FLOOR_PERIOD; y++) for (let x = 0; x < FLOOR_PERIOD; x++) {
    const canvasTile = tileGrid("floor", (x + 3 * y) % 4);
    const actual = pixels.slice(y * TILE, (y + 1) * TILE).map(row => row.slice(x * TILE, (x + 1) * TILE));
    expect(actual).toEqual(canvasTile.map(row => [...row].map(index => palette[parseInt(index, 36)])));
  }
});

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


it("adds a junior badge without resampling the character or changing its face", () => {
  const adult = characterGrid(look, "work", 0);
  const junior = characterGrid(look, "work", 0, true);
  expect(junior.map(row => row.length)).toEqual(Array(CHARACTER_HEIGHT).fill(TILE));
  expect(junior.slice(0, 23)).toEqual(adult.slice(0, 23));
  expect(junior.slice(23, 35)).not.toEqual(adult.slice(23, 35));
});

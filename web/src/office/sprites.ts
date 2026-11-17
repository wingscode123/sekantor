import type { Look, Pose } from "./model";
export type TileKind = "floor" | "wall";
export type FurnitureKind = "desk" | "chair" | "rack" | "coffee" | "plant" | "door" | "your_desk";
export interface Theme {
  palette: string[];
  tile(kind: TileKind, ctx: CanvasRenderingContext2D, x: number, y: number): void;
  character(look: Look, pose: Pose, frame: number, ctx: CanvasRenderingContext2D, x: number, y: number): void;
  furniture(kind: FurnitureKind, ctx: CanvasRenderingContext2D, x: number, y: number, frame?: number): void;
}
// Original geometric office art: chamfered furniture, narrow heads and asymmetric jackets.
export const palette = ["#00000000", "#e0ded1", "#c5cabb", "#35474b", "#66837c", "#ad795b", "#eed0a2", "#b97660", "#473c42", "#6599aa", "#ca9862", "#91bd98", "#f4e8c8", "#de786c", "#a299bc", "#ffffff"];
type Grid = string[];
function grid(w: number, h: number) {
  const rows = Array.from({ length: h }, () => Array<string>(w).fill("0"));
  return { rect(x: number, y: number, width: number, height: number, c: number) {
    for (let j = y; j < y + height; j++) for (let i = x; i < x + width; i++)
      if (rows[j]?.[i] !== undefined) rows[j][i] = c.toString(16);
  }, done: () => rows.map(r => r.join("")) };
}
export function tileGrid(kind: TileKind): Grid {
  const g = grid(16, 16); g.rect(0, 0, 16, 16, kind === "wall" ? 4 : 1);
  g.rect(0, 15, 16, 1, kind === "wall" ? 3 : 2);
  if (kind === "floor") { g.rect(15, 0, 1, 16, 2); g.rect(3, 4, 1, 1, 2); }
  else g.rect(0, 2, 16, 1, 2);
  return g.done();
}
export function furnitureGrid(kind: FurnitureKind, frame = 0): Grid {
  const g = grid(16, 16);
  if (kind === "desk" || kind === "your_desk") {
    g.rect(2, 4, 12, 10, 3); g.rect(1, 3, 14, 9, kind === "desk" ? 5 : 9);
    g.rect(5, 1, 7, 6, 3); g.rect(6, 2, 5, 3, 11); g.rect(5, 9, 6, 2, 12);
  } else if (kind === "chair") {
    g.rect(4, 2, 8, 9, 4); g.rect(3, 8, 10, 4, 3); g.rect(7, 12, 2, 3, 3);
  } else if (kind === "rack") {
    g.rect(2, 0, 12, 16, 3);
    for (let y = 2; y < 15; y += 4) { g.rect(4, y, 8, 2, 4); g.rect(10, y, 1, 1, frame % 2 ? 11 : 13); }
  } else if (kind === "coffee") {
    g.rect(2, 3, 12, 12, 5); g.rect(4, 1, 8, 10, 3); g.rect(6, 3, 4, 2, 9);
    g.rect(7, 7, 3, 5, 12); g.rect(10, 8, 2, 2, 12);
  } else if (kind === "plant") {
    g.rect(5, 10, 7, 5, 5); g.rect(8, 3, 1, 8, 4); g.rect(3, 3, 5, 3, 11);
    g.rect(9, 1, 5, 4, 4); g.rect(5, 7, 7, 2, 11);
  } else { g.rect(2, 0, 12, 16, 3); g.rect(4, 1, 9, 15, 5); g.rect(10, 8, 1, 2, 12); }
  return g.done();
}
const index = (n: number, choices: number[]) => choices[((n % choices.length) + choices.length) % choices.length];
export function characterGrid(look: Look, pose: Pose, frame: number): Grid {
  const g = grid(16, 24), f = ((frame % 4) + 4) % 4;
  const skin = index(look.body, [6, 7, 10]), hair = index(look.hair, [3, 5, 8]);
  const shirt = index(look.shirt, [9, 11, 13, 14]);
  const walk = pose === "run" || pose === "leave";
  g.rect(5, 5, 6, 6, skin); g.rect(4, 4, 7, 3, hair); g.rect(4, 7, 2, 2, hair);
  g.rect(9, 8, 1, 1, 3); g.rect(4, 12, 8, 7, shirt); g.rect(4, 12, 2, 7, 3);
  g.rect(6, 18, 2, walk && f % 2 ? 3 : 5, 3); g.rect(10, 18, 2, walk && !(f % 2) ? 3 : 5, 3);
  g.rect(7, 13, 1, 2, index(look.accessory, [12, 10, 14]));
  g.rect(3, 14 + f % 2, 2, 3, skin); g.rect(12, 14 + (f + 1) % 2, 2, 3, skin);
  if (pose === "type") { g.rect(6, 17, 7, 2, 12); g.rect(7 + f, 16, 2, 1, skin); }
  if (pose === "read") { g.rect(7, 13, 7, 5, 12); g.rect(9 + f % 3, 13, 1, 5, 2); }
  if (pose === "ask") { g.rect(10, f % 2, 5, 4, 12); g.rect(12, f % 2, 1, 2, 13); g.rect(12, 3 + f % 2, 1, 1, 13); }
  if (pose === "smoke") { g.rect(11 - f, 3 - f % 3, 3, 2, 2); g.rect(12, 11, 2, 3, skin); }
  if (pose === "coffee") { g.rect(11, 12 - f % 2, 3, 4, 12); g.rect(14, 13 - f % 2, 1, 2, 12); }
  if (pose === "web") { g.rect(10, 10 + f % 2, 4, 4, 3); g.rect(11, 11 + f % 2, 2, 2, 9); }
  if (pose === "work") g.rect(10, 15 + f % 2, 3, 2, skin);
  return g.done();
}
const cache = new Map<string, HTMLCanvasElement>();
function paint(key: string, build: () => Grid, ctx: CanvasRenderingContext2D, x: number, y: number) {
  let sprite = cache.get(key);
  if (!sprite) {
    const rows = build();
    sprite = document.createElement("canvas"); sprite.width = rows[0].length; sprite.height = rows.length;
    const off = sprite.getContext("2d"); if (!off) return;
    rows.forEach((row, j) => [...row].forEach((c, i) => {
      const n = parseInt(c, 16); if (n) { off.fillStyle = palette[n]; off.fillRect(i, j, 1, 1); }
    }));
    if (cache.size >= 512) cache.delete(cache.keys().next().value!);
    cache.set(key, sprite);
  }
  ctx.drawImage(sprite, Math.round(x), Math.round(y));
}
export const defaultTheme: Theme = {
  palette,
  tile: (kind, ctx, x, y) => paint(kind, () => tileGrid(kind), ctx, x, y),
  furniture: (kind, ctx, x, y, frame = 0) => paint(`${kind}:${frame % 2}`, () => furnitureGrid(kind, frame), ctx, x, y),
  character: (look, pose, frame, ctx, x, y) => paint(`${look.body},${look.hair},${look.shirt},${look.accessory}:${pose}:${frame % 4}`, () => characterGrid(look, pose, frame), ctx, x, y),
};

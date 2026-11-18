import type { Look, Pose } from "./model";

export const TILE = 32;
export const CHARACTER_HEIGHT = TILE * 3 / 2;
export type TileKind = "floor" | "wall";
export type FurnitureKind = "desk" | "chair" | "rack" | "coffee" | "plant" | "door" | "your_desk" | "window" | "lamp" | "bookshelf" | "rug" | "sunlight";
export interface Theme {
  palette: string[];
  tile(kind: TileKind, ctx: CanvasRenderingContext2D, x: number, y: number): void;
  character(look: Look, pose: Pose, frame: number, ctx: CanvasRenderingContext2D, x: number, y: number): void;
  furniture(kind: FurnitureKind, ctx: CanvasRenderingContext2D, x: number, y: number, frame?: number): void;
}

// Apricot plaster, oiled walnut and pools of gold, with petrol blue accents.
enum Ink {
  Clear, Shade, Shadow, Wood, WoodLight, WoodDark, Walnut, Rim,
  Plaster, Stripe, Brass, Gold, Cream, Linen, Clay, Oxide,
  Ink, Slate, Ash, Petrol, Teal, Glass, Daylight, Mint,
  Moss, Leaf, Fern, Plum, Lilac, Rose, Peach, Sand,
  Ochre, Umber, Cocoa, Sunlight,
}
export const palette = [
  "#00000000", "#43232322", "#43232355", "#bd8968", "#c99570", "#ae785a", "#70483d", "#e1af83",
  "#e5bb9f", "#d9a88c", "#a46b47", "#f7ce82", "#fff0ce", "#ded4bd", "#bd705d", "#8c5049",
  "#332b35", "#51444c", "#75636a", "#2d5558", "#51817c", "#87aead", "#cde2cf", "#c9e29a",
  "#445d48", "#6d8455", "#a1a269", "#765469", "#ad8497", "#d08871", "#efaa86", "#ffceaa",
  "#c58a59", "#865743", "#543938", "#fff0ce44",
];
type Grid = string[];
function grid(height = TILE) {
  const rows = Array.from({ length: height }, () => Array<string>(TILE).fill("0"));
  function rect(x: number, y: number, w: number, h: number, color: Ink) {
    const code = color.toString(36);
    for (let j = Math.max(0, y); j < Math.min(height, y + h); j++)
      rows[j].fill(code, Math.max(0, x), Math.max(0, Math.min(TILE, x + w)));
  }
  function oval(cx: number, cy: number, rx: number, ry: number, color: Ink) {
    for (let y = -ry; y <= ry; y++) {
      const halfWidth = Math.floor(rx * Math.sqrt(1 - (y / ry) ** 2));
      rect(cx - halfWidth, cy + y, 2 * halfWidth + 1, 1, color);
    }
  }
  function shadow(cx: number, cy: number, rx: number, ry: number) {
    oval(cx, cy, rx, ry, Ink.Shade);
    oval(cx, cy, rx - 3, ry - 2, Ink.Shadow);
  }
  return { rect, oval, shadow, done: () => rows.map(row => row.join("")) };
}

export function tileGrid(kind: TileKind, grain = 0): Grid {
  const { rect, done } = grid();
  if (kind === "wall") {
    rect(0, 0, TILE, TILE, Ink.Plaster);
    rect(0, 0, TILE, 2, Ink.Walnut);
    for (let x = 2; x < TILE; x += 8) {
      rect(x, 2, 1, 24, Ink.Stripe);
      for (let y = 6; y < 24; y += 8) rect(x + 2, y, 1, 2, Ink.Cream);
    }
    rect(0, 25, TILE, 1, Ink.Cream);
    rect(0, 26, TILE, 5, Ink.Walnut);
    rect(0, 27, TILE, 1, Ink.Brass);
    rect(0, 31, TILE, 1, Ink.Cocoa);
  } else {
    const planks = [Ink.Wood, Ink.WoodLight, Ink.Wood, Ink.WoodDark];
    for (let row = 0; row < 4; row++) {
      const top = row * 8, seam = (grain * 13 + row * 11 + 7) % 32;
      rect(0, top, TILE, 8, planks[(row + grain) % planks.length]);
      rect(0, top, TILE, 1, Ink.WoodDark);
      rect(0, top + 1, TILE, 1, Ink.Rim);
      rect(seam, top + 1, 1, 7, Ink.Brass);
      rect((seam + 7) % 25, top + 4, 7, 1, Ink.WoodLight);
      rect((seam + 19) % 27, top + 6, 5, 1, Ink.WoodDark);
    }
  }
  return done();
}

export function furnitureGrid(kind: FurnitureKind, frame = 0): Grid {
  const { rect, oval, shadow, done } = grid();
  switch (kind) {
    case "desk":
    case "your_desk": {
      const owner = kind === "your_desk";
      shadow(16, 24, 15, 6);
      rect(4, 15, 3, 11, Ink.Walnut);
      rect(25, 15, 3, 11, Ink.Walnut);
      rect(2, 10, 28, 12, Ink.Walnut);
      rect(1, 9, 30, 10, owner ? Ink.Petrol : Ink.WoodDark);
      rect(2, 9, 28, 1, owner ? Ink.Teal : Ink.Rim);
      rect(4, 14, 24, 4, owner ? Ink.Teal : Ink.WoodLight);
      rect(9, 2, 13, 10, Ink.Ink);
      rect(10, 3, 11, 7, Ink.Glass);
      rect(10, 3, 11, 2, Ink.Daylight);
      rect(12, 6, 5, 1, Ink.Petrol);
      rect(14, 8, 5, 1, Ink.Teal);
      rect(14, 12, 3, 2, Ink.Slate);
      rect(12, 14, 7, 1, Ink.Ink);
      rect(11, 16, 9, 2, Ink.Linen);
      rect(4, 12, 4, 4, Ink.Cream);
      rect(5, 12, 2, 1, Ink.Cocoa);
      rect(8, 13, 1, 2, Ink.Gold);
      rect(23, 13, 5, 4, Ink.Cream);
      rect(24, 14, 3, 1, Ink.Ash);
      break;
    }
    case "chair":
      shadow(16, 24, 11, 5);
      rect(10, 23, 12, 2, Ink.Ink);
      rect(15, 21, 2, 6, Ink.Slate);
      rect(8, 13, 16, 9, Ink.Ink);
      rect(10, 14, 12, 5, Ink.Teal);
      rect(10, 7, 12, 8, Ink.Petrol);
      rect(11, 7, 10, 2, Ink.Glass);
      rect(12, 10, 8, 3, Ink.Teal);
      rect(7, 15, 4, 2, Ink.Slate);
      rect(21, 15, 4, 2, Ink.Slate);
      break;
    case "rack":
      shadow(16, 27, 14, 5);
      rect(5, 3, 22, 25, Ink.Ink);
      rect(7, 2, 18, 3, Ink.Ash);
      rect(6, 5, 2, 21, Ink.Ash);
      for (let bay = 0; bay < 4; bay++) {
        const y = 6 + bay * 5;
        rect(9, y, 15, 4, Ink.Slate);
        for (let x = 10; x <= 16; x += 2) rect(x, y + 1, 1, 2, Ink.Ink);
        rect(20, y + 1, 1, 1, (frame + bay) % 2 ? Ink.Mint : Ink.Moss);
        rect(22, y + 1, 1, 1, (frame + bay) % 2 ? Ink.Teal : Ink.Gold);
      }
      break;
    case "coffee":
      shadow(16, 26, 15, 5);
      rect(3, 14, 26, 13, Ink.Walnut);
      rect(5, 19, 22, 6, Ink.WoodDark);
      rect(8, 20, 5, 1, Ink.Gold);
      rect(19, 20, 5, 1, Ink.Gold);
      rect(2, 14, 28, 4, Ink.WoodLight);
      rect(5, 4, 14, 13, Ink.Ink);
      rect(6, 3, 12, 5, Ink.Oxide);
      rect(6, 4, 11, 1, Ink.Rose);
      rect(8, 9, 8, 2, Ink.Ash);
      rect(11, 11, 2, 2, Ink.Brass);
      rect(10, 13, 5, 3, Ink.Cream);
      rect(20, 12, 8, 5, Ink.Brass);
      rect(21, 9, 3, 6, Ink.Linen);
      rect(25, 11, 3, 4, Ink.Cream);
      break;
    case "plant":
      shadow(17, 27, 11, 4);
      rect(11, 20, 10, 8, Ink.Oxide);
      rect(12, 21, 6, 6, Ink.Clay);
      rect(10, 19, 12, 3, Ink.Rose);
      rect(15, 6, 2, 14, Ink.Moss);
      oval(11, 9, 6, 3, Ink.Moss);
      oval(10, 8, 4, 2, Ink.Fern);
      oval(21, 7, 6, 4, Ink.Leaf);
      oval(22, 5, 4, 2, Ink.Fern);
      oval(12, 15, 6, 3, Ink.Leaf);
      oval(21, 13, 5, 3, Ink.Moss);
      oval(22, 12, 3, 2, Ink.Fern);
      break;
    case "door":
      shadow(16, 27, 15, 4);
      rect(3, 0, 26, 26, Ink.Cocoa);
      rect(4, 0, 23, 24, Ink.Rim);
      rect(7, 2, 18, 24, Ink.Walnut);
      rect(8, 3, 15, 22, Ink.Oxide);
      rect(10, 5, 11, 8, Ink.Walnut);
      rect(11, 6, 9, 6, Ink.Clay);
      rect(10, 16, 11, 7, Ink.Walnut);
      rect(11, 17, 9, 5, Ink.Clay);
      rect(20, 14, 3, 1, Ink.Gold);
      rect(3, 26, 26, 2, Ink.Brass);
      break;
    case "window":
      rect(2, 4, 28, 20, Ink.Walnut);
      rect(4, 5, 24, 16, Ink.Daylight);
      rect(4, 16, 24, 5, Ink.Glass);
      oval(11, 10, 3, 3, Ink.Cream);
      for (let x = 18; x < 27; x += 3) rect(x, 15 - x % 4, 2, 6, Ink.Teal);
      rect(15, 5, 2, 17, Ink.Cream);
      rect(4, 13, 24, 1, Ink.Cream);
      rect(1, 22, 30, 2, Ink.Rim);
      break;
    case "sunlight":
      for (let y = 0; y < 18; y++) {
        const offset = Math.floor(y / 3);
        rect(4 + offset, y, 10, 1, Ink.Sunlight);
        rect(17 + offset, y, 9, 1, Ink.Sunlight);
      }
      break;
    case "lamp":
      oval(16, 16, 12, 9, Ink.Gold);
      rect(14, 13, 4, 7, Ink.Brass);
      rect(10, 10, 12, 5, Ink.Cream);
      rect(9, 14, 14, 2, Ink.Walnut);
      break;
    case "bookshelf": {
      rect(3, 4, 26, 24, Ink.Walnut);
      rect(4, 4, 24, 2, Ink.Rim);
      const books = [Ink.Clay, Ink.Glass, Ink.Gold, Ink.Fern, Ink.Lilac];
      for (let shelf = 0; shelf < 2; shelf++) {
        const y = 15 + shelf * 10;
        rect(6, y - 8, 20, 8, Ink.Cocoa);
        for (let b = 0; b < books.length; b++) {
          const height = 5 + (b + shelf) % 4;
          rect(7 + b * 4, y - height, 3, height, books[(b + shelf) % books.length]);
          rect(7 + b * 4, y - 3, 3, 1, Ink.Linen);
        }
        rect(4, y, 24, 1, Ink.WoodLight);
      }
      break;
    }
    case "rug":
      shadow(16, 18, 15, 12);
      rect(1, 5, 30, 21, Ink.Oxide);
      rect(2, 6, 28, 19, Ink.Clay);
      rect(4, 8, 24, 15, Ink.Oxide);
      rect(5, 9, 22, 13, Ink.Clay);
      for (let i = 4; i < 30; i += 3) {
        rect(i, 4, 1, 2, Ink.Linen);
        rect(i, 26, 1, 2, Ink.Linen);
      }
      for (const x of [10, 16, 22]) for (let y = -3; y <= 3; y++)
        rect(x - 3 + Math.abs(y), 15 + y, 7 - 2 * Math.abs(y), 1, Ink.Rose);
      break;
  }
  return done();
}

const index = <T,>(n: number, choices: readonly T[]) => choices[((n % choices.length) + choices.length) % choices.length];
const skinTones = [[Ink.Sand, Ink.Peach], [Ink.Peach, Ink.Rose], [Ink.Ochre, Ink.Umber], [Ink.Umber, Ink.Cocoa]];
const hairTones = [[Ink.Ink, Ink.Slate], [Ink.Cocoa, Ink.Umber], [Ink.Walnut, Ink.Ochre], [Ink.Brass, Ink.Gold], [Ink.Slate, Ink.Ash], [Ink.Oxide, Ink.Clay], [Ink.Plum, Ink.Lilac], [Ink.Ash, Ink.Linen]];
const jackets = [[Ink.Teal, Ink.Petrol], [Ink.Clay, Ink.Oxide], [Ink.Leaf, Ink.Moss], [Ink.Lilac, Ink.Plum], [Ink.Gold, Ink.Brass], [Ink.Glass, Ink.Teal], [Ink.Ash, Ink.Slate], [Ink.Rose, Ink.Clay]];
const gait = [[-3, 2, -1], [-1, 0, 0], [2, -3, -1], [0, -1, 0]];
export function characterGrid(look: Look, pose: Pose, frame: number): Grid {
  const { rect, oval, shadow, done } = grid(CHARACTER_HEIGHT);
  const f = ((frame % 4) + 4) % 4, beat = f % 2;
  const [skin, skinShade] = index(look.body, skinTones);
  const [hair, hairLight] = index(look.hair, hairTones);
  const [jacket, jacketShade] = index(look.shirt, jackets);
  const accent = index(look.accessory, [Ink.Gold, Ink.Linen, Ink.Mint, Ink.Lilac]);
  const [leftLeg, rightLeg, bob] = pose === "run" || pose === "leave" ? gait[f] : [0, 0, 0];
  shadow(16, 44, 12, 3);
  rect(9, 33, 6, 9 + leftLeg, Ink.Slate);
  rect(17, 33, 6, 9 + rightLeg, Ink.Ink);
  rect(10, 35, 2, 6 + leftLeg, Ink.Ash);
  rect(18, 35, 2, 6 + rightLeg, Ink.Slate);
  rect(8, 41 + leftLeg, 7, 3, Ink.Ink);
  rect(17, 41 + rightLeg, 7, 3, Ink.Ink);
  rect(8, 43 + leftLeg, 6, 1, Ink.Ash);
  rect(18, 43 + rightLeg, 6, 1, Ink.Ash);

  rect(8, 24 + bob, 16, 12, jacketShade);
  rect(10, 23 + bob, 12, 11, jacket);
  rect(11, 24 + bob, 2, 9, jacketShade);
  rect(20, 26 + bob, 2, 2, accent);
  rect(13, 22 + bob, 6, 3, Ink.Linen);
  rect(14, 20 + bob, 4, 4, skinShade);

  rect(9, 10 + bob, 14, 11, skinShade);
  rect(10, 10 + bob, 12, 10, skin);
  rect(12, 20 + bob, 8, 2, skin);
  rect(8, 14 + bob, 2, 4, skinShade);
  rect(22, 14 + bob, 2, 4, skin);
  rect(10, 8 + bob, 12, 2, hair);
  rect(8, 10 + bob, 16, 4, hair);
  rect(8, 13 + bob, 3 + look.hair % 2, 3, hair);
  rect(11, 9 + bob, 7, 2, hairLight);
  rect(19, 12 + bob, 4, 2, hair);
  rect(13, 15 + bob, 1, 2, Ink.Ink);
  rect(19, 15 + bob, 1, 2, Ink.Ink);
  rect(16, 17 + bob, 2, 1, skinShade);

  rect(6, 25 + bob, 4, 6, jacketShade);
  rect(22, 25 + bob, 4, 6, jacket);
  rect(6, 30 + bob + beat, 4, 4, skinShade);
  rect(22, 31 + bob - beat, 4, 4, skin);
  switch (pose) {
    case "type":
      rect(9, 32, 16, 4, Ink.Ink);
      rect(10, 32, 14, 3, Ink.Linen);
      for (let x = 11; x < 24; x += 2) rect(x, 33, 1, 1, Ink.Slate);
      rect(10 + f, 30 + beat, 4, 2, skin);
      rect(19 - f, 31 - beat, 4, 2, skin);
      break;
    case "read":
      rect(12, 27, 14, 9, Ink.Walnut);
      rect(13, 26, 12, 8, Ink.Cream);
      rect(19 + beat, 26, 1, 8, Ink.Brass);
      rect(14, 28, 4, 1, Ink.Linen);
      rect(21, 29 - beat, 3, 1, Ink.Ash);
      rect(11, 31 + beat, 3, 3, skin);
      break;
    case "report":
      rect(18, 23 - beat, 11, 14, Ink.Ash);
      rect(19, 23 - beat, 10, 13, Ink.Cream);
      rect(20, 25 - beat, 7, 2, Ink.Teal);
      for (let y = 29; y <= 33; y += 2) rect(20, y - beat, 6, 1, Ink.Ash);
      rect(17, 31 - beat, 4, 3, skin);
      break;
    case "web":
      oval(23, 20 - beat, 5, 5, Ink.Ink);
      oval(23, 20 - beat, 3, 3, Ink.Glass);
      rect(21, 18 - beat, 3, 1, Ink.Daylight);
      rect(24, 24 - beat, 2, 6, Ink.Walnut);
      rect(23, 28 - beat, 4, 3, skin);
      break;
    case "coffee":
      rect(23, 26 - beat * 4, 6, 6, Ink.Cream);
      rect(24, 26 - beat * 4, 4, 1, Ink.Cocoa);
      rect(29, 27 - beat * 4, 2, 3, Ink.Linen);
      rect(25 + beat, 22 - beat * 4, 1, 2, Ink.Linen);
      rect(21, 29 - beat * 4, 4, 3, skin);
      break;
    case "ask":
      rect(19, 1 + beat, 11, 9, Ink.Oxide);
      rect(20, beat, 9, 9, Ink.Cream);
      rect(20, 9 + beat, 3, 2, Ink.Cream);
      rect(24, 2 + beat, 2, 3, Ink.Oxide);
      rect(24, 6 + beat, 2, 1, Ink.Oxide);
      break;
    case "smoke":
      oval(25 - f, 8 - f, 4, 3, Ink.Ash);
      oval(27 - f, 5 - f, 3, 2, Ink.Linen);
      rect(22, 19 + beat, 4, 4, skin);
      rect(24, 23, 3, 7, jacket);
      break;
    case "work":
      rect(19, 27 + beat, 6, 3, skin);
      rect(15, 30, 5, 4, accent);
      break;
  }
  return done();
}

const cache = new Map<string, HTMLCanvasElement>();
function paint(key: string, build: () => Grid, ctx: CanvasRenderingContext2D, x: number, y: number) {
  let sprite = cache.get(key);
  if (!sprite) {
    const rows = build();
    sprite = document.createElement("canvas");
    sprite.width = TILE;
    sprite.height = rows.length;
    const off = sprite.getContext("2d");
    if (!off) return;
    for (const [y, row] of rows.entries()) for (let x = 0; x < row.length; x++) {
      const color = parseInt(row[x], 36);
      if (color === Ink.Clear) continue;
      off.fillStyle = palette[color];
      off.fillRect(x, y, 1, 1);
    }
    if (cache.size >= 512) cache.delete(cache.keys().next().value!);
    cache.set(key, sprite);
  }
  ctx.drawImage(sprite, Math.round(x), Math.round(y));
}
export const defaultTheme: Theme = {
  palette,
  tile(kind, ctx, x, y) {
    const grain = kind === "floor" ? (Math.floor(x / TILE) + 3 * Math.floor(y / TILE)) % 4 : 0;
    paint(`${kind}:${grain}`, () => tileGrid(kind, grain), ctx, x, y);
  },
  furniture(kind, ctx, x, y, frame = 0) {
    const f = kind === "rack" ? Math.floor(frame / 6) % 2 : 0;
    paint(`${kind}:${f}`, () => furnitureGrid(kind, f), ctx, x, y);
  },
  character(look, pose, frame, ctx, x, y) {
    const f = pose === "run" || pose === "leave" || pose === "type" || pose === "smoke" ? frame % 4 : Math.floor(frame / 4) % 2;
    paint(`${look.body},${look.hair},${look.shirt},${look.accessory}:${pose}:${f}`, () => characterGrid(look, pose, f), ctx, x, y);
  },
};

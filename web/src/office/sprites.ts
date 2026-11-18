import { roomSignWidth, type Kind, type Lobby, type Look, type Pose, type Room } from "./model";

export const TILE = 32;
export const CHARACTER_HEIGHT = TILE * 3 / 2;
export type TileKind = "floor" | "wall" | "corridor";
export type FurnitureKind = "desk" | "chair" | "rack" | "coffee" | "plant" | "door" | "your_desk" | "window" | "lamp" | "bookshelf" | "rug" | "sunlight";
export interface Theme {
  palette: string[];
  tile(kind: TileKind, ctx: CanvasRenderingContext2D, x: number, y: number): void;
  character(look: Look, pose: Pose, frame: number, ctx: CanvasRenderingContext2D, x: number, y: number, junior?: boolean): void;
  furniture(kind: FurnitureKind, ctx: CanvasRenderingContext2D, x: number, y: number, frame?: number): void;
  room?(kind: Kind, ctx: CanvasRenderingContext2D, room: Room): void;
  lobby?(ctx: CanvasRenderingContext2D, lobby: Lobby): void;
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
  } else if (kind === "corridor") {
    rect(0, 0, TILE, TILE, Ink.Linen);
    for (let y = 0; y < TILE; y += 16) {
      const seam = (y + grain * 8) % TILE;
      rect(0, y, TILE, 15, Ink.Plaster);
      rect(seam, y, 1, 15, Ink.Stripe);
      rect(0, y + 1, TILE, 1, Ink.Rim);
      rect(0, y + 15, TILE, 1, Ink.Stripe);
    }
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

type Decor = "sketch" | "screen" | "cables" | "chart" | "flasks" | "phones" | "arcade" | "server";

function decorGrid(kind: Decor): Grid {
  const { rect, done } = grid();
  switch (kind) {
    case "sketch":
    case "chart":
      rect(2, 3, 28, 22, Ink.Walnut);
      rect(4, 5, 24, 17, Ink.Cream);
      rect(4, 22, 24, 2, Ink.Rim);
      if (kind === "sketch") {
        rect(6, 7, 10, 12, Ink.Glass);
        rect(7, 10, 8, 8, Ink.Daylight);
        rect(8, 12, 6, 2, Ink.Teal);
        rect(19, 8, 6, 5, Ink.Gold);
        rect(21, 14, 5, 5, Ink.Rose);
      } else {
        rect(6, 7, 1, 13, Ink.Ash);
        rect(6, 19, 20, 1, Ink.Ash);
        for (const [i, height] of [4, 8, 6, 11].entries())
          rect(9 + i * 4, 19 - height, 3, height, i % 2 ? Ink.Teal : Ink.Lilac);
      }
      break;
    case "screen":
      rect(1, 5, 30, 15, Ink.Ink);
      rect(3, 7, 26, 11, Ink.Petrol);
      rect(4, 8, 8, 9, Ink.Teal);
      rect(14, 8, 13, 5, Ink.Glass);
      rect(14, 15, 7, 1, Ink.Mint);
      rect(23, 15, 4, 1, Ink.Rose);
      rect(14, 20, 4, 3, Ink.Slate);
      rect(10, 23, 12, 2, Ink.Walnut);
      break;
    case "cables":
      rect(2, 4, 28, 6, Ink.Slate);
      for (const [i, color] of [Ink.Gold, Ink.Glass, Ink.Rose].entries()) {
        const x = 5 + i * 5, y = 13 + i * 4;
        rect(x, 7, 2, y - 5, color);
        rect(x, y, 20 - i * 4, 2, color);
        rect(x + 18 - i * 4, y, 2, 7, color);
        rect(x + 17 - i * 4, y + 6, 4, 3, Ink.Ink);
      }
      break;
    case "flasks":
      rect(2, 23, 28, 3, Ink.Walnut);
      for (const [i, color] of [Ink.Mint, Ink.Lilac, Ink.Glass].entries()) {
        const x = 5 + i * 8;
        rect(x + 2, 9 - i, 3, 8 + i, Ink.Daylight);
        rect(x + 1, 16, 5, 6, Ink.Daylight);
        rect(x, 19, 7, 4, color);
        rect(x + 1, 19, 1, 2, Ink.Cream);
      }
      break;
    case "phones":
      for (const y of [3, 15]) {
        rect(2, y + 10, 28, 2, Ink.Walnut);
        for (const [i, color] of [Ink.Glass, Ink.Lilac, Ink.Teal].entries()) {
          const x = 5 + i * 8;
          rect(x, y, 6, 10, Ink.Ink);
          rect(x + 1, y + 1, 4, 7, color);
          rect(x + 2, y + 8, 2, 1, Ink.Linen);
        }
      }
      break;
    case "arcade":
      rect(7, 2, 18, 26, Ink.Plum);
      rect(8, 3, 16, 4, Ink.Gold);
      rect(10, 9, 12, 9, Ink.Ink);
      rect(11, 10, 10, 6, Ink.Petrol);
      rect(13, 12, 2, 2, Ink.Mint);
      rect(18, 13, 2, 1, Ink.Lilac);
      rect(5, 18, 22, 4, Ink.Lilac);
      rect(10, 17, 2, 3, Ink.Rose);
      rect(19, 19, 4, 1, Ink.Gold);
      rect(11, 24, 10, 2, Ink.Slate);
      break;
    case "server":
      rect(2, 2, 28, 27, Ink.Ink);
      rect(3, 2, 26, 2, Ink.Ash);
      for (const x of [5, 17]) for (let y = 6; y < 26; y += 5) {
        rect(x, y, 10, 4, Ink.Slate);
        rect(x + 1, y + 1, 5, 2, Ink.Ink);
        rect(x + 7, y + 1, 2, 1, y % 2 ? Ink.Gold : Ink.Mint);
      }
      break;
  }
  return done();
}

const index = <T,>(n: number, choices: readonly T[]) => choices[((n % choices.length) + choices.length) % choices.length];
const skinTones = [[Ink.Sand, Ink.Peach], [Ink.Peach, Ink.Rose], [Ink.Ochre, Ink.Umber], [Ink.Umber, Ink.Cocoa]];
const hairTones = [[Ink.Ink, Ink.Slate], [Ink.Cocoa, Ink.Umber], [Ink.Walnut, Ink.Ochre], [Ink.Brass, Ink.Gold], [Ink.Slate, Ink.Ash], [Ink.Oxide, Ink.Clay], [Ink.Plum, Ink.Lilac], [Ink.Ash, Ink.Linen]];
const jackets = [[Ink.Teal, Ink.Petrol], [Ink.Clay, Ink.Oxide], [Ink.Leaf, Ink.Moss], [Ink.Lilac, Ink.Plum], [Ink.Gold, Ink.Brass], [Ink.Glass, Ink.Teal], [Ink.Ash, Ink.Slate], [Ink.Rose, Ink.Clay]];
const gait = [[-3, 2, -1], [-1, 0, 0], [2, -3, -1], [0, -1, 0]];
export function characterGrid(look: Look, pose: Pose, frame: number, junior = false): Grid {
  const { rect, oval, shadow, done } = grid(CHARACTER_HEIGHT);
  const f = ((frame % 4) + 4) % 4, beat = f % 2;
  const [skin, skinShade] = index(look.body, skinTones);
  const [hair, hairLight] = index(look.hair, hairTones);
  const [jacket, jacketShade] = index(look.shirt, jackets);
  const accent = index(look.accessory, [Ink.Gold, Ink.Linen, Ink.Mint, Ink.Lilac]);
  const [leftLeg, rightLeg, bob] = pose === "run" || pose === "leave" || pose === "deliver" ? gait[f] : [0, 0, 0];
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
  if (junior) {
    rect(12, 23 + bob, 2, 4, Ink.Gold);
    rect(18, 23 + bob, 2, 4, Ink.Gold);
    rect(14, 26 + bob, 4, 3, Ink.Gold);
    rect(13, 29 + bob, 6, 5, Ink.Ink);
    rect(14, 30 + bob, 4, 3, Ink.Cream);
  }
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
    case "receive":
      rect(19, 26, 9, 11, Ink.Cream);
      rect(20, 28, 6, 2, Ink.Teal);
      for (let y = 31; y <= 35; y += 2) rect(20, y, 6, 1, Ink.Ash);
      rect(17, 33, 4, 3, skin);
      rect(25, 32, 4, 3, skinShade);
      break;
    case "deliver":
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

type WallDecor = Decor | "rack" | "bookshelf" | "window" | "lamp";
const roomDecor: Record<Kind, readonly WallDecor[]> = {
  web: ["sketch", "screen"],
  backend: ["rack", "cables", "rack"],
  data: ["chart", "flasks"],
  mobile: ["phones", "phones", "screen"],
  game: ["arcade", "arcade", "arcade"],
  infra: ["server", "server", "server", "cables"],
  docs: ["bookshelf", "bookshelf", "bookshelf"],
  other: ["window", "lamp", "bookshelf"],
};
const roomTrim: Record<Kind, Ink> = {
  web: Ink.Teal, backend: Ink.Slate, data: Ink.Leaf, mobile: Ink.Glass,
  game: Ink.Plum, infra: Ink.Petrol, docs: Ink.Oxide, other: Ink.Brass,
};

function fill(ctx: CanvasRenderingContext2D, color: Ink, x: number, y: number, w: number, h: number) {
  ctx.fillStyle = palette[color];
  ctx.fillRect(x, y, w, h);
}

function doorway(ctx: CanvasRenderingContext2D, x: number, y: number, side: boolean) {
  fill(ctx, Ink.Cocoa, x, y, side ? 8 : TILE, side ? TILE : 8);
  fill(ctx, Ink.Rim, x + (side ? 0 : 4), y + (side ? 4 : 0), side ? 8 : 24, side ? 24 : 8);
  fill(ctx, Ink.Brass, x + (side ? 0 : 5), y + (side ? 5 : 7), side ? 8 : 22, side ? 22 : 1);
  for (const end of [0, TILE - 5]) {
    fill(ctx, Ink.Walnut, x + (side ? 0 : end), y + (side ? end : 0), side ? 8 : 5, side ? 5 : 14);
    fill(ctx, Ink.Rim, x + (side ? 1 : end + 1), y + (side ? end + 1 : 1), side ? 6 : 1, side ? 1 : 12);
  }
}

export const defaultTheme: Theme = {
  palette,
  tile(kind, ctx, x, y) {
    const grain = kind === "wall" ? 0 : (Math.floor(x / TILE) + 3 * Math.floor(y / TILE)) % 4;
    paint(`${kind}:${grain}`, () => tileGrid(kind, grain), ctx, x, y);
  },
  furniture(kind, ctx, x, y, frame = 0) {
    const f = kind === "rack" ? Math.floor(frame / 6) % 2 : 0;
    paint(`${kind}:${f}`, () => furnitureGrid(kind, f), ctx, x, y);
  },
  room(kind, ctx, room) {
    const right = room.x + room.w - 1, front = room.y + room.h - 1;
    const trim = roomTrim[kind] ?? roomTrim.other;
    for (let y = room.y; y <= front; y++) for (let x = room.x; x <= right; x++) {
      const px = x * TILE, py = y * TILE;
      const isSide = x === room.x || x === right;
      if (x === room.door.x && y === room.door.y) {
        doorway(ctx, px + (x === right ? TILE - 8 : 0), py, isSide);
      } else if (y === room.y) {
        this.tile("wall", ctx, px, py);
        fill(ctx, trim, px, py + 28, TILE, 3);
      } else {
        if (y === front) {
          fill(ctx, Ink.Cocoa, px, py, TILE, 8);
          fill(ctx, trim, px, py + 2, TILE, 4);
          fill(ctx, Ink.Rim, px, py + 2, TILE, 1);
        }
        if (!isSide) continue;
        const edge = px + (x === right ? TILE - 8 : 0);
        fill(ctx, Ink.Cocoa, edge, py, 8, TILE);
        fill(ctx, trim, edge + 2, py, 4, TILE);
        fill(ctx, Ink.Rim, edge + 2, py, 1, TILE);
      }
    }

    const signWidth = roomSignWidth(room);
    const signStart = room.sign.x - Math.floor(signWidth / 2);
    const slots = [];
    for (let x = room.x + 1; x < right; x++) {
      if (room.door.y === room.y && room.door.x === x) continue;
      if (room.sign.y === room.y && x >= signStart && x < signStart + signWidth) continue;
      slots.push(x);
    }
    const decor = roomDecor[kind] ?? roomDecor.other;
    for (const [i, piece] of decor.slice(0, slots.length).entries()) {
      const slot = Math.floor((i + 0.5) * slots.length / Math.min(decor.length, slots.length));
      const x = slots[slot] * TILE, y = room.y * TILE;
      if (piece === "rack" || piece === "bookshelf" || piece === "lamp" || piece === "window") {
        this.furniture(piece, ctx, x, y);
      } else {
        paint(`decor:${piece}`, () => decorGrid(piece), ctx, x, y);
      }
      if (kind === "game" && room.h > 2) {
        fill(ctx, Ink.Plum, x + 1, y + TILE, 30, 11);
        fill(ctx, Ink.Lilac, x + 3, y + TILE + 2, 26, 7);
        fill(ctx, Ink.Gold, x + 13, y + TILE + 4, 6, 3);
      }
    }
    const signX = signStart * TILE, signY = room.sign.y * TILE;
    const signPixels = signWidth * TILE;
    fill(ctx, Ink.Cocoa, signX, signY + 4, signPixels, 24);
    fill(ctx, Ink.Petrol, signX + 2, signY + 6, signPixels - 4, 20);
    fill(ctx, Ink.Gold, signX + 2, signY + 6, signPixels - 4, 1);
    fill(ctx, Ink.Teal, signX + 2, signY + 25, signPixels - 4, 1);
  },
  lobby(ctx, lobby) {
    const { x, y, w, h, door, yourDesk } = lobby;
    for (let row = y; row < y + h; row++) for (let col = x; col < x + w; col++) {
      this.tile("corridor", ctx, col * TILE, row * TILE);
    }
    for (const edge of [x * TILE, (x + w) * TILE - 8]) {
      fill(ctx, Ink.Walnut, edge, y * TILE, 8, h * TILE);
      fill(ctx, Ink.Teal, edge + 2, y * TILE, 4, h * TILE);
      fill(ctx, Ink.Rim, edge + 2, y * TILE, 1, h * TILE);
    }
    const top = y * TILE, bottom = door.y * TILE;
    for (let col = x; col < x + w; col++) {
      const px = col * TILE;
      if (col === door.x) {
        doorway(ctx, px, top, false);
        doorway(ctx, px, bottom, false);
        continue;
      }
      for (const edge of [top, bottom]) {
        fill(ctx, Ink.Walnut, px, edge, TILE, 8);
        fill(ctx, Ink.Teal, px, edge + 2, TILE, 4);
        fill(ctx, Ink.Rim, px, edge + 2, TILE, 1);
      }
    }
    if (w >= 5 && h >= 3) {
      this.furniture("plant", ctx, (x + 1) * TILE, (y + 1) * TILE);
      this.furniture("plant", ctx, (x + w - 2) * TILE, (y + 1) * TILE);
    }
    this.furniture("rug", ctx, yourDesk.x * TILE, yourDesk.y * TILE + TILE / 2);
    this.furniture("chair", ctx, yourDesk.x * TILE, yourDesk.y * TILE + TILE / 2);
    this.furniture("your_desk", ctx, yourDesk.x * TILE, yourDesk.y * TILE);
  },
  character(look, pose, frame, ctx, x, y, junior = false) {
    const f = pose === "run" || pose === "leave" || pose === "deliver" || pose === "type" || pose === "smoke" ? frame % 4 : Math.floor(frame / 4) % 2;
    paint(`${look.body},${look.hair},${look.shirt},${look.accessory}:${pose}:${f}:${junior}`, () => characterGrid(look, pose, f, junior), ctx, x, y);
  },
};

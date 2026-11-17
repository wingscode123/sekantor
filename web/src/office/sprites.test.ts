import { expect, it } from "vitest";
import { characterGrid, furnitureGrid, palette, tileGrid, type FurnitureKind } from "./sprites";
import type { Pose } from "./model";
it("all original sprite grids have fixed dimensions and palette indexes", () => {
  const check = (rows: string[], height: number) => {
    expect(rows).toHaveLength(height);
    for (const row of rows) { expect(row).toHaveLength(16); for (const c of row) expect(parseInt(c, 16)).toBeLessThan(palette.length); }
  };
  for (const kind of ["floor", "wall"] as const) check(tileGrid(kind), 16);
  for (const kind of ["desk", "chair", "rack", "coffee", "plant", "door", "your_desk"] as FurnitureKind[]) for (let f = 0; f < 4; f++) check(furnitureGrid(kind, f), 16);
  for (const pose of ["type", "read", "run", "web", "work", "ask", "smoke", "coffee", "leave"] as Pose[]) {
    const frames = Array.from({ length: 4 }, (_, f) => characterGrid({ body: 0, hair: 1, shirt: 2, accessory: 3 }, pose, f));
    frames.forEach(rows => check(rows, 24)); expect(new Set(frames.map(f => f.join(""))).size).toBeGreaterThanOrEqual(2);
  }
  expect(furnitureGrid("rack", 0)).not.toEqual(furnitureGrid("rack", 1));
});

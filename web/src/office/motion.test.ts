import { describe, expect, it } from "vitest";
import { Departures, step } from "./motion";
const map = (x: number, y: number) => new Map([["a", { x, y }]]);
describe("Manhattan movement", () => {
  it("moves at four tiles/s, x before y, and arrives exactly", () => {
    expect(step(map(0, 0), map(2, 2), 750).get("a")).toEqual({ x: 2, y: 1 });
    expect(step(map(0, 0), map(2, 2), 2000).get("a")).toEqual({ x: 2, y: 2 });
  });
  it("retargets running to waiting to running without teleporting", () => {
    const first = step(map(0, 0), map(5, 0), 100);
    const second = step(first, map(0, 5), 50);
    expect(second.get("a")).toEqual({ x: 0.2, y: 0 });
    expect(step(second, map(5, 0), 50).get("a")).toEqual({ x: 0.4, y: 0 });
  });
  it("retains a departure until it reaches the door", () => {
    const d = new Departures(); d.mark("a");
    d.arrive("a", { x: 1, y: 0 }, { x: 0, y: 0 }); expect(d.leaving("a")).toBe(true);
    d.arrive("a", { x: 0, y: 0 }, { x: 0, y: 0 }); expect(d.leaving("a")).toBe(false);
  });
});

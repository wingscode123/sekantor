import { describe, expect, it } from "vitest";
import { Departures, followRoute } from "./motion";

describe("route-following movement", () => {
  it("carries over leftover time across corners", () => {
    const waypoints = [{ x: 2, y: 0 }, { x: 2, y: 3 }];
    const pos = followRoute({ x: 0, y: 0 }, waypoints, 750, 4);
    expect(pos).toEqual({ x: 2, y: 1 });
    expect(waypoints).toEqual([{ x: 2, y: 3 }]);
  });

  it("arrives exactly at destination without overshoot", () => {
    const waypoints = [{ x: 2, y: 0 }, { x: 2, y: 3 }];
    const pos = followRoute({ x: 0, y: 0 }, waypoints, 2000, 4);
    expect(pos).toEqual({ x: 2, y: 3 });
    expect(waypoints).toEqual([]);
  });

  it("retains a departure until it reaches the door", () => {
    const d = new Departures(); d.mark("a");
    d.arrive("a", { x: 1, y: 0 }, { x: 0, y: 0 }); expect(d.leaving("a")).toBe(true);
    d.arrive("a", { x: 0, y: 0 }, { x: 0, y: 0 }); expect(d.leaving("a")).toBe(false);
  });
});


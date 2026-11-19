import { expect, it, vi } from "vitest";
import { drawWaitMark } from "./waitmark";

const fake = () => { const fills: string[] = []; const ctx = { fillRect: vi.fn(), set fillStyle(v: string) { fills.push(v); } } as unknown as CanvasRenderingContext2D; return { ctx, fills }; };

it("colours the frame by level", () => {
  for (const [ms, colour, level] of [[0, "#F7CE82", "calm"], [3 * 60_000, "#E5BB9F", "restless"], [11 * 60_000, "#EF8B72", "urgent"]] as const) {
    const { ctx, fills } = fake();
    expect(drawWaitMark(ctx, 0, 0, ms, 0, false)).toBe(level);
    expect(fills[0]).toBe(colour);
  }
});

it("pulses only the urgent frame, and not with reduced motion", () => {
  const colourAt = (ms: number, frame: number, reduced: boolean) => { const { ctx, fills } = fake(); drawWaitMark(ctx, 0, 0, ms, frame, reduced); return fills[0]; };
  expect(colourAt(11 * 60_000, 0, false)).toBe("#EF8B72");
  expect(colourAt(11 * 60_000, 6, false)).toBe("#F7CE82");
  expect(colourAt(11 * 60_000, 6, true)).toBe("#EF8B72");
  expect(colourAt(3 * 60_000, 6, false)).toBe("#E5BB9F");
});

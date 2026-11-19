import { LEVEL_COLOR, waitLevel, type WaitLevel } from "../attention";

export const reducedMotion = (): boolean =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * A frame around a waiting avatar's speech bubble (native pixels, sprite top-left at x, y). The colour
 * carries the level (Gold, Apricot, Coral); only the urgent frame pulses, and not with reduced motion.
 */
export function drawWaitMark(ctx: CanvasRenderingContext2D, x: number, y: number, ms: number, frame: number, reduced = reducedMotion()): WaitLevel {
  const level = waitLevel(ms);
  const pulse = level === "urgent" && !reduced && Math.floor(frame / 6) % 2 === 1;
  ctx.fillStyle = pulse ? LEVEL_COLOR.calm : LEVEL_COLOR[level];
  const thick = level === "urgent" ? 2 : 1;
  const left = x + 19 - thick, top = y - thick + 1, width = 12 + thick * 2 - 2, height = 11 + thick * 2 - 2;
  ctx.fillRect(left, top, width, thick);
  ctx.fillRect(left, top + height - thick, width, thick);
  ctx.fillRect(left, top, thick, height);
  ctx.fillRect(left + width - thick, top, thick, height);
  return level;
}

export interface Pt { x: number; y: number }
/** Pure Manhattan movement. Targets may change on every tick without resetting position. */
export function step(positions: Map<string, Pt>, targets: Map<string, Pt>, dtMs: number, speed = 4): Map<string, Pt> {
  const result = new Map<string, Pt>();
  for (const [key, target] of targets) {
    const current = positions.get(key) ?? target;
    let budget = Math.max(0, Number.isFinite(dtMs) ? dtMs : 0) * Math.max(0, speed) / 1000;
    const dx = target.x - current.x;
    const x = current.x + Math.sign(dx) * Math.min(Math.abs(dx), budget);
    budget = Math.max(0, budget - Math.abs(dx));
    const dy = target.y - current.y;
    result.set(key, { x, y: current.y + Math.sign(dy) * Math.min(Math.abs(dy), budget) });
  }
  return result;
}
/** Renderer-local departure bookkeeping: keep each departing avatar until arrival. */
export class Departures {
  private pending = new Set<string>();
  mark(key: string): void { this.pending.add(key); }
  cancel(key: string): void { this.pending.delete(key); }
  leaving(key: string): boolean { return this.pending.has(key); }
  arrive(key: string, position: Pt, door: Pt): void {
    if (position.x === door.x && position.y === door.y) this.pending.delete(key);
  }
}

/** Advance along an axis-aligned route, using leftover time at each corner. */
export function followRoute(position: Pt, waypoints: Pt[], dtMs: number, speed = 4): Pt {
  let budget = Math.max(0, dtMs) * speed / 1000;
  while (waypoints.length && budget > 0) {
    const next = waypoints[0];
    const dx = next.x - position.x, dy = next.y - position.y;
    const distance = Math.abs(dx) + Math.abs(dy);
    if (distance > budget) {
      const fraction = budget / distance;
      return { x: position.x + dx * fraction, y: position.y + dy * fraction };
    }
    position = next;
    budget -= distance;
    waypoints.shift();
  }
  return position;
}

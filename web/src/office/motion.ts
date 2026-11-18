export interface Pt { x: number; y: number }
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

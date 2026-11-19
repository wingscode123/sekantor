// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { attentionTitle, formatWait, queueSummary, waitingQueue, waitLevel, WAIT_RESTLESS_MS, WAIT_URGENT_MS, useAttentionSignals } from "./attention";
import type { Session } from "./types";

const NOW = Date.parse("2026-11-19T12:00:00Z");
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();
const session = (id: string, over: Partial<Session> = {}): Session => ({ session_id: id, source: "claude", source_label: id,
  status: "waiting_approval", status_since: ago(1), started_at: ago(60), last_event_at: ago(1), workspace: {}, capabilities: [], needs_you: true, ...over });

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.title = ""; document.head.innerHTML = ""; });

it("levels: calm under 2 min, restless to 10 min, urgent from 10 min", () => {
  expect([WAIT_RESTLESS_MS, WAIT_URGENT_MS]).toEqual([120_000, 600_000]);
  expect(waitLevel(0)).toBe("calm");
  expect(waitLevel(119_999)).toBe("calm");
  expect(waitLevel(120_000)).toBe("restless");
  expect(waitLevel(599_999)).toBe("restless");
  expect(waitLevel(600_000)).toBe("urgent");
  expect(waitLevel(-5)).toBe("calm");
});

it("formats waits as 3m and 1h 5m", () => {
  expect(formatWait(20_000)).toBe("<1m");
  expect(formatWait(3 * 60_000 + 5000)).toBe("3m");
  expect(formatWait(60 * 60_000)).toBe("1h");
  expect(formatWait(65 * 60_000)).toBe("1h 5m");
});

it("the queue holds sessions that wait for you, longest wait first", () => {
  const sessions = [
    session("short", { status_since: ago(2) }),
    session("long", { status_since: ago(30) }),
    session("running", { status: "running", needs_you: false }),
    session("lead", { status: "reported", needs_you: false, report_to: "lead" }),
    session("snoozed", { status_since: ago(50), snoozed_until: new Date(NOW + 3600_000).toISOString() }),
    session("mid", { status_since: ago(9) }),
    session("ended", { status: "ended", status_since: ago(90) }),
  ];
  expect(waitingQueue(sessions, NOW).map(s => s.session_id)).toEqual(["long", "mid", "short"]);
});

it("summary: count, longest waiter and pill text", () => {
  expect(queueSummary([], NOW)).toBeNull();
  const summary = queueSummary([session("a", { status_since: ago(7) }), session("b", { status_since: ago(3) })], NOW)!;
  expect(summary.count).toBe(2);
  expect(summary.longest.session_id).toBe("a");
  expect(summary.text).toBe("2 waiting · longest 7m");
});

it("title carries the count", () => {
  expect(attentionTitle(0)).toBe("SeKantor");
  expect(attentionTitle(3)).toBe("(3) SeKantor");
});

it("sets the title and a badged favicon while somebody waits, and restores both", async () => {
  document.head.innerHTML = '<link rel="icon" href="/icon.svg" type="image/svg+xml">';
  const ctx = { clearRect: vi.fn(), drawImage: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), fillStyle: "", strokeStyle: "", lineWidth: 0 };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,BADGE");
  vi.stubGlobal("Image", class { onload?: () => void; set src(_: string) { queueMicrotask(() => this.onload?.()); } });
  const { rerender } = renderHook(({ n }) => useAttentionSignals(n), { initialProps: { n: 0 } });
  expect(document.title).toBe("SeKantor");
  rerender({ n: 2 });
  expect(document.title).toBe("(2) SeKantor");
  await act(async () => { await Promise.resolve(); });
  {
    const link = document.querySelector<HTMLLinkElement>("link[rel~='icon']")!;
    expect(link.getAttribute("href")).toBe("data:image/png;base64,BADGE");
    expect(ctx.fill).toHaveBeenCalled();
    rerender({ n: 0 });
    expect(document.title).toBe("SeKantor");
    expect(link.getAttribute("href")).toBe("/icon.svg");
  }
});

it("survives a canvas without a 2d context", () => {
  document.head.innerHTML = '<link rel="icon" href="/icon.svg">';
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  expect(() => renderHook(() => useAttentionSignals(1))).not.toThrow();
  expect(document.title).toBe("(1) SeKantor");
});

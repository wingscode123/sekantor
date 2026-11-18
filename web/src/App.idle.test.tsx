// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import App from "./App";
import { MiniView } from "./office/MiniView";
import { TILE } from "./office/sprites";
import { useGhostNow, useNow, useSessions } from "./useSessions";
import type { Session } from "./types";
class Socket {
  static latest: Socket;
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  close = vi.fn();
  constructor() { Socket.latest = this; }
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("has no page timers or per-second officechange with only ended sessions", () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn(), fillRect: vi.fn() } as unknown as CanvasRenderingContext2D);
  render(<App />);
  const ended: Session = { session_id: "ended", source: "claude", source_label: "Claude", status: "ended", status_since: "2026-11-17", started_at: "2026-11-17", last_event_at: "2026-11-17", workspace: {}, capabilities: [], needs_you: false };
  act(() => {
    Socket.latest.onopen?.();
    Socket.latest.onmessage?.({ data: JSON.stringify({ type: "snapshot", sessions: [ended] }) });
  });
  expect(screen.getByRole("img", { name: /Office with 0 agents/ })).toBeTruthy();
  expect(vi.getTimerCount()).toBe(0);
  const dispatch = vi.spyOn(document.querySelector("canvas")!, "dispatchEvent");
  act(() => { vi.advanceTimersByTime(5000); });
  expect(dispatch).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});
it("memoizes the session array when connection state or the consumer rerenders", () => {
  vi.stubGlobal("WebSocket", Socket);
  const { result, rerender } = renderHook(() => useSessions());
  const sessions = result.current.sessions;
  act(() => { Socket.latest.onopen?.(); });
  expect(result.current.sessions).toBe(sessions);
  rerender();
  expect(result.current.sessions).toBe(sessions);
});

it("reads current time without a recurring clock when no session is snoozed", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
  const { result, rerender } = renderHook(() => useNow(1000, false));
  vi.setSystemTime(new Date("2026-11-17T13:00:00Z"));
  rerender();
  expect(result.current).toBe(Date.now());
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["office", "mini"])("uses one expiry timeout and no interval for %s ghost desks", mode => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
  vi.stubGlobal("WebSocket", Socket);
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn(), fillRect: vi.fn() } as unknown as CanvasRenderingContext2D);
  const interval = vi.spyOn(window, "setInterval");
  const View = mode === "office" ? App : MiniView;
  render(<View />);
  const ended: Session = { session_id: "ghost", source: "claude", source_label: "Claude", status: "ended", ended_at: new Date().toISOString(), status_since: new Date().toISOString(), started_at: "2026-11-17", last_event_at: "2026-11-17", workspace: {}, capabilities: [], needs_you: false };
  act(() => {
    Socket.latest.onopen?.();
    Socket.latest.onmessage?.({ data: JSON.stringify({ type: "snapshot", sessions: [ended] }) });
  });
  const canvas = document.querySelector("canvas")!;
  if (mode === "office") {
    expect(canvas.height).toBe(16 * TILE);
    expect(screen.queryByRole("button", { name: /ghost, claude/ })).toBeNull();
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("0 agents");
  }
  expect(vi.getTimerCount()).toBe(1);
  act(() => { vi.advanceTimersByTime(19_999); });
  expect(vi.getTimerCount()).toBe(1);
  act(() => { vi.advanceTimersByTime(1); });
  if (mode === "office") expect(canvas.height).toBe(8 * TILE);
  expect(vi.getTimerCount()).toBe(0);
  expect(interval).not.toHaveBeenCalled();
});
it("rearms only one timeout when several ghosts expire at different times", () => {
  vi.useFakeTimers();
  const start = Date.parse("2026-11-17T12:00:00Z");
  vi.setSystemTime(start);
  const base: Session = { session_id: "a", source: "claude", source_label: "Claude", status: "ended", ended_at: new Date(start - 5000).toISOString(), status_since: "2026-11-17", started_at: "2026-11-17", last_event_at: "2026-11-17", workspace: {}, capabilities: [], needs_you: false };
  const sessions = [base, { ...base, session_id: "b", ended_at: new Date(start).toISOString() }];
  const { result } = renderHook(() => useGhostNow(sessions));
  expect(vi.getTimerCount()).toBe(1);
  act(() => { vi.advanceTimersByTime(15_000); });
  expect(result.current).toBe(start + 15_000);
  expect(vi.getTimerCount()).toBe(1);
  act(() => { vi.advanceTimersByTime(5000); });
  expect(result.current).toBe(start + 20_000);
  expect(vi.getTimerCount()).toBe(0);
});

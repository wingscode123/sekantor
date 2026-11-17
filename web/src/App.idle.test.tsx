// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import App from "./App";
import { useNow, useSessions } from "./useSessions";
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

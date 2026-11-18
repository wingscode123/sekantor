// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MiniView } from "./MiniView";
import { layoutOffice } from "./model";
import type { Session } from "../types";
const mocks = vi.hoisted(() => ({ renderer: vi.fn<typeof import("./render").startRenderer>(() => vi.fn()), state: { sessions: [] as Session[], connection: "live", loaded: true } }));
vi.mock("./render", () => ({ startRenderer: mocks.renderer }));
vi.mock("../useSessions", () => ({ useSessions: () => mocks.state, useNow: () => Date.parse("2026-11-17T12:00:00Z"), useGhostNow: () => Date.parse("2026-11-17T12:00:00Z") }));
const session = (id: string, status: Session["status"] = "waiting_input"): Session => ({ session_id: id, source: "claude", source_label: id, status, status_since: "2026-11-17T11:00:00Z", started_at: "2026-11-17T10:00:00Z", last_event_at: "2026-11-17T11:00:00Z", workspace: { cwd: "/repo" }, capabilities: [], needs_you: status.startsWith("waiting_") });
afterEach(() => { cleanup(); mocks.state.sessions = []; mocks.state.connection = "live"; mocks.state.loaded = true; mocks.renderer.mockClear(); });
it("shows only waiting non-snoozed avatars, preserving their full-office looks", () => {
  mocks.state.sessions = [session("busy", "running"), session("input"), session("approval", "waiting_approval"), { ...session("muted"), snoozed_until: "2026-11-18T12:00:00Z" }, session("error", "error"), session("done", "done"), { ...session("report", "reported"), report_pending: true }, session("ended", "ended")];
  render(<MiniView />);
  const scene = mocks.renderer.mock.lastCall![1]();
  expect(scene.avatars.map(a => a.sessionId).sort()).toEqual(["approval", "input"]);
  const full = layoutOffice(mocks.state.sessions);
  for (const a of scene.avatars) expect(a.look).toEqual(full.avatars.find(f => f.key === a.key)!.look);
  expect(document.querySelector("canvas")?.getAttribute("aria-hidden")).toBe("true");
  expect(scene.door.x).toBe(1);
  expect(scene.door).not.toEqual(scene.yourDesk);
  expect(screen.getByText("1 busy \u00b7 2 needs you \u00b7 1 reports")).toBeTruthy();
});
it("shows the most recent waiting summary, ignoring newer muted or running summaries", () => {
  mocks.state.sessions = [{ ...session("old"), summary: "Old question" }, { ...session("new"), last_event_at: "2026-11-17T11:30:00Z", summary: "New question" }, { ...session("busy", "running"), last_event_at: "2026-11-17T11:45:00Z", summary: "Busy summary" }, { ...session("muted"), last_event_at: "2026-11-17T11:50:00Z", summary: "Muted question", snoozed_until: "2026-11-18T12:00:00Z" }];
  render(<MiniView />);
  expect(screen.getByText("New question")).toBeTruthy();
  expect(screen.queryByText("Old question")).toBeNull();
  expect(screen.queryByText("Muted question")).toBeNull();
});
it("click anywhere opens the full office at slash", () => {
  const navigate = vi.fn();
  render(<MiniView navigate={navigate} />);
  fireEvent.click(document.querySelector("canvas")!);
  expect(navigate).toHaveBeenCalledWith("/");
});
it.each(["{Enter}", " "])("native keyboard activation with %s opens the office", async key => {
  const navigate = vi.fn();
  const user = userEvent.setup();
  render(<MiniView navigate={navigate} />);
  await user.tab();
  await user.keyboard(key);
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
});
it("wakes for scene changes without restarting or waking for summary-only updates", () => {
  const view = render(<MiniView />);
  const canvas = document.querySelector("canvas")!;
  const wake = vi.fn();
  canvas.addEventListener("officechange", wake);
  const firstStop = mocks.renderer.mock.results[0].value;
  mocks.state.sessions = [session("input")];
  view.rerender(<MiniView />);
  expect(wake).toHaveBeenCalled();
  expect(firstStop).not.toHaveBeenCalled();
  expect(mocks.renderer.mock.lastCall![1]().avatars).toHaveLength(1);
  mocks.state.sessions = [{ ...session("input"), snoozed_until: "2026-11-18T12:00:00Z" }];
  view.rerender(<MiniView />);
  expect(mocks.renderer.mock.lastCall![1]().avatars).toHaveLength(0);
  wake.mockClear();
  mocks.state.sessions = mocks.state.sessions.map(s => ({ ...s, summary: "Only text changed" }));
  view.rerender(<MiniView />);
  expect(wake).not.toHaveBeenCalled();
  expect(mocks.renderer).toHaveBeenCalledTimes(1);
  const stop = mocks.renderer.mock.results.at(-1)!.value;
  view.unmount();
  expect(stop).toHaveBeenCalledOnce();
});
it("retains the canvas during disconnection and explains the stale state", () => {
  mocks.state.sessions = [session("input")];
  const view = render(<MiniView />);
  const canvas = document.querySelector("canvas")!;
  mocks.state.connection = "down";
  view.rerender(<MiniView />);
  expect(document.querySelector("canvas")!).toBe(canvas);
  expect(screen.getByRole("button").getAttribute("aria-label")).toContain("Hub disconnected");
});

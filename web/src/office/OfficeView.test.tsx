// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../App";
import { OfficeView } from "./OfficeView";

import type { Session } from "../types";
const mocks = vi.hoisted(() => ({ renderer: vi.fn<typeof import("./render").startRenderer>(() => vi.fn()), state: { sessions: [] as Session[], connection: "live", loaded: true } }));
vi.mock("./render", () => ({ startRenderer: mocks.renderer }));
vi.mock("../useSessions", () => ({ useSessions: () => mocks.state, useNow: () => Date.parse("2026-11-17T12:00:00Z"), useGhostNow: () => Date.parse("2026-11-17T12:00:00Z") }));
const session = (id = "one"): Session => ({ session_id: id, source: "claude", source_label: id, status: "running", status_since: "2026-11-17T11:00:00Z", started_at: "2026-11-17T10:00:00Z", last_event_at: "2026-11-17T11:00:00Z", workspace: { cwd: "/repo", branch: "main" }, capabilities: [], needs_you: false, open_label: "Open in Orca" });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); mocks.state.connection = "live"; mocks.state.sessions = []; mocks.state.loaded = true; mocks.renderer.mockClear(); });
describe("office page", () => {
  it("renders one plate per session", () => {
    render(<OfficeView sessions={[session(), session("two")]} />);
    expect(screen.getAllByTestId("name-plate")).toHaveLength(2);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("2 agents");
  });
  it("opens the card from a plate and calls the source app endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    render(<OfficeView sessions={[session()]} />);
    fireEvent.click(screen.getByTestId("name-plate"));
    expect(screen.getByRole("dialog").textContent).toContain("repo / main");
    fireEvent.click(screen.getByRole("button", { name: "Open in Orca" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/v1/sessions/one/open", expect.objectContaining({ method: "POST" })));
  });
  it("opens with native list button activation and closes with Escape", () => {
    render(<OfficeView sessions={[session()]} />);
    const item = screen.getByRole("button", { name: "one, claude, repo, Running" });
    fireEvent.click(item);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it.each(["down", "unauthorized"])("keeps the same canvas when %s", connection => {
    mocks.state.sessions = [session()];
    const view = render(<App />);
    const canvas = screen.getByRole("img", { name: /Office with/ });
    mocks.state.connection = connection;
    view.rerender(<App />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("img", { name: /Office with/ })).toBe(canvas);
    expect(mocks.renderer).toHaveBeenCalledTimes(1);
  });
  it("hits overlapping avatars top-most first after a new office object", () => {
    mocks.renderer.mockImplementationOnce((_canvas, _getOffice, _theme, onFrame) => {
      // Deliberately opposite session order: one is painted last, in front of two.
      onFrame!(new Map([["two", { x: 80, y: 40 }], ["one", { x: 80, y: 42 }]]));
      return vi.fn();
    });
    const view = render(<OfficeView sessions={[session(), session("two")]} />);
    // The next frame has not run; equivalent new avatars must retain valid hit areas.
    view.rerender(<OfficeView sessions={[{ ...session(), summary: "Updated" }, session("two")]} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 42, clientY: 23 });
    expect(screen.getByRole("dialog", { name: "one details" }).textContent).toContain("Updated");
    expect(mocks.renderer).toHaveBeenCalledTimes(1);
  });
  it("counts awake agents with UTF-8 separators and keeps snoozed avatars", () => {
    mocks.state.sessions = [session(), { ...session("waiting"), status: "waiting_input", needs_you: true }, { ...session("error"), status: "error" }, { ...session("muted"), status: "waiting_input", needs_you: true, snoozed_until: "2026-11-18T12:00:00Z" }];
    const view = render(<App />);
    expect(screen.getByText("1 busy \u00b7 1 needs you \u00b7 1 errors")).toBeTruthy();
    expect(document.title).toBe("(1) SeKantor");
    expect(screen.getAllByTestId("name-plate")).toHaveLength(4);
    mocks.state.sessions = mocks.state.sessions.map(s => s.needs_you ? { ...s, snoozed_until: "2026-11-18T12:00:00Z" } : s);
    view.rerender(<App />);
    expect(screen.getByText("1 busy \u00b7 0 needs you \u00b7 1 errors")).toBeTruthy();
    expect(document.title).toBe("SeKantor");
  });
  it("shows first-load and empty-office hints at the appropriate time", () => {
    mocks.state.loaded = false;
    const view = render(<App />);
    expect(screen.queryByText(/Your office is quiet/)).toBeNull();
    mocks.state.connection = "down";
    view.rerender(<App />);
    expect(screen.getByText("sekantor up")).toBeTruthy();
    mocks.state.loaded = true;
    mocks.state.connection = "live";
    view.rerender(<App />);
    expect(screen.getByText("sekantor install claude --project")).toBeTruthy();
  });
  it("omits ended plates and list items and removes live plates from tab order", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(960);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(512);
    render(<OfficeView sessions={[session(), { ...session("ended"), status: "ended" }]} />);
    const plates = screen.getAllByTestId("name-plate") as HTMLButtonElement[];
    expect(plates.find(p => p.textContent?.startsWith("one"))!.hidden).toBe(false);
    expect(plates).toHaveLength(1);
    expect(plates.every(p => p.tabIndex === -1)).toBe(true);
    expect(screen.queryByRole("button", { name: "ended, claude, repo, Ended" })).toBeNull();
  });
  it("wakes the renderer when an empty office gains a session", () => {
    const view = render(<OfficeView sessions={[]} />);
    const wake = vi.fn();
    screen.getByRole("img").addEventListener("officechange", wake);
    view.rerender(<OfficeView sessions={[session()]} />);
    expect(wake).toHaveBeenCalledOnce();
  });
  it("keeps plates visible at 1200px width with three cluster rows", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    const sessions = Array.from({ length: 25 }, (_, i) => ({ ...session(String(i)), workspace: { cwd: `/project-${i % 6}` } }));
    render(<OfficeView sessions={sessions} />);
    expect(screen.getAllByTestId("name-plate").every(p => !(p as HTMLButtonElement).hidden)).toBe(true);
  });
  it("excludes ended and snoozed agents from canvas counts but keeps snoozed live avatars", () => {
    mocks.state.sessions = [session(), { ...session("ended"), status: "ended" }, { ...session("muted"), snoozed_until: "2026-11-18T12:00:00Z" }, { ...session("waiting"), status: "waiting_input", needs_you: true }];
    render(<App />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("Office with 2 agents: 1 busy, 1 needs you, 0 errors");
    expect(screen.getAllByTestId("name-plate")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /ended, claude/ })).toBeNull();
  });
  it("does not wake the office for summary-only updates", () => {
    const view = render(<OfficeView sessions={[session()]} />);
    const wake = vi.fn();
    screen.getByRole("img").addEventListener("officechange", wake);
    view.rerender(<OfficeView sessions={[{ ...session(), summary: "Only text changed" }]} />);
    expect(wake).not.toHaveBeenCalled();
  });
});

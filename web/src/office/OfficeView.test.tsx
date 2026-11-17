// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../App";
import { OfficeView } from "./OfficeView";
import { defaultTheme } from "./sprites";
import type { Session } from "../types";
const mocks = vi.hoisted(() => ({ renderer: vi.fn<typeof import("./render").startRenderer>(() => vi.fn()), state: { sessions: [] as Session[], connection: "live", loaded: true } }));
vi.mock("./render", () => ({ startRenderer: mocks.renderer }));
vi.mock("../useSessions", () => ({ useSessions: () => mocks.state, useNow: () => Date.parse("2026-11-17T12:00:00Z") }));
const session = (id = "one"): Session => ({ session_id: id, source: "claude", source_label: id, status: "running", status_since: "2026-11-17T11:00:00Z", started_at: "2026-11-17T10:00:00Z", last_event_at: "2026-11-17T11:00:00Z", workspace: { cwd: "/repo", branch: "main" }, capabilities: [], needs_you: false, open_label: "Open in Orca" });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); mocks.state.connection = "live"; mocks.state.sessions = []; mocks.renderer.mockClear(); });
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
  it("opens with Enter from the accessible list and closes with Escape", () => {
    render(<OfficeView sessions={[session()]} />);
    const item = screen.getByRole("button", { name: "one, claude, repo, Running" });
    fireEvent.keyDown(item, { key: "Enter" });
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
  it("opens a moving avatar at its rendered position", () => {
    vi.spyOn(defaultTheme, "character").mockImplementation(() => {});
    mocks.renderer.mockImplementationOnce((_canvas, getOffice, theme) => {
      theme!.character(getOffice().avatars[0].look, "run", 0, {} as CanvasRenderingContext2D, 80, 40);
      return vi.fn();
    });
    render(<OfficeView sessions={[session()]} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 85, clientY: 45 });
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
  it("wakes the renderer when an empty office gains a session", () => {
    const view = render(<OfficeView sessions={[]} />);
    const wake = vi.fn();
    screen.getByRole("img").addEventListener("officechange", wake);
    view.rerender(<OfficeView sessions={[session()]} />);
    expect(wake).toHaveBeenCalledOnce();
  });
});


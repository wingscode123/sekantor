// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "../App";
import { OfficeView } from "./OfficeView";
import { layoutOffice } from "./model";
import { floorAttention, floorOf, modelBadge } from "./floors";

import type { Session } from "../types";
const mocks = vi.hoisted(() => ({ renderer: vi.fn<typeof import("./render").startRenderer>(() => vi.fn()), state: { sessions: [] as Session[], connection: "live", loaded: true } }));
vi.mock("./model", async importOriginal => { const m = await importOriginal<typeof import("./model")>(); return { ...m, layoutOffice: vi.fn(m.layoutOffice) }; });
vi.mock("./render", () => ({ startRenderer: mocks.renderer }));
vi.mock("../useSessions", () => ({ useSessions: () => mocks.state, useNow: () => Date.parse("2026-11-17T12:00:00Z"), useGhostNow: () => Date.parse("2026-11-17T12:00:00Z") }));
const session = (id = "one"): Session => ({ session_id: id, source: "claude", source_label: id, status: "running", status_since: "2026-11-17T11:00:00Z", started_at: "2026-11-17T10:00:00Z", last_event_at: "2026-11-17T11:00:00Z", workspace: { cwd: "/repo", branch: "main" }, capabilities: [], needs_you: false, open_label: "Open in Orca" });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); mocks.state.connection = "live"; mocks.state.sessions = []; mocks.state.loaded = true; mocks.renderer.mockClear(); });
describe("office page", () => {
  it("defaults to the first floor with attention, filters sessions, and remembers an explicit choice", () => {
    const openbot = { ...session("openbot"), source: "openbot", needs_you: true };
    const orca = { ...session("worker"), host: { app: "orca", confidence: 1, via: [] }, needs_you: true };
    localStorage.setItem("sekantor.floor", "openbot");
    mocks.state.sessions = [session("claude"), openbot, orca];
    const view = render(<App />);
    expect(screen.getByRole("button", { name: /2 Orca.*attention/, pressed: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: /3 OpenBot.*attention/, pressed: false })).toBeTruthy();
    expect(screen.getByTestId("name-plate").textContent).toContain("worker");
    fireEvent.click(screen.getByRole("button", { name: "1 Claude" }));
    expect(screen.getByTestId("name-plate").textContent).toContain("claude");
    view.unmount();
    mocks.state.sessions = [session("claude"), { ...orca, needs_you: false, report_pending: true }, { ...openbot, needs_you: false }];
    render(<App />);
    expect(screen.getByRole("button", { name: "1 Claude", pressed: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: /2 Orca.*attention/, pressed: false })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "3 OpenBot" }));
    expect(screen.getByText("OpenBot agents", { exact: true })).toBeTruthy();
  });

  it("fills the viewport with repeated procedural tiles and puts the lobby at the front centre", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1440);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(500);
    const { container } = render(<OfficeView sessions={[session()]} />);
    const viewport = container.querySelector<HTMLElement>(".office-viewport")!;
    const floor = container.querySelector<HTMLElement>(".office-floor")!;
    expect(viewport.style.backgroundImage).toContain("data:image/svg+xml");
    expect(viewport.style.backgroundRepeat).toBe("repeat");
    expect(parseFloat(floor.style.width)).toBeLessThan(1440);
    expect(1440 - parseFloat(floor.style.marginLeft) * 2 - parseFloat(floor.style.width)).toBeLessThanOrEqual(1);
    expect(parseFloat(floor.style.marginTop) + parseFloat(floor.style.height)).toBe(500);
  });

  it.each([1.25, 1.5])("aligns repeating floor tiles to device pixels at DPR %s", dpr => {
    vi.stubGlobal("devicePixelRatio", dpr);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1441);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(703);
    const { container } = render(<OfficeView sessions={[session()]} />);
    const viewport = container.querySelector<HTMLElement>(".office-viewport")!;
    const floor = container.querySelector<HTMLElement>(".office-floor")!;
    const pixels = (value: string) => parseFloat(value) * dpr;
    const [left, top] = viewport.style.backgroundPosition.split(" ").map(pixels);
    const period = pixels(viewport.style.backgroundSize);
    for (const value of [left, top, period / 4]) expect(value).toBeCloseTo(Math.round(value), 10);
    expect(left).toBeCloseTo(pixels(floor.style.marginLeft), 10);
    expect(top).toBeCloseTo(pixels(floor.style.marginTop), 10);
    expect(left).toBeGreaterThan(0);
    expect(top).toBeGreaterThan(0);
    expect(left + pixels(floor.style.width)).toBeLessThan(Math.floor(1441 * dpr));
  });

  it("supports old hub payloads and storage failures while keeping the chosen floor sticky", () => {
    for (const method of ["getItem", "setItem"] as const) {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error("Storage denied"); });
    }
    const claude = session("claude");
    const orca = { ...session("orca"), source: "orca" };
    expect([floorOf(claude), floorOf(orca), floorOf({ ...claude, source: "openbot" })]).toEqual(["claude", "orca", "openbot"]);
    mocks.state.sessions = [claude, orca];
    const view = render(<App />);
    expect(screen.getByRole("button", { name: "1 Claude", pressed: true })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2 Orca" }));
    mocks.state.sessions = [{ ...claude, needs_you: true }, orca];
    view.rerender(<App />);
    expect(screen.getByRole("button", { name: "2 Orca", pressed: true })).toBeTruthy();
  });

  it("omits snoozed, ended and lead-routed reports from floor badges", () => {
    const now = Date.parse("2026-11-17T12:00:00Z");
    const sessions: Session[] = [
      { ...session("snoozed"), needs_you: true, snoozed_until: "2026-11-18" },
      { ...session("ended"), status: "ended", needs_you: true },
      { ...session("lead-report"), status: "reported", report_to: "lead", report_pending: true },
      { ...session("user-report"), status: "reported", report_to: "you", report_pending: true },
    ];
    expect(floorAttention(sessions, now)).toEqual({ alerts: 1, needsYou: false });
  });

  it("shows model badges on every floor and recognizes Claude name variants", () => {
    for (const floor of ["claude", "orca", "openbot"] as const) {
      expect(modelBadge({ ...session(), floor, agent: { name: "codex" } })).toBe("Codex");
      expect(modelBadge({ ...session(), floor, agent: { name: "antigravity" } })).toBe("Gemini");
      for (const name of ["Claude", "claude-code", "Claude Code"]) {
        expect(modelBadge({ ...session(), floor, agent: { name } })).toBeUndefined();
      }
    }
  });

  it("reserves clear space above each worktree group for its sign", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(340);
    const worker = (id: string, role: "lead" | "junior"): Session => ({
      ...session(id), floor: "orca",
      team: { project: "Studio", worktree: id, role, lead: null, model: null },
    });
    render(<OfficeView sessions={[worker("main", "lead"), worker("feature-a", "junior"), worker("feature-b", "junior")]} />);
    const [lead, first, second] = screen.getAllByTestId("name-plate").map(plate => parseFloat(plate.style.top));
    const [a, b] = ["feature-a", "feature-b"].map(name => parseFloat(screen.getByTitle(name).style.top));
    const room = parseFloat(screen.getByText("Studio", { exact: true }).style.top);
    // Signs are vertically centred and plates end at their anchor.
    expect(a - 9).toBeGreaterThan(Math.max(room + 9, lead));
    expect(a + 9).toBeLessThan(first - 30);
    expect(b - 9).toBeGreaterThan(first);
    expect(b + 9).toBeLessThan(second - 30);
  });

  it("shows an Orca worker's model badge on its plate and card", () => {
    const worker: Session = { ...session(), source: "orca", agent: { name: "codex" },
      team: { project: "SeKantor", worktree: "web-checkout", role: "junior", lead: null, model: "gpt-6.2-sol" } };
    render(<OfficeView sessions={[worker]} />);
    const plate = screen.getByTestId("name-plate");
    expect(plate.textContent).toContain("GPT");
    expect(screen.getByText("web-checkout")).toBeTruthy();
    fireEvent.click(plate);
    expect(screen.getByRole("heading", { name: "codex GPT" })).toBeTruthy();
  });
  it("renders one plate per session", () => {
    render(<OfficeView sessions={[session(), session("two")]} />);
    expect(screen.getAllByTestId("name-plate")).toHaveLength(2);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("2 agents");
  });
  it("moves the name plate with the painted avatar", () => {
    render(<OfficeView sessions={[session()]} />);
    const paint = mocks.renderer.mock.calls[0][3]!;
    paint(new Map([["one", { x: 64, y: 96 }]]));
    const plate = screen.getByTestId("name-plate");
    expect(plate.style.left).toBe("40px");
    expect(plate.style.top).toBe("51px");
  });

  it("shows working and reported juniors on the main agent card", () => {
    const now = "2026-11-17T12:00:00Z";
    const junior = { id: "a", type: "Explore", status: "working" as const, activity: null,
      summary: null, started_at: now, ended_at: null };
    const parent = { ...session(), subagents: [junior,
      { ...junior, id: "b", type: "Review", status: "reported" as const, summary: "Checks passed.", ended_at: now }] };
    render(<OfficeView sessions={[parent]} now={Date.parse(now)} />);
    fireEvent.click(screen.getByTestId("name-plate"));
    expect(screen.getByRole("region", { name: "Subagents" }).textContent).toMatch(/Explore Working.*Review Reported.*Checks passed/);
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
    mocks.state.sessions = [session(), { ...session("waiting"), status: "waiting_input", needs_you: true }, { ...session("error"), status: "error" }, { ...session("report"), status: "reported", report_pending: true }, { ...session("accepted"), status: "reported", report_pending: false }, { ...session("muted"), status: "waiting_input", needs_you: true, snoozed_until: "2026-11-18T12:00:00Z" }];
    const view = render(<App />);
    expect(screen.getByText("1 busy \u00b7 1 need you \u00b7 1 reports \u00b7 1 errors")).toBeTruthy();
    expect(document.title).toBe("(1) SeKantor");
    expect(screen.getAllByTestId("name-plate")).toHaveLength(6);
    mocks.state.sessions = mocks.state.sessions.map(s => s.needs_you ? { ...s, snoozed_until: "2026-11-18T12:00:00Z" } : s);
    view.rerender(<App />);
    expect(screen.getByText("1 busy \u00b7 0 need you \u00b7 1 reports \u00b7 1 errors")).toBeTruthy();
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
  it("keeps plates visible at 1200px width with six rooms", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(1000);
    const sessions = Array.from({ length: 25 }, (_, i) => ({ ...session(String(i)), workspace: { cwd: `/project-${i % 6}` } }));
    render(<OfficeView sessions={sessions} />);
    expect(screen.getAllByTestId("name-plate").every(p => !(p as HTMLButtonElement).hidden)).toBe(true);
  });
  it("fits the canvas to whole device pixels per tile and labels the room and its landmarks", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(600);
    vi.stubGlobal("devicePixelRatio", 1.25);
    render(<OfficeView sessions={[session()]} />);
    const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
    const cssWidth = parseFloat(canvas.style.width);
    expect(cssWidth).toBeLessThanOrEqual(600);
    expect(canvas.width % layoutOffice([session()]).width).toBe(0);
    expect(cssWidth * 1.25).toBeCloseTo(canvas.width);
    expect(screen.getByText("repo", { exact: true }).getAttribute("title")).toBe("repo");
    for (const label of ["Your desk: permissions, questions, reports", "Rack", "Pantry", "Exit: session ended"]) {
      const sign = screen.getAllByText(label).find(el => el.classList.contains("office-sign"))!;
      expect(sign.closest('[aria-hidden="true"]')).toBeTruthy();
    }
    expect(screen.getByText("What the places mean")).toBeTruthy();
    expect(screen.getByText("Server rack: running commands").tagName).toBe("DT");
    expect(screen.getByText("Pantry: idle").tagName).toBe("DT");
    expect(screen.getByText(/Agents come here for approval/)).toBeTruthy();
  });
  it("anchors name plates above the seated avatar's head and hides plates when tiles are under 20px", () => {
    const spy = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(960);
    render(<OfficeView sessions={[session()]} />);
    const plate = screen.getByTestId("name-plate") as HTMLButtonElement;
    expect(plate.hidden).toBe(false);
    const topPx = parseFloat(plate.style.top);
    expect(topPx).toBeCloseTo((2.5 + 6 / 32) * 56);

    spy.mockReturnValue(300);
    act(() => { window.dispatchEvent(new Event("resize")); });
    expect((screen.getByTestId("name-plate") as HTMLButtonElement).hidden).toBe(true);
  });
  it("fills the width with multiple room columns on wide viewports at 100% zoom", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(450);
    render(<OfficeView sessions={[0, 1, 2].map(i => ({ ...session(String(i)), workspace: { cwd: `/project-${i}` } }))} />);
    const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
    // Short and wide: three columns give the larger tile, and the office still fits in both dimensions.
    expect(canvas.width % layoutOffice(projects(3)).width).toBe(0);
    expect(canvas.width).toBeLessThanOrEqual(1600);
    expect(canvas.height).toBeLessThanOrEqual(450);
    expect(parseFloat(canvas.style.width)).toBe(canvas.width);
  });
  it("fills at least 90% of the width at scaled DPI without horizontal overflow", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    const sessions = Array.from({ length: 6 }, (_, i) => ({ ...session(String(i)), workspace: { cwd: `/project-${i}` } }));
    for (const dpr of [1, 1.25, 1.5]) {
      vi.stubGlobal("devicePixelRatio", dpr);
      const view = render(<OfficeView sessions={sessions} />);
      const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
      const cssWidth = parseFloat(canvas.style.width);
      expect(cssWidth).toBeLessThanOrEqual(1600);
      expect(cssWidth).toBeGreaterThanOrEqual(0.9 * 1600);
      view.unmount();
    }
  });
  const projects = (n: number) => Array.from({ length: n }, (_, i) => ({ ...session(String(i)), workspace: { cwd: `/project-${i}` } }));
  it("contains the whole office in the viewport at every dpr and refits when projects come and go, without a resize", () => {
    const width = 1600, height = 700;
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(width);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(height);
    for (const dpr of [1, 1.25, 1.5]) {
      vi.stubGlobal("devicePixelRatio", dpr);
      const view = render(<OfficeView sessions={projects(2)} />);
      const sizes: number[] = [];
      for (const n of [2, 3, 4, 6, 3, 1]) {
        view.rerender(<OfficeView sessions={projects(n)} />);
        const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
        expect(parseFloat(canvas.style.width)).toBeLessThanOrEqual(width);
        expect(parseFloat(canvas.style.height)).toBeLessThanOrEqual(height);
        expect(canvas.width / dpr).toBeCloseTo(parseFloat(canvas.style.width));
        expect(canvas.width % 1).toBe(0);
        expect(canvas.height % 1).toBe(0);
        sizes.push(canvas.width);
      }
      expect(new Set(sizes).size).toBeGreaterThan(1);
      view.unmount();
    }
  });
  it("refits only when the room layout changes, not on status-only updates", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(700);
    const spy = vi.mocked(layoutOffice);
    const view = render(<OfficeView sessions={projects(3)} />);
    spy.mockClear();
    view.rerender(<OfficeView sessions={projects(3).map(s => ({ ...s, status: "waiting_input" as const }))} />);
    expect(spy.mock.calls.length).toBeLessThanOrEqual(1);
    spy.mockClear();
    view.rerender(<OfficeView sessions={projects(4)} />);
    expect(spy.mock.calls.length).toBeGreaterThan(1);
  });
  it("picks the column count that maximises the tile size", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    const view = render(<OfficeView sessions={projects(4)} />);
    const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
    const four = canvas.width;
    view.rerender(<OfficeView sessions={projects(2)} />);
    expect(screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ }).width).not.toBe(four);
  });
  it("does not add empty room columns for a single project", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    render(<OfficeView sessions={[session()]} />);
    const canvas = screen.getByRole<HTMLCanvasElement>("img", { name: /Office with/ });
    expect(canvas.width % 17).toBe(0);
    expect(canvas.width).toBeLessThanOrEqual(1600);
  });
  it("keeps the first-row plate below the room name at 1x", () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1600);
    render(<OfficeView sessions={[session()]} />);
    const sign = screen.getByText("repo", { exact: true });
    const plate = screen.getByTestId("name-plate");
    // Plate height is two text lines plus padding: 11px*1.2 + 9px*1.2 + 4px + 2px border.
    const plateHeight = 11 * 1.2 + 9 * 1.2 + 6;
    const signBottom = parseFloat(sign.style.top) + 12;
    expect(parseFloat(plate.style.top) - plateHeight).toBeGreaterThan(signBottom);
  });
  it("excludes ended and snoozed agents from canvas counts but keeps snoozed live avatars", () => {
    mocks.state.sessions = [session(), { ...session("ended"), status: "ended" }, { ...session("muted"), snoozed_until: "2026-11-18T12:00:00Z" }, { ...session("waiting"), status: "waiting_input", needs_you: true }];
    render(<App />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("Office with 2 agents: 1 busy, 1 need you, 0 reports, 0 errors");
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

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { formatSpan, groupDigest, Standup, type Digest, type DigestSession } from "./Standup";
import type { Session } from "./types";

const mocks = vi.hoisted(() => ({ state: { sessions: [] as Session[], connection: "live", loaded: true } }));
vi.mock("./office/render", () => ({ startRenderer: vi.fn(() => vi.fn()) }));
vi.mock("./useSessions", () => ({
  useSessions: () => mocks.state,
  useNow: () => Date.parse("2026-11-19T12:00:00Z"),
  useGhostNow: () => Date.parse("2026-11-19T12:00:00Z"),
}));

const row = (id: string, over: Partial<DigestSession> = {}): DigestSession => ({
  session_id: id, agent: "claude", model: "opus", project: { name: "alpha", kind: "web" }, floor: "claude", branch: "main",
  first_at: "2026-11-19T08:00:00+00:00", last_at: "2026-11-19T11:00:00+00:00", turns: 3, tools: { read: 5, edit: 2 },
  asked: 2, wait_s: 750, errors: 0, summary: "Refactored the parser", status: "running", status_since: "2026-11-19T11:00:00+00:00",
  waiting: false, needs_you: false, ...over,
});
const digest = (sessions: DigestSession[]): Digest => ({
  since: "2026-11-19T00:00:00+00:00", until: "2026-11-19T12:00:00+00:00",
  totals: { agents: sessions.length, turns: 7, asked: 4, wait_s: 3900, longest_wait_s: 1200, errors: 1, waiting_now: sessions.filter(s => s.waiting).length },
  sessions,
});
const live = (id: string, over: Partial<Session> = {}): Session => ({
  session_id: id, source: "claude", source_label: "Claude", status: "running", status_since: "2026-11-19T11:00:00Z",
  started_at: "2026-11-19T10:00:00Z", last_event_at: "2026-11-19T11:00:00Z", workspace: { cwd: "/repo", branch: "main" },
  capabilities: [], needs_you: false, agent: { name: "Ada" }, ...over,
});
const answer = (body: unknown) => vi.fn().mockResolvedValue({ ok: true, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); mocks.state.sessions = []; });

describe("standup helpers", () => {
  it("formats spans", () => {
    expect([0, 45, 720, 3900, 7260].map(formatSpan)).toEqual(["0s", "45s", "12m", "1h 05m", "2h 01m"]);
  });

  it("puts the waiting agents first, then groups by project in the hub's order", () => {
    const groups = groupDigest([
      row("w", { waiting: true, project: { name: "beta", kind: "web" } }),
      row("a1"), row("a2"), row("b1", { project: { name: "beta", kind: "web" } }), row("n", { project: null }),
    ]);
    expect(groups.map(g => g.title)).toEqual(["Waiting for you now", "alpha", "beta", "No project"]);
    expect(groups[1].sessions.map(s => s.session_id)).toEqual(["a1", "a2"]);
  });
});

describe("Rapat panel", () => {
  it("shows totals, waiting first, and switches the range", async () => {
    const fetch = answer(digest([row("w", { waiting: true, status: "waiting_approval", summary: "" }), row("a1")]));
    vi.stubGlobal("fetch", fetch);
    render(<Standup openable={() => true} onOpen={() => {}} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("standup-totals").textContent).toContain("2 agents"));
    expect(fetch).toHaveBeenCalledWith("/v1/digest?since=today", expect.anything());
    const text = screen.getByTestId("standup-totals").textContent!;
    expect(text).toContain("7 turns finished");
    expect(text).toContain("asked you 4×");
    expect(text).toContain("waited 1h 05m (longest 20m)");
    expect(text).toContain("1 error");
    expect(text).toContain("1 waiting now");
    const headings = screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent);
    expect(headings).toEqual(["Waiting for you now", "alpha"]);
    expect(screen.getAllByText(/read 5 · edit 2/)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Last 8 h" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/v1/digest?since=8h", expect.anything()));
    expect(screen.getByRole("button", { name: "Last 8 h", pressed: true })).toBeTruthy();
  });

  it("says so when the hub does not answer, and when nobody worked", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    const view = render(<Standup openable={() => true} onOpen={() => {}} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("did not answer"));
    view.unmount();
    vi.stubGlobal("fetch", answer(digest([])));
    render(<Standup openable={() => true} onOpen={() => {}} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/No agent was active/)).toBeTruthy());
  });

  it("opens an agent that is in the office, closes on Escape, and leaves the others plain", async () => {
    vi.stubGlobal("fetch", answer(digest([row("here"), row("gone")])));
    const onOpen = vi.fn();
    const onClose = vi.fn();
    render(<Standup openable={id => id === "here"} onOpen={onOpen} onClose={onClose} />);
    await waitFor(() => screen.getAllByRole("listitem"));
    expect(screen.getAllByRole("button", { name: /claude/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /claude/ }));
    expect(onOpen).toHaveBeenCalledWith("here");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Rapat in the header", () => {
  it("opens the agent's existing card from a row", async () => {
    mocks.state.sessions = [live("one"), live("two", { source: "orca", agent: { name: "Bo" } })];
    vi.stubGlobal("fetch", answer(digest([row("two", { agent: "Bo", floor: "orca" })])));
    render(<App />);
    expect(screen.queryByRole("region", { name: /Rapat/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rapat" }));
    await waitFor(() => screen.getByRole("button", { name: /Bo/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Bo/ }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: /Bo details/ })).toBeTruthy());
    expect(screen.queryByRole("region", { name: /Rapat/ })).toBeNull();
  });
});

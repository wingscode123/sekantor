// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AvatarCard } from "./AvatarCard";
import { layoutOffice } from "./model";
import type { Session } from "../types";
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("advances the elapsed minutes for an open non-snoozed card and stops on close", () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
  const s: Session = { session_id: "s", source: "claude", source_label: "Claude", status: "running", status_since: "2026-11-17T11:59:30Z", started_at: "2026-11-17T11:00:00Z", last_event_at: "2026-11-17T11:59:30Z", workspace: {}, capabilities: [], needs_you: false };
  const view = render(<AvatarCard session={s} avatar={layoutOffice([s]).avatars[0]} onClose={() => {}} />);
  expect(screen.getByText(/\(0m\)/)).toBeTruthy();
  expect(vi.getTimerCount()).toBe(1);
  act(() => { vi.advanceTimersByTime(31_000); });
  expect(screen.getByText(/\(1m\)/)).toBeTruthy();
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});


it("accepts a pending report through the hub", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [] }) });
  vi.stubGlobal("fetch", fetch);
  try {
    const s: Session = { session_id: "s", source: "claude", source_label: "Claude", status: "reported", status_since: "2026-11-17T11:59:30Z", started_at: "2026-11-17T11:00:00Z", last_event_at: "2026-11-17T11:59:30Z", workspace: {}, capabilities: [], needs_you: false, report_pending: true };
    const avatar = layoutOffice([s]).avatars[0];
    const view = render(<AvatarCard session={s} avatar={avatar} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/v1/sessions/s/acknowledge", expect.objectContaining({ method: "POST" })));
    view.rerender(<AvatarCard session={{ ...s, report_pending: false }} avatar={avatar} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  } finally {
    vi.unstubAllGlobals();
  }
});

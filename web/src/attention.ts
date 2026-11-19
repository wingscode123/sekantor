import { useEffect } from "react";
import { isSnoozed } from "./SessionMenu";
import type { Session } from "./types";

// Waiting levels: how long somebody has waited for you. One place for the thresholds.
export const WAIT_RESTLESS_MS = 2 * 60_000;
export const WAIT_URGENT_MS = 10 * 60_000;
export type WaitLevel = "calm" | "restless" | "urgent";

/** Brand palette (brand/BRAND.md): Gold, then Apricot, then the stronger Coral. */
export const LEVEL_COLOR: Record<WaitLevel, string> = { calm: "#F7CE82", restless: "#E5BB9F", urgent: "#EF8B72" };

export function waitLevel(ms: number): WaitLevel {
  return ms >= WAIT_URGENT_MS ? "urgent" : ms >= WAIT_RESTLESS_MS ? "restless" : "calm";
}

/** `<1m`, `3m`, `1h`, `1h 5m`. */
export function formatWait(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  return minutes % 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${Math.floor(minutes / 60)}h`;
}

/** Waiting for you: it needs you, it reports to you (not a lead), and it is not snoozed. */
export function waitsForYou(s: Session, now: number): boolean {
  return s.status !== "ended" && s.needs_you && s.report_to !== "lead" && !isSnoozed(s, now);
}

/** The people waiting for you, longest wait first. */
export function waitingQueue(sessions: Session[], now: number): Session[] {
  return sessions.filter(s => waitsForYou(s, now))
    .sort((a, b) => a.status_since.localeCompare(b.status_since) || a.session_id.localeCompare(b.session_id));
}

export interface QueueSummary { count: number; longest: Session; longestMs: number; text: string }

export function queueSummary(sessions: Session[], now: number): QueueSummary | null {
  const queue = waitingQueue(sessions, now);
  if (!queue.length) return null;
  const longestMs = Math.max(0, now - Date.parse(queue[0].status_since));
  return { count: queue.length, longest: queue[0], longestMs, text: `${queue.length} waiting · longest ${formatWait(longestMs)}` };
}

export const attentionTitle = (count: number) => count > 0 ? `(${count}) SeKantor` : "SeKantor";

const FAVICON_SIZE = 64;

function drawBadge(ctx: CanvasRenderingContext2D, size: number) {
  const r = size * 0.22, cx = size - r - 1, cy = r + 1;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = LEVEL_COLOR.urgent;
  ctx.fill();
  ctx.lineWidth = size * 0.06;
  ctx.strokeStyle = "#332B35";
  ctx.stroke();
}

function iconLink(): HTMLLinkElement | null {
  return document.querySelector<HTMLLinkElement>("link[rel~='icon']");
}

/** The tab title and a badge dot on the favicon while somebody waits for you (A1). */
export function useAttentionSignals(count: number) {
  useEffect(() => { document.title = attentionTitle(count); }, [count]);
  useEffect(() => {
    const link = iconLink();
    if (!link || count <= 0) return;
    const original = link.dataset.original ?? link.getAttribute("href") ?? "";
    link.dataset.original = original;
    let cancelled = false;
    try {
      const image = new Image();
      image.onload = () => {
        if (cancelled) return;
        try {
          const canvas = document.createElement("canvas");
          canvas.width = canvas.height = FAVICON_SIZE;
          const ctx = canvas.getContext("2d");
          if (!ctx) return;
          ctx.clearRect(0, 0, FAVICON_SIZE, FAVICON_SIZE);
          ctx.drawImage(image, 0, 0, FAVICON_SIZE, FAVICON_SIZE);
          drawBadge(ctx, FAVICON_SIZE);
          link.type = "image/png";
          link.setAttribute("href", canvas.toDataURL("image/png"));
        } catch { /* a blocked canvas keeps the plain icon */ }
      };
      image.src = original;
    } catch { /* no Image: keep the plain icon */ }
    return () => {
      cancelled = true;
      link.setAttribute("href", original);
      link.type = "image/svg+xml";
    };
  }, [count > 0]);
}

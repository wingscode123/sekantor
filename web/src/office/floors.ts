import { isSnoozed } from "../SessionMenu";
import type { Floor, Session } from "../types";

export const floors = [
  { id: "claude", label: "1 Claude" },
  { id: "orca", label: "2 Orca" },
  { id: "openbot", label: "3 OpenBot" },
] as const;

export function floorOf(s: Session): Floor {
  if (s.floor) return s.floor;
  if (s.source === "openbot" || s.host?.app === "openbot") return "openbot";
  return s.source === "orca" || s.host?.app === "orca" ? "orca" : "claude";
}

export function floorAttention(sessions: Session[], now: number): { alerts: number; needsYou: boolean } {
  let alerts = 0, needsYou = false;
  for (const s of sessions) {
    if (s.status === "ended" || isSnoozed(s, now)) continue;
    if (s.needs_you || (s.report_pending && s.report_to !== "lead")) alerts++;
    needsYou ||= s.needs_you;
  }
  return { alerts, needsYou };
}

const storageKey = "sekantor.floor";

export function defaultFloor(available: { id: Floor; needsYou: boolean }[]): Floor | undefined {
  if (!available.length) return undefined;
  const urgent = available.find(floor => floor.needsYou);
  if (urgent) return urgent.id;
  let saved: string | null = null;
  try { saved = localStorage.getItem(storageKey); } catch { /* Storage can be disabled. */ }
  return available.find(floor => floor.id === saved)?.id ?? available[0]?.id;
}

export function rememberFloor(floor: Floor): void {
  try { localStorage.setItem(storageKey, floor); } catch { /* Storage can be disabled. */ }
}

export function modelBadge(s: Session): string | undefined {
  if (!s.agent?.name || /^claude/i.test(s.agent.name)) return undefined;
  const model = s.team?.model || s.agent.model;
  if (model?.toLowerCase().startsWith("gpt")) return "GPT";
  if (/gemini|antigravity/i.test(`${s.agent.name} ${model ?? ""}`)) return "Gemini";
  if (/codex/i.test(s.agent.name)) return "Codex";
  return model || s.agent.name;
}

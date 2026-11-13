export interface Answer {
  ok: boolean;
  status: number;
  data: any;
}

/** A call to /v1/sessions/{id}/{path}. Null when the hub did not answer at all. */
export async function sessionApi(sessionId: string, path: string, method = "GET", body?: unknown): Promise<Answer | null> {
  try {
    const r = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}/${path}`, {
      method,
      cache: "no-store",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
  } catch {
    return null;
  }
}

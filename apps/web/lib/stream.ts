// Reads a server-sent-event response from the API, calling onEvent for each JSON event as it arrives.
export type AgentEvent =
  | { type: "token"; text: string }
  | { type: "tool_start"; id: string; name: string; kind: string }
  | { type: "tool_end"; id: string; name: string; status: string }
  | { type: "denied"; name: string; reason: string | null }
  | { type: "approval_required"; run_id: string; thread_id: string; requests: ApprovalRequest[] }
  | { type: "done"; status: string; run_id: string; thread_id: string; answer: string }
  | { type: "error"; message: string }
  | { type: "brief"; cached: boolean; content: string; brief_date: string; session: string };

export type ApprovalRequest = { id: string; tool: string; args: Record<string, unknown>; reason: string };

export async function readEvents(res: Response, onEvent: (e: AgentEvent) => void): Promise<void> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AgentEvent);
      }
    }
  }
}

// Turns a failed (non-stream) response into a readable message.
export async function errorMessage(res: Response): Promise<string> {
  try {
    const { detail } = (await res.json()) as { detail?: unknown };
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{ loc, msg }, ...]
    if (Array.isArray(detail) && detail.length) {
      return detail.map((d: { msg?: string }) => (d.msg ?? "").replace(/^Value error, /, "")).filter(Boolean).join(" ") || `Request failed (${res.status}).`;
    }
    if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  } catch {
    // not JSON
  }
  return `Request failed (${res.status}).`;
}

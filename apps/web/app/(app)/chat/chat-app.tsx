"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Ban, Check, LoaderCircle } from "lucide-react";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { type AgentEvent, type ApprovalRequest, errorMessage, readEvents } from "@/lib/stream";

export type Thread = { id: string; title: string; last_active_at: string };
type Activity = { id: string; label: string; status: "running" | "ok" | "error" | "denied" };
type Message = { role: "user" | "assistant"; text: string; activity?: Activity[] };
export type Usage = { spent_usd: number; cap_usd: number };

const API = "/api/foxhood";

// Plain-English labels for what the agent is doing.
const TOOL_LABELS: Record<string, string> = {
  get_portfolio_summary: "Checking your portfolio",
  get_positions: "Looking at your positions",
  get_watchlist_snapshot: "Checking your watchlist",
  get_price_performance: "Pulling price history",
  get_company_profile: "Reading the company profile",
  recall_memory: "Checking your saved notes",
  remember: "Saving a note",
  load_skill: "Loading a playbook",
  delegate_news_analysis: "Researching the news",
  get_macro_snapshot: "Checking economic data",
  get_series: "Pulling an economic series",
  get_upcoming_releases: "Checking the economic calendar",
  add_to_watchlist: "Adding to your watchlist",
  remove_from_watchlist: "Removing from your watchlist",
  add_holding: "Recording a purchase",
  submit_trade_order: "Placing a trade",
  get_earnings_calendar: "Checking earnings dates",
};
const label = (name: string) => TOOL_LABELS[name] ?? name;

function ActivityIcon({ status }: { status: Activity["status"] }) {
  const cls = "size-3.5 shrink-0";
  if (status === "running") return <LoaderCircle className={`${cls} motion-safe:animate-spin`} aria-label="In progress" />;
  if (status === "ok") return <Check className={`${cls} text-up`} aria-label="Done" />;
  if (status === "denied") return <Ban className={cls} aria-label="Blocked" />;
  return <AlertTriangle className={cls} aria-label="Failed" />;
}

function describeRequest(r: ApprovalRequest): string {
  const a = r.args;
  switch (r.tool) {
    case "remember":
      return `Save this note: "${String(a.content ?? "")}"`;
    case "add_to_watchlist":
      return `Add ${String(a.ticker ?? "")} to your watchlist`;
    case "remove_from_watchlist":
      return `Remove ${String(a.ticker ?? "")} from your watchlist`;
    case "add_holding":
      return `Record a purchase of ${String(a.ticker ?? "")} on ${String(a.purchase_date ?? "")} (${
        a.shares != null ? `${String(a.shares)} shares` : `$${String(a.amount)}`})`;
    default:
      return `${r.tool}(${JSON.stringify(a)})`;
  }
}

export default function ChatApp({ initialThreads, initialUsage }: { initialThreads: Thread[]; initialUsage: Usage | null }) {
  const [threads, setThreads] = useState<Thread[]>(initialThreads);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<{ runId: string | null; requests: ApprovalRequest[] }>({ runId: null, requests: [] });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(initialUsage);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshSidebar = useCallback(async () => {
    const [t, u] = await Promise.all([fetch(`${API}/threads`), fetch(`${API}/usage/today`)]);
    if (t.ok) setThreads(await t.json());
    if (u.ok) setUsage(await u.json());
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  // Apply a change to the assistant message currently being written (always the last one).
  const updateLast = (fn: (m: Message) => Message) =>
    setMessages((ms) => (ms.length ? [...ms.slice(0, -1), fn(ms[ms.length - 1])] : ms));

  function onEvent(e: AgentEvent) {
    switch (e.type) {
      case "token":
        updateLast((m) => ({ ...m, text: m.text + e.text }));
        break;
      case "tool_start":
        updateLast((m) => ({ ...m, activity: [...(m.activity ?? []), { id: e.id, label: label(e.name), status: "running" }] }));
        break;
      case "tool_end":
        updateLast((m) => ({
          ...m,
          activity: (m.activity ?? []).map((a) => (a.id === e.id ? { ...a, status: e.status === "ok" ? "ok" : "error" } : a)),
        }));
        break;
      case "denied":
        updateLast((m) => ({
          ...m,
          activity: [...(m.activity ?? []), { id: `denied-${e.name}`, label: `${label(e.name)}: blocked. ${e.reason ?? ""}`, status: "denied" }],
        }));
        break;
      case "approval_required":
        setThreadId(e.thread_id);
        setPending({ runId: e.run_id, requests: e.requests });
        break;
      case "done":
        setThreadId(e.thread_id);
        break;
      case "error":
        setError(e.message);
        break;
    }
  }

  // Send a request that streams back agent events (a new message, or an approval decision).
  async function run(url: string, body: unknown, userText?: string) {
    setBusy(true);
    setError(null);
    setPending({ runId: null, requests: [] });
    setMessages((ms) => [...ms, ...(userText ? [{ role: "user" as const, text: userText }] : []), { role: "assistant", text: "" }]);
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) {
        setError(await errorMessage(res));
        setMessages((ms) => ms.slice(0, -1)); // drop the empty assistant bubble
        return;
      }
      await readEvents(res, onEvent);
    } catch {
      setError("Lost the connection. Your answer may still finish; reopen the conversation in a moment.");
    } finally {
      setBusy(false);
      void refreshSidebar();
    }
  }

  function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    void run(`${API}/chat`, { message: text, thread_id: threadId }, text);
  }

  function decide(approved: boolean) {
    if (!threadId) return;
    const decisions = Object.fromEntries(pending.requests.map((r) => [r.id, { approved }]));
    void run(`${API}/threads/${encodeURIComponent(threadId)}/approve`, { decisions, run_id: pending.runId });
  }

  async function openThread(id: string) {
    if (busy) return;
    setError(null);
    const res = await fetch(`${API}/threads/${encodeURIComponent(id)}`);
    if (!res.ok) return setError(await errorMessage(res));
    const data = (await res.json()) as { messages: { role: "user" | "assistant"; text: string; tools: string[] }[]; pending: ApprovalRequest[] };
    setThreadId(id);
    setMessages(
      data.messages
        .filter((m) => m.text)
        .map((m) => ({ role: m.role, text: m.text })),
    );
    setPending({ runId: null, requests: data.pending });
  }

  function newChat() {
    if (busy) return;
    setThreadId(null);
    setMessages([]);
    setPending({ runId: null, requests: [] });
    setError(null);
  }

  const placeholder = pending.requests.length ? "Approve or reject above, or ask something new" : "Ask about your portfolio, a stock, or the market";

  return (
    <div className="flex min-h-0 flex-1 gap-8">
      <aside aria-label="Conversations" className="hidden w-60 shrink-0 flex-col gap-1 overflow-y-auto border-r border-rule pr-4 md:flex">
        <Button variant="outline" onClick={newChat} disabled={busy} className="mb-2 h-10 bg-paper-raised">New chat</Button>
        {threads.map((t) => (
          <button
            key={t.id}
            onClick={() => void openThread(t.id)}
            aria-current={t.id === threadId ? "true" : undefined}
            className="truncate rounded-md px-2.5 py-2 text-left text-sm text-ink-muted hover:bg-muted hover:text-ink aria-[current=true]:bg-muted aria-[current=true]:font-medium aria-[current=true]:text-ink"
            title={t.title}
          >
            {t.title}
          </button>
        ))}
        {usage && (
          <p className="mt-auto pt-3 text-[13px] text-ink-muted">
            Used today: ${usage.spent_usd.toFixed(3)} of ${usage.cap_usd.toFixed(2)}
          </p>
        )}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        {/* On phones the conversation list becomes a picker. */}
        <div className="mb-3 flex gap-2 md:hidden">
          <label htmlFor="fx-thread" className="sr-only">Past conversations</label>
          <select
            id="fx-thread"
            value={threadId ?? ""}
            onChange={(e) => (e.target.value ? void openThread(e.target.value) : newChat())}
            disabled={busy}
            className="h-10 min-w-0 flex-1 rounded-lg border border-rule-strong bg-paper-raised px-2 text-sm"
          >
            <option value="">New conversation</option>
            {threads.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
          <Button variant="outline" onClick={newChat} disabled={busy} className="h-10 bg-paper-raised">New chat</Button>
        </div>

        <div className="flex-1 overflow-y-auto pb-4">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && (
              <div className="pt-12 md:pt-20">
                <p className="text-2xl font-semibold tracking-tight">What do you want to know?</p>
                <p className="mt-2 text-ink-muted">Try &quot;How is my portfolio doing today?&quot; or &quot;When does NVDA report?&quot;</p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
                <div className={m.role === "user" ? "max-w-[85%] rounded-xl bg-muted px-4 py-2.5" : "max-w-full"}>
                  {m.activity && m.activity.length > 0 && (
                    <ul className="mb-3 space-y-1 text-[13px] text-ink-muted">
                      {m.activity.map((a) => (
                        <li key={a.id} className="flex items-center gap-2">
                          <ActivityIcon status={a.status} />
                          {a.label}
                        </li>
                      ))}
                    </ul>
                  )}
                  {m.role === "user" ? (
                    <p className="whitespace-pre-wrap leading-relaxed">{m.text}</p>
                  ) : m.text ? (
                    <Markdown text={m.text} />
                  ) : busy && i === messages.length - 1 ? (
                    <p className="text-ink-muted">Thinking…</p>
                  ) : null}
                </div>
              </div>
            ))}

            {pending.requests.length > 0 && (
              <div className="rounded-xl border border-rule-strong bg-paper-raised p-4">
                <p className="mb-2 font-medium">Foxhood wants to:</p>
                <ul className="mb-4 list-disc space-y-1 pl-5">
                  {pending.requests.map((r) => (
                    <li key={r.id}>{describeRequest(r)}</li>
                  ))}
                </ul>
                <div className="flex gap-2">
                  <Button onClick={() => decide(true)} disabled={busy} className="h-10 px-4">Approve</Button>
                  <Button variant="outline" onClick={() => decide(false)} disabled={busy} className="h-10 px-4">Reject</Button>
                </div>
              </div>
            )}

            {error && <p role="alert" className="text-fox">{error}</p>}
            <div ref={bottom} />
          </div>
        </div>

        <div className="mx-auto w-full max-w-3xl">
          <form
            className="flex items-end gap-2 rounded-xl border border-rule-strong bg-paper-raised p-2 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-fox shadow-[0_8px_24px_rgba(34,30,31,0.10)]"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <label htmlFor="fx-chat-input" className="sr-only">Message</label>
            <textarea
              id="fx-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={2}
              maxLength={4000}
              placeholder={placeholder}
              className="min-w-0 flex-1 resize-none bg-transparent px-2 py-1.5 text-base outline-none focus-visible:outline-none"
            />
            <Button type="submit" disabled={busy || !input.trim()} className="h-11 px-5 text-[15px] font-semibold">
              {busy ? "Working…" : "Ask"}
            </Button>
          </form>
          <p className="pt-2 text-[13px] text-ink-muted">
            Prices from Tiingo, quotes and earnings from Finnhub, economic data from FRED. Not financial advice.
          </p>
        </div>
      </section>
    </div>
  );
}

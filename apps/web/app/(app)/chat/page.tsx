import { apiFetch } from "@/lib/api";
import ChatApp, { type Thread, type Usage } from "./chat-app";

async function loadSidebar(): Promise<{ threads: Thread[]; usage: Usage | null }> {
  try {
    const [t, u] = await Promise.all([apiFetch("/threads"), apiFetch("/usage/today")]);
    return { threads: t.ok ? await t.json() : [], usage: u.ok ? await u.json() : null };
  } catch {
    return { threads: [], usage: null }; // the page still loads; sending a message will show the real error
  }
}

export default async function ChatPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const [{ threads, usage }, { q }] = await Promise.all([loadSidebar(), searchParams]);
  return (
    <main className="mx-auto flex h-full min-h-0 w-full max-w-[1200px] flex-col px-5 pt-4 pb-3 md:px-10">
      <h1 className="sr-only">Chat</h1>
      <ChatApp initialThreads={threads} initialUsage={usage} initialQuestion={q?.trim().slice(0, 4000) || null} />
    </main>
  );
}

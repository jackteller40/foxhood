import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
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

export default async function ChatPage() {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { threads, usage } = await loadSidebar();
  return (
    <main className="mx-auto flex h-screen max-w-5xl flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Foxhood chat</h1>
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">Dashboard</Link>
      </div>
      <ChatApp initialThreads={threads} initialUsage={usage} />
    </main>
  );
}
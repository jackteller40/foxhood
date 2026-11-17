"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";

// Sends the question to Chat, which asks it straight away.
export function AskBar() {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      aria-label="Ask Foxhood"
      onSubmit={(e) => {
        e.preventDefault();
        const text = q.trim();
        if (text) router.push(`/chat?q=${encodeURIComponent(text)}`);
      }}
      className="sticky bottom-4 flex gap-2 rounded-xl border border-rule-strong bg-paper-raised p-2 shadow-[0_8px_24px_rgba(34,30,31,0.10)] focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-fox"
    >
      <label htmlFor="fx-ask" className="sr-only">Ask Foxhood</label>
      <input
        id="fx-ask"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        maxLength={4000}
        placeholder="Ask about your portfolio, a stock, or the market"
        className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-base outline-none focus-visible:outline-none"
      />
      <Button type="submit" disabled={!q.trim()} className="h-11 px-5 text-[15px] font-semibold">Ask</Button>
    </form>
  );
}

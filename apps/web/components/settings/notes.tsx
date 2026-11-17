"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";

export type Note = { id: string; kind: "preference" | "fact" | "brief_takeaway"; content: string; tags: string[] };

const KIND: Record<Note["kind"], string> = { preference: "Preference", fact: "Fact", brief_takeaway: "From a brief" };

// What the agent remembers about you (saved in chat, from briefs, or added here).
export function Notes({ notes }: { notes: Note[] }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(path: string, method: "POST" | "DELETE", body?: unknown) {
    setBusy(true);
    setError(null);
    const err = await send(path, method, body);
    setBusy(false);
    if (err) {
      setError(err);
      return false;
    }
    router.refresh();
    return true;
  }

  return (
    <div className="max-w-2xl">
      {notes.length === 0 ? (
        <p className="text-ink-muted">Nothing saved yet. Tell Foxhood things like “never let one stock go over 25%” and it can save them.</p>
      ) : (
        <ul>
          {notes.map((n) => (
            <li key={n.id} className="flex items-start justify-between gap-4 border-t border-rule py-3 last:border-b">
              <div>
                <p>{n.content}</p>
                <p className="text-sm text-ink-muted">{KIND[n.kind]}</p>
              </div>
              <button type="button" disabled={busy} onClick={() => void run(`memories/${n.id}`, "DELETE")}
                aria-label={`Forget: ${n.content}`} className="shrink-0 cursor-pointer text-sm text-ink-muted hover:text-fox">
                Forget
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="mt-4 flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (text.trim() && (await run("memories", "POST", { kind: "preference", content: text.trim() }))) setText("");
        }}
      >
        <label htmlFor="n-text" className="sr-only">New note</label>
        <input id="n-text" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
          placeholder="Add something Foxhood should remember" className={inputClass} />
        <Button type="submit" variant="outline" disabled={busy || !text.trim()} className="h-10 bg-paper-raised px-4">Save</Button>
      </form>
      {error && <p role="alert" className="mt-2 text-fox">{error}</p>}
    </div>
  );
}

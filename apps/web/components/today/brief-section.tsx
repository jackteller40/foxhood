"use client";

import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { errorMessage, readEvents } from "@/lib/stream";
import type { Brief, BriefPeek } from "@/lib/today";

// The first real paragraph of the brief (skipping headings), for the collapsed view.
function excerpt(md: string): string {
  const paras = md.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => p && !p.startsWith("#"));
  return paras[0] ?? md;
}

export function BriefSection({ peek }: { peek: BriefPeek | null }) {
  const [brief, setBrief] = useState<Brief | null>(peek?.brief ?? null);
  const [draft, setDraft] = useState("");
  const [writing, setWriting] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const morning = peek?.session === "premarket";
  const title = morning ? "This morning’s brief" : "The latest market recap";

  async function write() {
    setWriting(true);
    setError(null);
    setDraft("");
    try {
      const res = await fetch("/api/foxhood/briefs/today", { method: "POST" });
      if (!res.ok) return setError(await errorMessage(res));
      await readEvents(res, (e) => {
        if (e.type === "token") setDraft((d) => d + e.text);
        else if (e.type === "brief") setBrief({ brief_date: e.brief_date, session: e.session, content: e.content, created_at: "" });
        else if (e.type === "error") setError(e.message);
      });
    } catch {
      setError("Lost the connection while writing. Reload in a minute; the brief will be saved if it finished.");
    } finally {
      setWriting(false);
    }
  }

  return (
    <section aria-labelledby="fx-brief">
      <h2 id="fx-brief" className="mb-3 text-lg font-semibold">{title}</h2>
      {brief ? (
        <>
          <div className="max-w-[38em]">
            <Markdown text={open ? brief.content : excerpt(brief.content)} />
          </div>
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
            className="mt-3 cursor-pointer font-semibold text-fox hover:text-fox-dark">
            {open ? "Show less" : "Read the full brief"}
          </button>
        </>
      ) : writing ? (
        <div className="max-w-[38em]" aria-live="polite">
          <p className="mb-2 text-ink-muted">Writing it now. This takes about 20 seconds.</p>
          {draft && <Markdown text={draft} />}
        </div>
      ) : (
        <>
          <p className="max-w-[38em] text-ink-muted">
            {morning ? "Today’s brief hasn’t been written yet." : "The recap for the last session hasn’t been written yet."}
          </p>
          <Button onClick={() => void write()} className="mt-3 h-10 px-4 font-semibold">
            {morning ? "Write this morning’s brief" : "Write the recap"}
          </Button>
        </>
      )}
      {error && <p role="alert" className="mt-2 text-fox">{error}</p>}
    </section>
  );
}

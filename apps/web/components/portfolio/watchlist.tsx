"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";
import type { WatchItem } from "@/lib/today";

export function Watchlist({ items }: { items: WatchItem[] }) {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
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
    <div className="max-w-3xl">
      {items.length === 0 ? (
        <p className="text-ink-muted">Nothing on your watchlist. Foxhood checks these for earnings and mentions them in briefs.</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {items.map((w) => (
            <li key={w.id} className="flex items-center gap-1 rounded-lg border border-rule-strong bg-paper-raised py-1 pr-1 pl-3">
              <span className="font-semibold">{w.ticker}</span>
              {w.note && <span className="text-sm text-ink-muted">{w.note}</span>}
              <button type="button" aria-label={`Remove ${w.ticker} from watchlist`} disabled={busy}
                onClick={() => void run(`watchlist/${w.id}`, "DELETE")}
                className="flex size-8 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-muted hover:text-ink">
                <X className="size-4" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="mt-4 flex max-w-sm gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          const t = ticker.trim().toUpperCase();
          if (t && (await run("watchlist", "POST", { ticker: t }))) setTicker("");
        }}
      >
        <label htmlFor="w-ticker" className="sr-only">Ticker to watch</label>
        <input id="w-ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. TSLA" maxLength={12}
          autoComplete="off" className={`${inputClass} uppercase placeholder:normal-case`} />
        <Button type="submit" variant="outline" disabled={busy || !ticker.trim()} className="h-10 bg-paper-raised px-4">Watch</Button>
      </form>
      {error && <p role="alert" className="mt-2 text-fox">{error}</p>}
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Field, inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";

export function AddHolding() {
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [date, setDate] = useState("");
  const [by, setBy] = useState<"shares" | "amount">("shares");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const today = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local time

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const n = Number(qty);
    if (!ticker.trim() || !date || !(n > 0)) return setError("Fill in the ticker, the date and a quantity above zero.");
    setBusy(true);
    setError(null);
    setAdded(null);
    const t = ticker.trim().toUpperCase();
    const err = await send("holdings", "POST", { ticker: t, purchase_date: date, [by]: n });
    setBusy(false);
    if (err) return setError(err);
    setAdded(`Added ${t}.`);
    setTicker("");
    setQty("");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="max-w-3xl" noValidate>
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr_1.4fr]">
        <Field id="h-ticker" label="Ticker">
          <input id="h-ticker" value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="AAPL" autoCapitalize="characters"
            autoComplete="off" maxLength={12} className={`${inputClass} uppercase placeholder:normal-case`} />
        </Field>
        <Field id="h-date" label="Date bought">
          <input id="h-date" type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} className={inputClass} />
        </Field>
        <Field id="h-qty" label={by === "shares" ? "Shares" : "Dollars invested"}>
          <div className="flex gap-2">
            <input id="h-qty" type="number" inputMode="decimal" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)}
              placeholder={by === "shares" ? "10" : "1,000"} className={inputClass} />
            <div role="group" aria-label="Quantity in" className="flex shrink-0 rounded-lg border border-rule-strong bg-paper-raised p-0.5">
              {(["shares", "amount"] as const).map((k) => (
                <button key={k} type="button" aria-pressed={by === k} onClick={() => setBy(k)}
                  className="cursor-pointer rounded-md px-2.5 text-sm text-ink-muted aria-pressed:bg-muted aria-pressed:font-semibold aria-pressed:text-ink">
                  {k === "shares" ? "Shares" : "$"}
                </button>
              ))}
            </div>
          </div>
        </Field>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={busy} className="h-10 px-4 font-semibold">{busy ? "Checking the price…" : "Add holding"}</Button>
        {error && <p role="alert" className="text-fox">{error}</p>}
        {added && <p role="status" className="text-up">{added}</p>}
      </div>
    </form>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { inputClass } from "@/components/field";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/stream";
import { money } from "@/lib/today";

type PreviewRow = {
  row: number;
  ticker: string;
  status: "ok" | "error";
  purchase_date: string | null;
  shares: number | null;
  amount: number | null;
  error: string | null;
  cost_basis: number | null;
  broker_cost_basis: number | null;
};
type Preview = { rows: PreviewRow[]; ok: number; errors: number; skipped: { row: number; ticker: string; reason: string }[] };

// The preview rows back into a CSV, so edited dates can be checked again.
function toCsv(rows: PreviewRow[]): string {
  const cell = (v: number | string | null) => (v == null ? "" : String(v));
  return ["ticker,date,shares,amount,cost basis total",
    ...rows.map((r) => [r.ticker, r.purchase_date, r.shares, r.amount, r.broker_cost_basis].map(cell).join(","))].join("\n");
}


export function CsvImport() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [needsDate, setNeedsDate] = useState<string | null>(null); // the API's explanation, when the file has no dates
  const [defaultDate, setDefaultDate] = useState("");
  const [edited, setEdited] = useState(false);
  const today = new Date().toLocaleDateString("en-CA");
  const [busy, setBusy] = useState<"checking" | "saving" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function post(path: string, body: unknown): Promise<Response | null> {
    try {
      return await fetch(`/api/foxhood/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch {
      setError("Couldn't reach Foxhood. Check your connection and try again.");
      return null;
    }
  }

  async function check(csv = text, date = defaultDate) {
    if (!csv.trim()) return setError("Choose a file or paste some rows first.");
    setBusy("checking");
    setError(null);
    setDone(null);
    const res = await post("holdings/import/preview", { csv, default_date: date || null });
    setBusy(null);
    if (!res) return;
    if (!res.ok) {
      const body = await res.clone().json().catch(() => null);
      if (body?.detail?.needs_date) {
        setPreview(null);
        return setNeedsDate(body.detail.message);
      }
      return setError(await errorMessage(res));
    }
    setPreview(await res.json());
    setEdited(false);
  }

  function reset(next: string) {
    setText(next);
    setPreview(null);
    setNeedsDate(null);
    setDefaultDate("");
    setDone(null);
  }

  function editDate(row: number, value: string) {
    setPreview((p) => p && { ...p, rows: p.rows.map((r) => (r.row === row ? { ...r, purchase_date: value || null } : r)) });
    setEdited(true);
  }

  async function commit() {
    if (!preview) return;
    const rows = preview.rows.map((r) => ({ ticker: r.ticker, purchase_date: r.purchase_date, shares: r.shares, amount: r.amount }));
    setBusy("saving");
    setError(null);
    const res = await post("holdings/import/commit", { rows });
    setBusy(null);
    if (!res) return;
    if (!res.ok) return setError(await errorMessage(res));
    const { created } = (await res.json()) as { created: number };
    setDone(`Imported ${created} ${created === 1 ? "holding" : "holdings"}.`);
    reset("");
    router.refresh();
  }

  return (
    <div className="max-w-3xl">
      <p className="mb-3 max-w-[40em] text-ink-muted">
        Needs a ticker column and either shares or the dollar amount, plus purchase dates if the file has them. Broker exports
        like Fidelity&apos;s positions download work as they are. Nothing is saved until you confirm.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex h-10 cursor-pointer items-center rounded-lg border border-rule-strong bg-paper-raised px-4 text-sm font-medium hover:bg-muted focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-fox">
          Choose a CSV file
          <input type="file" accept=".csv,text/csv,text/plain" className="sr-only"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) reset(await f.text());
              e.target.value = "";
            }} />
        </label>
        <span className="text-sm text-ink-muted">or paste below</span>
      </div>
      <label htmlFor="csv-text" className="sr-only">CSV text</label>
      <textarea id="csv-text" value={text} onChange={(e) => reset(e.target.value)} rows={5} maxLength={200_000}
        placeholder={"ticker,date,shares\nAAPL,2024-03-01,10\nMSFT,2023-11-15,5"}
        className={`${inputClass} mt-3 h-auto py-2 font-[inherit] text-sm`} />
      <div className="mt-3 flex flex-wrap items-center gap-4">
        {!needsDate && (
          <Button type="button" variant="outline" onClick={() => void check()} disabled={busy !== null} className="h-10 bg-paper-raised px-4">
            {busy === "checking" ? "Checking each row…" : "Check rows"}
          </Button>
        )}
        {error && <p role="alert" className="text-fox">{error}</p>}
        {done && <p role="status" className="text-up">{done}</p>}
      </div>

      {needsDate && !preview && (
        <form className="mt-5 rounded-xl border border-rule-strong bg-paper-raised p-4"
          onSubmit={(e) => { e.preventDefault(); if (defaultDate) void check(text, defaultDate); }}>
          <p className="max-w-[40em]">{needsDate}</p>
          <label htmlFor="csv-date" className="mt-3 block text-[15px] font-medium">When did you buy these?</label>
          <div className="mt-1.5 flex max-w-sm gap-2">
            <input id="csv-date" type="date" max={today} value={defaultDate} onChange={(e) => setDefaultDate(e.target.value)} className={inputClass} />
            <Button type="submit" disabled={!defaultDate || busy !== null} className="h-10 px-4 font-semibold">
              {busy === "checking" ? "Checking…" : "Check rows"}
            </Button>
          </div>
        </form>
      )}

      {preview && (
        <div className="mt-6">
          <p className="mb-2 font-medium">
            {edited
              ? "You changed some dates. Check again before importing."
              : preview.errors === 0
                ? `All ${preview.ok} rows look good.`
                : `${preview.errors} of ${preview.rows.length} rows need fixing. Fix the dates below or edit the file; nothing is imported until every row is OK.`}
          </p>
          {preview.rows.some((r) => r.broker_cost_basis != null) && (
            <p className="mb-3 max-w-[40em] text-sm text-ink-muted">
              Foxhood works out what you paid from the price on the date you give. If a cost is far from what your file says, move
              that row&apos;s date closer to when you really bought it.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-[15px]">
              <thead>
                <tr className="border-b border-rule-strong text-left text-[13px] text-ink-muted">
                  <th scope="col" className="py-2 pr-4 font-medium">Row</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Ticker</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Bought</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Quantity</th>
                  <th scope="col" className="py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row} className="border-b border-rule align-top">
                    <td className="py-2 pr-4 text-ink-muted">{r.row}</td>
                    <td className="py-2 pr-4 font-semibold">{r.ticker || "?"}</td>
                    <td className="py-1 pr-4">
                      <label htmlFor={`csv-d-${r.row}`} className="sr-only">Date bought for row {r.row}</label>
                      <input id={`csv-d-${r.row}`} type="date" max={today} value={r.purchase_date ?? ""} onChange={(e) => editDate(r.row, e.target.value)}
                        className={`${inputClass} h-9 w-40 text-sm`} />
                    </td>
                    <td className="py-2 pr-4">{r.shares != null ? `${r.shares} shares` : r.amount != null ? money(r.amount) : ""}</td>
                    <td className={`py-2 ${r.status === "ok" ? "text-up" : "text-fox"}`}>
                      {r.status === "ok" ? `OK${r.cost_basis != null ? `, cost ${money(r.cost_basis)}` : ""}` : r.error}
                      {r.broker_cost_basis != null && <span className="block text-sm text-ink-muted">Your file says {money(r.broker_cost_basis)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.skipped.length > 0 && (
            <p className="mt-3 text-sm text-ink-muted">
              Skipped: {preview.skipped.map((s) => `${s.ticker} (${s.reason.toLowerCase()})`).join(", ")}.
            </p>
          )}
          {edited ? (
            <Button type="button" variant="outline" onClick={() => void check(toCsv(preview.rows), "")} disabled={busy !== null}
              className="mt-4 h-10 bg-paper-raised px-4">
              {busy === "checking" ? "Checking…" : "Check again"}
            </Button>
          ) : preview.errors === 0 && preview.ok > 0 && (
            <Button type="button" onClick={() => void commit()} disabled={busy !== null} className="mt-4 h-10 px-4 font-semibold">
              {busy === "saving" ? "Importing…" : `Import ${preview.ok} ${preview.ok === 1 ? "holding" : "holdings"}`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

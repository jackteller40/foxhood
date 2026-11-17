"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { inputClass } from "@/components/field";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/stream";
import { localDate, money } from "@/lib/today";

type PreviewRow = {
  row: number;
  ticker: string;
  status: "ok" | "error";
  purchase_date: string | null;
  shares: number | null;
  amount: number | null;
  error: string | null;
  cost_basis: number | null;
};
type Preview = { rows: PreviewRow[]; ok: number; errors: number };

const fmtDate = (iso: string | null) => (iso ? localDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "");

export function CsvImport() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
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

  async function check() {
    if (!text.trim()) return setError("Choose a file or paste some rows first.");
    setBusy("checking");
    setError(null);
    setDone(null);
    const res = await post("holdings/import/preview", { csv: text });
    setBusy(null);
    if (!res) return;
    if (!res.ok) return setError(await errorMessage(res));
    setPreview(await res.json());
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
    setPreview(null);
    setText("");
    router.refresh();
  }

  return (
    <div className="max-w-3xl">
      <p className="mb-3 max-w-[40em] text-ink-muted">
        Needs a ticker column, a date column, and either shares or the dollar amount. Most broker exports work as they are;
        other columns are ignored. Nothing is saved until you confirm.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex h-10 cursor-pointer items-center rounded-lg border border-rule-strong bg-paper-raised px-4 text-sm font-medium hover:bg-muted focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-fox">
          Choose a CSV file
          <input type="file" accept=".csv,text/csv,text/plain" className="sr-only"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) { setText(await f.text()); setPreview(null); setDone(null); }
              e.target.value = "";
            }} />
        </label>
        <span className="text-sm text-ink-muted">or paste below</span>
      </div>
      <label htmlFor="csv-text" className="sr-only">CSV text</label>
      <textarea id="csv-text" value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} rows={5} maxLength={200_000}
        placeholder={"ticker,date,shares\nAAPL,2024-03-01,10\nMSFT,2023-11-15,5"}
        className={`${inputClass} mt-3 h-auto py-2 font-[inherit] text-sm`} />
      <div className="mt-3 flex flex-wrap items-center gap-4">
        <Button type="button" variant="outline" onClick={() => void check()} disabled={busy !== null} className="h-10 bg-paper-raised px-4">
          {busy === "checking" ? "Checking each row…" : "Check rows"}
        </Button>
        {error && <p role="alert" className="text-fox">{error}</p>}
        {done && <p role="status" className="text-up">{done}</p>}
      </div>

      {preview && (
        <div className="mt-6">
          <p className="mb-2 font-medium">
            {preview.errors === 0
              ? `All ${preview.ok} rows look good.`
              : `${preview.errors} of ${preview.rows.length} rows need fixing. Edit the file and check again; nothing is imported until every row is OK.`}
          </p>
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
                    <td className="py-2 pr-4">{fmtDate(r.purchase_date)}</td>
                    <td className="py-2 pr-4">{r.shares != null ? `${r.shares} shares` : r.amount != null ? money(r.amount) : ""}</td>
                    <td className={`py-2 ${r.status === "ok" ? "text-up" : "text-fox"}`}>
                      {r.status === "ok" ? `OK${r.cost_basis != null ? `, cost ${money(r.cost_basis)}` : ""}` : r.error}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.errors === 0 && preview.ok > 0 && (
            <Button type="button" onClick={() => void commit()} disabled={busy !== null} className="mt-4 h-10 px-4 font-semibold">
              {busy === "saving" ? "Importing…" : `Import ${preview.ok} ${preview.ok === 1 ? "holding" : "holdings"}`}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

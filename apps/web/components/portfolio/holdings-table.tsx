"use client";

import { ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { Fragment, useState } from "react";
import { send } from "@/components/field";
import { localDate, money, moveColor, pct, type Holding, type Position } from "@/lib/today";

type Row = { ticker: string; name: string; position: Position | null; lots: Holding[] };

function rows(positions: Position[], holdings: Holding[]): Row[] {
  const byTicker = new Map<string, Holding[]>();
  for (const h of holdings) byTicker.set(h.ticker, [...(byTicker.get(h.ticker) ?? []), h]);
  const out: Row[] = positions.map((p) => ({ ticker: p.ticker, name: p.name, position: p, lots: byTicker.get(p.ticker) ?? [] }));
  // Holdings that couldn't be priced still need to show up, so they can be deleted.
  for (const [ticker, lots] of byTicker) if (!positions.some((p) => p.ticker === ticker)) out.push({ ticker, name: "Couldn't be priced", position: null, lots });
  return out;
}

const fmtDate = (iso: string) => localDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

function Lot({ lot }: { lot: Holding }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    const err = await send(`holdings/${lot.id}`, "DELETE");
    setBusy(false);
    if (err) return setError(err);
    router.refresh();
  }

  const what = lot.shares != null ? `${lot.shares} shares` : `${money(lot.amount ?? 0)} worth`;
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
      <span>
        {what}, bought {fmtDate(lot.purchase_date)}
        {lot.source !== "manual" && <span className="text-ink-muted"> (added {lot.source === "csv" ? "by import" : "in chat"})</span>}
      </span>
      {error ? (
        <span role="alert" className="text-sm text-fox">{error}</span>
      ) : confirming ? (
        <span className="flex items-center gap-3 text-sm">
          <span className="text-ink-muted">Delete this purchase?</span>
          <button type="button" disabled={busy} onClick={() => void remove()} className="cursor-pointer font-semibold text-fox hover:text-fox-dark">
            {busy ? "Deleting…" : "Delete"}
          </button>
          <button type="button" disabled={busy} onClick={() => setConfirming(false)} className="cursor-pointer text-ink-muted hover:text-ink">Cancel</button>
        </span>
      ) : (
        <button type="button" onClick={() => setConfirming(true)} className="cursor-pointer text-sm text-ink-muted hover:text-fox">Delete</button>
      )}
    </li>
  );
}

export function HoldingsTable({ positions, holdings }: { positions: Position[]; holdings: Holding[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const list = rows(positions, holdings);
  if (list.length === 0) return <p className="text-ink-muted">No holdings yet. Add your first one below, or import a CSV.</p>;

  const th = "py-2.5 pr-4 text-left text-[13px] font-medium text-ink-muted";
  const num = "py-3 pr-4 text-right";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-[15px]">
        <thead>
          <tr className="border-b border-rule-strong">
            <th scope="col" className={th}>Holding</th>
            <th scope="col" className={`${th} text-right`}>Shares</th>
            <th scope="col" className={`${th} text-right`}>Value</th>
            <th scope="col" className={`${th} text-right`}>Cost</th>
            <th scope="col" className={`${th} text-right`}>Return</th>
            <th scope="col" className={`${th} text-right`}>Today</th>
            <th scope="col" className={`${th} pr-0 text-right`}>Share</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => {
            const p = r.position;
            const isOpen = open === r.ticker;
            return (
              <Fragment key={r.ticker}>
                <tr className="border-b border-rule">
                  <td className="py-3 pr-4">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? null : r.ticker)}
                      className="flex cursor-pointer items-center gap-2 text-left"
                    >
                      <ChevronRight className={`size-4 shrink-0 text-ink-muted transition-transform ${isOpen ? "rotate-90" : ""}`} aria-hidden="true" />
                      <span>
                        <span className="font-semibold">{r.ticker}</span>
                        <span className="block max-w-[16rem] truncate text-sm text-ink-muted">
                          {r.name}, {r.lots.length} {r.lots.length === 1 ? "purchase" : "purchases"}
                        </span>
                      </span>
                    </button>
                  </td>
                  <td className={num}>{p ? p.shares.toLocaleString("en-US", { maximumFractionDigits: 3 }) : ""}</td>
                  <td className={`${num} font-semibold`}>{p ? money(p.market_value) : ""}</td>
                  <td className={num}>{p ? money(p.cost_basis) : ""}</td>
                  <td className={`${num} ${moveColor(p?.total_return_pct)}`}>{p ? pct(p.total_return_pct) : ""}</td>
                  <td className={`${num} ${moveColor(p?.day_change_pct)}`}>{p ? pct(p.day_change_pct, { digits: 2 }) : ""}</td>
                  <td className={`${num} pr-0`}>{p ? `${p.weight_pct.toFixed(1)}%` : ""}</td>
                </tr>
                {isOpen && (
                  <tr className="border-b border-rule bg-paper-raised">
                    <td colSpan={7} className="px-8 py-1">
                      <ul className="divide-y divide-rule">
                        {r.lots.map((l) => <Lot key={l.id} lot={l} />)}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { errorMessage } from "@/lib/stream";
import { localDate, money, type History, type HistoryPoint } from "@/lib/today";

const RANGES = [
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
  { key: "1y", label: "1Y" },
  { key: "all", label: "All" },
] as const;

const SERIES = {
  portfolio: { name: "Your portfolio", stroke: "var(--color-ink)", width: 2.5, dash: undefined },
  benchmark: { name: "Same dollars in SPY", stroke: "#8A8384", width: 2, dash: "6 5" },
  invested: { name: "Money you put in", stroke: "#A39C9C", width: 1.5, dash: "2 4" },
} as const;
type Key = keyof typeof SERIES;

const shortMoney = (n: number) => (Math.abs(n) >= 1000 ? `$${Math.round(n / 1000)}k` : `$${Math.round(n)}`);

function Swatch({ k }: { k: Key }) {
  const s = SERIES[k];
  return (
    <svg width="22" height="8" aria-hidden="true">
      <line x1="0" y1="4" x2="22" y2="4" stroke={s.stroke} strokeWidth={s.width} strokeDasharray={s.dash} />
    </svg>
  );
}

function Readout({ active, payload }: { active?: boolean; payload?: { payload: HistoryPoint }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-rule-strong bg-paper-raised px-3 py-2 text-sm shadow-[0_8px_24px_rgba(34,30,31,0.10)]">
      <div className="mb-1 font-semibold">{localDate(p.date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</div>
      {(Object.keys(SERIES) as Key[]).map((k) => (
        <div key={k} className="flex items-center gap-2">
          <Swatch k={k} />
          <span className="text-ink-muted">{SERIES[k].name}</span>
          <span className="ml-auto pl-4 font-medium">{money(p[k])}</span>
        </div>
      ))}
    </div>
  );
}

export function ValueChart({ initial }: { initial: History }) {
  const [history, setHistory] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const points = history.points;
  const last = points[points.length - 1];
  const spanDays = points.length > 1 ? (localDate(last.date).getTime() - localDate(points[0].date).getTime()) / 864e5 : 0;
  const tickFormat = (iso: string) =>
    localDate(iso).toLocaleDateString("en-US", spanDays > 400 ? { month: "short", year: "2-digit" } : spanDays > 45 ? { month: "short" } : { month: "short", day: "numeric" });

  async function pick(range: string) {
    if (range === history.range || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/foxhood/portfolio/history?range=${range}`);
      if (!res.ok) return setError(await errorMessage(res));
      setHistory(await res.json());
    } catch {
      setError("Couldn't load that range. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section aria-labelledby="fx-history">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 id="fx-history" className="text-lg font-semibold">Value since you started</h2>
        <div role="group" aria-label="Time range" className="flex gap-0.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              aria-pressed={history.range === r.key}
              onClick={() => void pick(r.key)}
              className="min-h-9 cursor-pointer rounded-md px-3 text-sm text-ink-muted aria-pressed:bg-muted aria-pressed:font-semibold aria-pressed:text-ink"
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {points.length < 2 ? (
        <p className="py-16 text-ink-muted">Not enough history yet. Check back after your first full trading day.</p>
      ) : (
        <div className={`h-[260px] transition-opacity ${loading ? "opacity-50" : ""}`} aria-busy={loading}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--color-rule)" />
              <XAxis dataKey="date" tickFormatter={tickFormat} minTickGap={48} tickLine={false} axisLine={{ stroke: "var(--color-rule-strong)" }}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }} />
              <YAxis tickFormatter={shortMoney} width={48} tickLine={false} axisLine={false} domain={["auto", "auto"]}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }} />
              <Tooltip content={<Readout />} cursor={{ stroke: "var(--color-rule-strong)" }} />
              {(["invested", "benchmark", "portfolio"] as Key[]).map((k) => (
                <Line key={k} type="monotone" dataKey={k} name={SERIES[k].name} stroke={SERIES[k].stroke} strokeWidth={SERIES[k].width}
                  strokeDasharray={SERIES[k].dash} dot={false} activeDot={k === "portfolio" ? { r: 4 } : false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {error && <p role="alert" className="mt-2 text-fox">{error}</p>}
      {last && (
        <ul className="mt-3.5 flex flex-wrap gap-x-8 gap-y-2.5 text-[15px]">
          {(Object.keys(SERIES) as Key[]).map((k) => (
            <li key={k} className="flex items-center gap-2">
              <Swatch k={k} />
              {SERIES[k].name} <strong className="font-semibold">{money(last[k])}</strong>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

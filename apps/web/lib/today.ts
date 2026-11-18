// Types for the Today page (shapes match the API in apps/api/portfolio and app/routes) and the number formatting it uses.

export type Summary = {
  total_value: number;
  total_cost: number;
  day_pnl: number;
  day_change_pct: number | null;
  benchmark_day_change_pct: number | null;
  benchmark: string;
  total_return_pct: number;
  benchmark_total_return_pct: number;
  num_positions: number;
  largest_position: string;
  largest_weight_pct: number;
};

export type Position = {
  ticker: string;
  name: string;
  shares: number;
  price: number;
  cost_basis: number;
  total_return_pct: number;
  market_value: number;
  weight_pct: number;
  day_change_pct: number | null;
  day_pnl: number;
};

export type PortfolioView = {
  summary: Summary | null;
  positions: Position[];
  lot_errors: { holding_id: string; ticker: string; error: string }[];
};

export type Holding = { id: string; ticker: string; purchase_date: string; shares: number | null; amount: number | null; source: string };
export type WatchItem = { id: string; ticker: string; note: string | null };

export type Alert = { id: string; kind: "big_move" | "earnings_tomorrow" | "position_limit"; ticker: string; message: string };
export type Settings = { scheduled_briefs: boolean; email_briefs: boolean; email_alerts: boolean; max_position_pct: number | null };

export type HistoryPoint = { date: string; portfolio: number; benchmark: number; invested: number };
export type History = { range: string; benchmark: string; points: HistoryPoint[] };

export type Earning = {
  ticker: string;
  date: string;
  timing: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  status: "upcoming" | "reported";
};

export type Brief = { brief_date: string; session: string; content: string; created_at: string };
export type BriefPeek = { session: "premarket" | "close"; brief_date: string; trading_day_today: boolean; brief: Brief | null };

const MINUS = "−"; // a real minus sign, the same width as +

export function money(n: number, { signed = false, cents = false } = {}): string {
  const abs = Math.abs(n).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  });
  if (!signed) return n < 0 ? MINUS + abs : abs;
  return (n < 0 ? MINUS : "+") + abs;
}

export function pct(n: number | null | undefined, { signed = true, digits = 1 } = {}): string {
  if (n == null) return "n/a";
  const abs = Math.abs(n).toFixed(digits) + "%";
  if (!signed) return abs;
  return (n < 0 ? MINUS : n > 0 ? "+" : "") + abs;
}

// A calendar date like "2026-11-19" as a local date (new Date("2026-11-19") would be UTC midnight and can shift a day).
export function localDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function moveColor(n: number | null | undefined): string {
  if (n == null || Math.abs(n) < 0.005) return "text-ink";
  return n < 0 ? "text-down" : "text-up";
}

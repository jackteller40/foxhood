import { localDate, money, type Position, type Summary } from "@/lib/today";

// The sentence at the top of Today, written from the numbers (no AI call, so it's instant, free and never wrong).
// Example: "You're down $292 today, and NVDA did almost all of it. Since you started, you're up 59.9%, ahead of the S&P 500's 41.0%."

function whoDidIt(positions: Position[], dayPnl: number): string {
  if (positions.length < 2 || Math.abs(dayPnl) < 1) return "";
  const sameWay = positions.filter((p) => Math.sign(p.day_pnl) === Math.sign(dayPnl)).sort((a, b) => Math.abs(b.day_pnl) - Math.abs(a.day_pnl));
  const [first, second] = sameWay;
  const share = (n: number) => Math.abs(n) / Math.abs(dayPnl);
  if (first && share(first.day_pnl) >= 0.8) return `, and ${first.ticker} did almost all of it`;
  if (first && second && share(first.day_pnl + second.day_pnl) >= 0.7) return `, led by ${first.ticker} and ${second.ticker}`;
  if (first && share(first.day_pnl) >= 0.4) return `, led by ${first.ticker}`;
  if (sameWay.length >= positions.length * 0.75) return `, with most of your holdings ${dayPnl < 0 ? "down" : "up"}`;
  return "";
}

function dayPart(s: Summary, positions: Position[], tradingDayToday: boolean, lastSession: string): string {
  const pctMove = s.day_change_pct ?? 0;
  const flat = Math.abs(pctMove) < 0.05;
  const amount = money(Math.abs(s.day_pnl));
  const dir = s.day_pnl < 0 ? "down" : "up";
  if (tradingDayToday) {
    return flat ? "You're about flat today" : `You're ${dir} ${amount} today${whoDidIt(positions, s.day_pnl)}`;
  }
  const day = localDate(lastSession).toLocaleDateString("en-US", { weekday: "long" });
  return flat
    ? `Markets are closed today. On ${day} you finished about flat`
    : `Markets are closed today. On ${day} you finished ${dir} ${amount}${whoDidIt(positions, s.day_pnl)}`;
}

function sincePart(s: Summary): string {
  const mine = s.total_return_pct;
  const spy = s.benchmark_total_return_pct;
  const you = `${mine < 0 ? "down" : "up"} ${Math.abs(mine).toFixed(1)}%`;
  const theirs = `the S&P 500's ${spy < 0 ? "−" : ""}${Math.abs(spy).toFixed(1)}%`;
  if (Math.abs(mine - spy) < 0.5) return `Since you started, you're ${you}, about even with ${theirs}.`;
  return `Since you started, you're ${you}, ${mine > spy ? "ahead of" : "behind"} ${theirs}.`;
}

export function verdict(s: Summary, positions: Position[], tradingDayToday: boolean, lastSession: string): string {
  return `${dayPart(s, positions, tradingDayToday, lastSession)}. ${sincePart(s)}`;
}

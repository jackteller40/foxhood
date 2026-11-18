import Link from "next/link";
import { Alerts } from "@/components/today/alerts";
import { AskBar } from "@/components/today/ask-bar";
import { BriefSection } from "@/components/today/brief-section";
import { ComingUp } from "@/components/today/coming-up";
import { Treemap, TreemapLegend } from "@/components/today/treemap";
import { ValueChart } from "@/components/today/value-chart";
import { apiFetch } from "@/lib/api";
import { moveColor, money, pct, type Alert, type BriefPeek, type Earning, type History, type PortfolioView } from "@/lib/today";
import { verdict } from "@/lib/verdict";

type Loaded<T> = { data: T | null; status: number | null }; // status null: the API couldn't be reached

async function get<T>(path: string): Promise<Loaded<T>> {
  try {
    const res = await apiFetch(path);
    return { data: res.ok ? ((await res.json()) as T) : null, status: res.status };
  } catch {
    return { data: null, status: null };
  }
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10">
      <h1 className="text-3xl font-semibold tracking-tight">Today</h1>
      <div className="mt-4 max-w-[38em] text-lg text-ink-muted">{children}</div>
    </main>
  );
}

export default async function Today() {
  const [portfolio, history, earnings, brief, alerts] = await Promise.all([
    get<PortfolioView>("/portfolio"),
    get<History>("/portfolio/history?range=1y"),
    get<{ earnings: Earning[] }>("/earnings/upcoming"),
    get<BriefPeek>("/briefs/today"),
    get<Alert[]>("/alerts"),
  ]);

  if (portfolio.status === null) return <Notice>Can&apos;t reach the Foxhood API. If you&apos;re running it locally, is uvicorn running on port 8000?</Notice>;
  if (portfolio.status === 503) return <Notice>Market data is unavailable right now. Try again in a few minutes.</Notice>;
  if (!portfolio.data) return <Notice>Something went wrong loading your portfolio (error {portfolio.status}).</Notice>;

  const { summary, positions, lot_errors } = portfolio.data;
  if (!summary) {
    return (
      <Notice>
        <p>Nothing to show yet. Add your first holding and this page fills in with how it&apos;s doing.</p>
        <p className="mt-3">
          For now, the quickest way is to{" "}
          <Link href={`/chat?q=${encodeURIComponent("I bought 10 shares of AAPL on March 3, 2025")}`} className="font-semibold text-fox hover:text-fox-dark">
            tell Foxhood what you bought
          </Link>
          .
        </p>
      </Notice>
    );
  }

  const peek = brief.data;
  const tradingDay = peek?.trading_day_today ?? true;
  const sentence = verdict(summary, positions, tradingDay, peek?.brief_date ?? "");
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "America/New_York" });

  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 md:px-10">
      <Alerts initial={alerts.data ?? []} />
      <section aria-labelledby="fx-verdict" className="mt-8 flex flex-wrap items-end gap-x-16 gap-y-8 md:mt-12">
        <div className="min-w-0 flex-[999_1_560px]">
          <p className="mb-3 text-[15px] text-ink-muted">{today}</p>
          <h1 id="fx-verdict" className="max-w-[21em] text-[28px] leading-[1.18] font-semibold tracking-tight md:text-[44px] md:leading-[1.14]">
            {sentence}
          </h1>
        </div>
        <dl className="grid flex-[1_1_240px] gap-3 md:gap-4">
          {[
            ["Portfolio value", <>{money(summary.total_value)}</>, "text-ink"],
            [tradingDay ? "Today" : "Last session",
              <>{money(summary.day_pnl, { signed: true })} <span className="text-base font-medium">{pct(summary.day_change_pct, { digits: 2 })}</span></>,
              moveColor(summary.day_pnl)],
            ["S&P 500", <>{pct(summary.benchmark_day_change_pct, { digits: 2 })}</>, moveColor(summary.benchmark_day_change_pct)],
          ].map(([label, value, color], i) => (
            <div key={i} className="flex items-baseline justify-between gap-4 border-b border-rule pb-3 last:border-0 last:pb-0">
              <dt className="text-[15px] text-ink-muted">{label}</dt>
              <dd className={`text-[22px] font-semibold md:text-[26px] ${color}`}>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="fx-holdings" className="mt-12 md:mt-14">
        <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="fx-holdings" className="text-lg font-semibold">{tradingDay ? "Your holdings today" : "Your holdings, last session"}</h2>
          <TreemapLegend />
        </div>
        <Treemap positions={positions} />
        {lot_errors.length > 0 && (
          <p className="mt-3 text-[15px] text-ink-muted">
            Left out because they couldn&apos;t be priced: {lot_errors.map((e) => e.ticker).join(", ")}.
          </p>
        )}
      </section>

      <div className="mt-12 flex flex-wrap gap-x-16 gap-y-12 pb-8 md:mt-14">
        <div className="min-w-0 flex-[999_1_560px]">
          {history.data ? <ValueChart initial={history.data} /> : <p className="text-ink-muted">The value chart is unavailable right now.</p>}
        </div>
        <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-10">
          <ComingUp earnings={earnings.data?.earnings ?? []} largest={summary.largest_position} failed={!earnings.data} />
          <BriefSection peek={peek} />
        </div>
      </div>

      <AskBar />
      <footer className="pt-7 pb-8 text-[13px] text-ink-muted">
        Prices from Tiingo, quotes and earnings from Finnhub, economic data from FRED. Not financial advice.
      </footer>
    </main>
  );
}

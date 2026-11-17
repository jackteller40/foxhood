import { AddHolding } from "@/components/portfolio/add-holding";
import { CsvImport } from "@/components/portfolio/csv-import";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { Watchlist } from "@/components/portfolio/watchlist";
import { apiFetch } from "@/lib/api";
import { money, moveColor, pct, type Holding, type PortfolioView, type WatchItem } from "@/lib/today";

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(path);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export default async function PortfolioPage() {
  const [view, holdings, watchlist] = await Promise.all([
    get<PortfolioView>("/portfolio"),
    get<Holding[]>("/holdings"),
    get<WatchItem[]>("/watchlist"),
  ]);
  const s = view?.summary;

  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10">
      <div className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Portfolio</h1>
        {s && (
          <p className="text-[15px] text-ink-muted">
            {money(s.total_value)} across {s.num_positions} {s.num_positions === 1 ? "holding" : "holdings"},{" "}
            <span className={moveColor(s.total_return_pct)}>{pct(s.total_return_pct)}</span> since you started
          </p>
        )}
      </div>

      <section aria-labelledby="p-holdings" className="mt-8">
        <h2 id="p-holdings" className="sr-only">Holdings</h2>
        {holdings === null ? (
          <p role="alert" className="text-fox">Couldn&apos;t load your holdings. Is the API running?</p>
        ) : (
          <>
            {view === null && holdings.length > 0 && (
              <p className="mb-3 text-ink-muted">Live prices are unavailable right now, so values are missing.</p>
            )}
            <HoldingsTable positions={view?.positions ?? []} holdings={holdings} />
          </>
        )}
      </section>

      <section aria-labelledby="p-add" className="mt-14">
        <h2 id="p-add" className="mb-4 text-lg font-semibold">Add a holding</h2>
        <AddHolding />
      </section>

      <section aria-labelledby="p-import" className="mt-14">
        <h2 id="p-import" className="mb-2 text-lg font-semibold">Import from a CSV</h2>
        <CsvImport />
      </section>

      <section aria-labelledby="p-watch" className="mt-14">
        <h2 id="p-watch" className="mb-4 text-lg font-semibold">Watchlist</h2>
        <Watchlist items={watchlist ?? []} />
      </section>
    </main>
  );
}

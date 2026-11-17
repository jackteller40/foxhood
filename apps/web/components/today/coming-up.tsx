import { localDate, type Earning } from "@/lib/today";

const TIMING: Record<string, string> = {
  "before market open": " before the open",
  "after market close": " after the close",
  "during market hours": " during the trading day",
};
const eps = (n: number) => `$${n.toFixed(2)} a share`;

function describe(e: Earning, largest: string | null): { lead: string; rest: string } {
  const when = TIMING[e.timing] ?? "";
  if (e.status === "reported") {
    const rest = e.eps_actual != null && e.eps_estimate != null
      ? `${eps(e.eps_actual)} against ${eps(e.eps_estimate).replace(" a share", "")} expected.`
      : e.eps_actual != null ? `${eps(e.eps_actual)}.` : "";
    return { lead: `${e.ticker} reported${when}.`, rest };
  }
  const parts = [
    e.eps_estimate != null ? `Analysts expect ${eps(e.eps_estimate)}.` : "",
    when ? "" : "Time not announced yet.",
    e.ticker === largest ? "It's your largest position." : "",
  ];
  return { lead: `${e.ticker} reports${when}.`, rest: parts.filter(Boolean).join(" ") };
}

export function ComingUp({ earnings, largest, failed }: { earnings: Earning[]; largest: string | null; failed: boolean }) {
  const rows = earnings.slice(0, 5);
  return (
    <section aria-labelledby="fx-coming">
      <h2 id="fx-coming" className="mb-3 text-lg font-semibold">Coming up</h2>
      {failed ? (
        <p className="text-ink-muted">Earnings dates are unavailable right now.</p>
      ) : rows.length === 0 ? (
        <p className="text-ink-muted">No earnings from your holdings or watchlist in the next two weeks.</p>
      ) : (
        <ul>
          {rows.map((e) => {
            const d = localDate(e.date);
            const { lead, rest } = describe(e, largest);
            return (
              <li key={`${e.ticker}-${e.date}`} className="grid grid-cols-[64px_minmax(0,1fr)] gap-4 border-t border-rule py-3.5 last:border-b md:grid-cols-[76px_minmax(0,1fr)]">
                <div className="font-semibold">
                  {d.toLocaleDateString("en-US", { weekday: "short" })}
                  <div className="font-normal text-ink-muted">{d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>
                </div>
                <p>
                  <strong className="font-semibold">{lead}</strong> {rest}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

import Link from "next/link";
import { apiFetch } from "@/lib/api";

type Me = {
  email: string;
  name: string | null;
  profile: { persona: string | null; risk_tolerance: string; interests: string[] };
};
type Holding = { id: string; ticker: string; purchase_date: string; shares: number | null; amount: number | null };

async function load(): Promise<{ me: Me | null; holdings: Holding[]; problem: string | null }> {
  try {
    const [meRes, hRes] = await Promise.all([apiFetch("/me"), apiFetch("/holdings")]);
    if (!meRes.ok) return { me: null, holdings: [], problem: `The API returned ${meRes.status}.` };
    return { me: await meRes.json(), holdings: hRes.ok ? await hRes.json() : [], problem: null };
  } catch {
    return { me: null, holdings: [], problem: "Can't reach the API. Is uvicorn running on port 8000?" };
  }
}

// Temporary: the real Today page (verdict, treemap, value chart, brief) arrives in chunk C.
export default async function Dashboard() {
  const { me, holdings, problem } = await load();

  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10">
      <h1 className="text-3xl font-semibold tracking-tight">Today</h1>
      {problem ? (
        <p role="alert" className="mt-4 text-fox">{problem}</p>
      ) : (
        me && (
          <>
            <p className="mt-3 text-ink-muted">
              Signed in as {me.name ?? me.email}. Risk tolerance: {me.profile.risk_tolerance}.
            </p>
            <h2 className="mt-10 text-lg font-semibold">Holdings</h2>
            {holdings.length === 0 ? (
              <p className="mt-2 text-ink-muted">No holdings yet.</p>
            ) : (
              <ul className="mt-3 max-w-xl">
                {holdings.map((h) => (
                  <li key={h.id} className="flex justify-between border-t border-rule py-3 last:border-b">
                    <span className="font-semibold">{h.ticker}</span>
                    <span className="text-ink-muted">
                      {h.shares !== null ? `${h.shares} shares` : `$${h.amount?.toLocaleString()}`}, bought {h.purchase_date}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Link href="/chat" className="mt-8 inline-block font-semibold text-fox hover:text-fox-dark">
              Ask Foxhood about your portfolio
            </Link>
          </>
        )
      )}
    </main>
  );
}

import { notFound } from "next/navigation";
import { type Person, People } from "@/components/admin/people";
import { apiFetch } from "@/lib/api";

type Overview = { spent_today_usd: number; cap_total_usd: number; cap_user_usd: number; people: Person[] };
type RunRow = {
  run_id: string; email: string | null; task: string | null; status: string | null; started_at: string;
  seconds: number | null; tool_calls: number; errors: number; denials: number; cost_usd: number;
};
type JobRow = { job: string; started_at: string; finished_at: string | null; ok: boolean | null; summary: Record<string, unknown> };

async function get<T>(path: string): Promise<{ data: T | null; status: number }> {
  try {
    const res = await apiFetch(path);
    return { data: res.ok ? ((await res.json()) as T) : null, status: res.status };
  } catch {
    return { data: null, status: 0 };
  }
}

const time = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });

const TASKS: Record<string, string> = { chat: "Chat", "brief:premarket": "Morning brief", "brief:close": "Close recap" };

function jobSummary(j: JobRow): string {
  const s = j.summary ?? {};
  if (typeof s.error === "string") return `Crashed (${s.error})`;
  if (s.ran === false) return String(s.reason ?? "Skipped");
  const counts = (s.outcomes ?? {}) as Record<string, number>;
  const parts = Object.entries(counts).map(([k, v]) => `${v} ${k}`);
  if (typeof s.alerts_added === "number") parts.push(`${s.alerts_added} new alerts`);
  if (typeof s.emailed === "number" && s.emailed) parts.push(`${s.emailed} emailed`);
  return parts.join(", ") || "Nothing to do";
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-4 text-lg font-semibold">{children}</h2>;
}

export default async function AdminPage() {
  const [overview, runs, jobs] = await Promise.all([get<Overview>("/admin/overview"), get<RunRow[]>("/admin/runs"), get<JobRow[]>("/admin/jobs")]);
  if (overview.status === 403) notFound(); // not an admin: the page doesn't exist for them
  if (!overview.data) {
    return <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10"><p role="alert" className="text-fox">Couldn&apos;t load the admin data.</p></main>;
  }
  const o = overview.data;
  const share = Math.min(o.spent_today_usd / o.cap_total_usd, 1);

  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10">
      <h1 className="text-3xl font-semibold tracking-tight">Admin</h1>
      <p className="mt-2 max-w-[44em] text-ink-muted">
        Who has access, how much AI everyone used, and how runs and scheduled jobs went. Nothing here shows what anyone asked or owns.
      </p>

      <section aria-labelledby="a-spend" className="mt-10 max-w-md">
        <H2><span id="a-spend">AI spend today</span></H2>
        <p><span className="text-[22px] font-semibold">${o.spent_today_usd.toFixed(3)}</span> <span className="text-ink-muted">of the ${o.cap_total_usd.toFixed(2)} shared daily cap (${o.cap_user_usd.toFixed(2)} per person)</span></p>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Share of the daily cap used"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}>
          <div className={`h-full rounded-full ${share >= 0.8 ? "bg-fox" : "bg-ink"}`} style={{ width: `${share * 100}%` }} />
        </div>
      </section>

      <section aria-labelledby="a-people" className="mt-12">
        <H2><span id="a-people">People</span></H2>
        <People people={o.people} />
      </section>

      <section aria-labelledby="a-jobs" className="mt-12">
        <H2><span id="a-jobs">Scheduled jobs</span></H2>
        {!jobs.data?.length ? (
          <p className="text-ink-muted">No job runs yet. The first morning brief run is 8:30 a.m. ET on the next trading day.</p>
        ) : (
          <ul className="max-w-3xl">
            {jobs.data.slice(0, 12).map((j, i) => (
              <li key={i} className="grid grid-cols-[110px_120px_minmax(0,1fr)] gap-4 border-t border-rule py-2.5 text-[15px] last:border-b">
                <span className="font-medium">{j.job === "briefs" ? "Morning briefs" : "Alerts"}</span>
                <span className="text-ink-muted">{time(j.started_at)}</span>
                <span className={j.ok === false ? "text-fox" : ""}>{j.ok === null ? "Running or interrupted" : jobSummary(j)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="a-runs" className="mt-12 pb-10">
        <H2><span id="a-runs">Recent agent runs</span></H2>
        {!runs.data?.length ? (
          <p className="text-ink-muted">No runs yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-[15px]">
              <thead>
                <tr className="border-b border-rule-strong text-left text-[13px] text-ink-muted">
                  <th scope="col" className="py-2 pr-4 font-medium">When</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Who</th>
                  <th scope="col" className="py-2 pr-4 font-medium">What</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Result</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Tools</th>
                  <th scope="col" className="py-2 pr-4 text-right font-medium">Time</th>
                  <th scope="col" className="py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => {
                  const failed = r.status === "error" || r.errors > 0;
                  return (
                    <tr key={r.run_id} className="border-b border-rule">
                      <td className="py-2 pr-4 text-ink-muted">{time(r.started_at)}</td>
                      <td className="max-w-[16rem] truncate py-2 pr-4">{r.email ?? "unknown"}</td>
                      <td className="py-2 pr-4">{TASKS[r.task ?? ""] ?? r.task ?? "?"}</td>
                      <td className={`py-2 pr-4 ${failed ? "font-semibold text-fox" : ""}`}>
                        {r.status === "paused" ? "Waiting for approval" : failed ? `${r.errors} error${r.errors === 1 ? "" : "s"}` : "OK"}
                        {r.denials > 0 && <span className="font-normal text-ink-muted">, {r.denials} blocked</span>}
                      </td>
                      <td className="py-2 pr-4 text-right">{r.tool_calls}</td>
                      <td className="py-2 pr-4 text-right">{r.seconds != null ? `${r.seconds.toFixed(0)}s` : ""}</td>
                      <td className="py-2 text-right">${r.cost_usd.toFixed(3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

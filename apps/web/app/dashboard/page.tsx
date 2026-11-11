import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Me = {
  email: string;
  name: string | null;
  profile: { persona: string | null; risk_tolerance: string; interests: string[] };
};
type Holding = { id: string; ticker: string; purchase_date: string; shares: number | null; amount: number | null };

async function load(): Promise<{ me: Me | null; holdings: Holding[]; problem: string | null }> {
  try {
    const [meRes, hRes] = await Promise.all([apiFetch("/me"), apiFetch("/holdings")]);
    if (!meRes.ok) return { me: null, holdings: [], problem: `API returned ${meRes.status}` };
    return { me: await meRes.json(), holdings: hRes.ok ? await hRes.json() : [], problem: null };
  } catch {
    return { me: null, holdings: [], problem: "API unreachable. Is uvicorn running on port 8000?" };
  }
}

export default async function Dashboard() {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { me, holdings, problem } = await load();

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/" });
          }}
        >
          <Button type="submit" variant="outline">Sign out</Button>
        </form>
      </div>

      {problem ? (
        <p className="text-red-600">{problem}</p>
      ) : (
        me && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>{me.name ?? me.email}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <p>{me.email}</p>
                <p>
                  Risk: {me.profile.risk_tolerance}
                  {me.profile.persona ? ` · ${me.profile.persona}` : ""}
                </p>
                {me.profile.interests.length > 0 && <p>Interests: {me.profile.interests.join(", ")}</p>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Holdings ({holdings.length})</CardTitle>
              </CardHeader>
              <CardContent>
                {holdings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No holdings yet.</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {holdings.map((h) => (
                      <li key={h.id} className="flex justify-between">
                        <span className="font-medium">{h.ticker}</span>
                        <span className="text-muted-foreground">
                          {h.shares !== null ? `${h.shares} shares` : `$${h.amount?.toLocaleString()}`} · bought {h.purchase_date}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )
      )}
    </main>
  );
}
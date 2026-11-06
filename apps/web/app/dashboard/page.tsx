import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Me = { email: string; name: string | null };

async function loadMe(): Promise<{ me: Me | null; problem: string | null }> {
  try {
    const res = await apiFetch("/me");
    return res.ok ? { me: await res.json(), problem: null } : { me: null, problem: `API returned ${res.status}` };
  } catch {
    return { me: null, problem: "API unreachable. Is uvicorn running on port 8000?" };
  }
}

export default async function Dashboard() {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { me, problem } = await loadMe();

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
      <Card>
        <CardHeader>
          <CardTitle>API connection</CardTitle>
        </CardHeader>
        <CardContent>
          {me ? (
            <p>
              Signed in as <strong>{me.name ?? me.email}</strong> ({me.email}), verified by the API.
            </p>
          ) : (
            <p className="text-red-600">{problem}</p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
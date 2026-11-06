import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Button } from "@/components/ui/button";

export default async function Home({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  if (await auth()) redirect("/dashboard");
  const { error } = await searchParams;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-semibold tracking-tight">Foxhood</h1>
      <p className="max-w-md text-center text-muted-foreground">
        Personal market research, written for your portfolio.
      </p>
      {error === "AccessDenied" && (
        <p className="text-sm text-red-600">That account isn&apos;t on the invite list.</p>
      )}
      <form
        action={async () => {
          "use server";
          await signIn("google", { redirectTo: "/dashboard" });
        }}
      >
        <Button type="submit" size="lg">Sign in with Google</Button>
      </form>
    </main>
  );
}
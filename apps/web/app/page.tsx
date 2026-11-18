import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Wordmark } from "@/components/fox-mark";
import { Button } from "@/components/ui/button";

export default async function Home({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  if (await auth()) redirect("/dashboard");
  const { error } = await searchParams;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[1200px] flex-col px-5 py-8 md:px-10">
      <Wordmark size={26} />
      <div className="my-auto max-w-[36rem] py-16">
        <h1 className="text-4xl leading-tight font-semibold tracking-tight md:text-5xl">
          Market research, written for your portfolio.
        </h1>
        <p className="mt-4 text-lg text-ink-muted">
          Foxhood is invite-only. Sign in with the Google account you were invited with.
        </p>
        {error === "AccessDenied" && (
          <p role="alert" className="mt-4 text-fox">That Google account isn&apos;t on the invite list.</p>
        )}
        <form
          className="mt-8"
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: "/dashboard" });
          }}
        >
          <Button type="submit" className="h-11 px-5 text-[15px] font-semibold">Sign in with Google</Button>
        </form>
      </div>
      <p className="text-[13px] text-ink-muted">
        Not financial advice. <a href="/privacy" className="underline underline-offset-2 hover:text-ink">Privacy</a>
      </p>
    </main>
  );
}

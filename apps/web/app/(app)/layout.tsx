import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { AccountMenu, DesktopNav, MobileNav } from "@/components/app-nav";
import { Wordmark } from "@/components/fox-mark";
import { signOutAction } from "./actions";

function initialsOf(name: string) {
  const parts = name.split(/[\s@.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

// Every signed-in page: header on top, the page in the middle, tab bar at the bottom on phones.
export default async function AppLayout({ children }: LayoutProps<"/">) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const name = session.user.name ?? session.user.email ?? "Account";

  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <header className="border-b border-rule md:border-0">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-8 px-5 md:px-10 md:pt-3">
          <div className="flex items-center gap-10">
            <Link href="/dashboard" aria-label="Foxhood, today">
              <Wordmark size={26} />
            </Link>
            <DesktopNav />
          </div>
          <AccountMenu name={name} initials={initialsOf(name)} signOutAction={signOutAction} />
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
      <MobileNav />
    </div>
  );
}

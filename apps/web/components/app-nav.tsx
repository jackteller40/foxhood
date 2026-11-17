"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "@base-ui/react/menu";

const LINKS = [
  { href: "/dashboard", label: "Today" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
] as const;

function useIsCurrent() {
  const path = usePathname();
  return (href: string) => path === href || path.startsWith(`${href}/`);
}

// Top nav for wider screens. The current page gets a red underline.
export function DesktopNav() {
  const isCurrent = useIsCurrent();
  return (
    <nav aria-label="Main" className="hidden gap-7 text-[15px] font-medium md:flex">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          aria-current={isCurrent(l.href) ? "page" : undefined}
          className="border-b-2 border-transparent py-2.5 text-ink-muted hover:text-ink aria-[current=page]:border-fox aria-[current=page]:text-ink"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

// Bottom tab bar for phones.
export function MobileNav() {
  const isCurrent = useIsCurrent();
  return (
    <nav
      aria-label="Main"
      className="grid grid-cols-4 border-t border-rule bg-paper pb-[env(safe-area-inset-bottom)] text-[13px] font-medium md:hidden"
    >
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          aria-current={isCurrent(l.href) ? "page" : undefined}
          className="py-3 text-center text-ink-muted aria-[current=page]:font-bold aria-[current=page]:text-ink"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

// The initials button and its menu.
export function AccountMenu({ name, initials, signOutAction }: { name: string; initials: string; signOutAction: () => Promise<void> }) {
  const item = "flex w-full cursor-pointer rounded-md px-3 py-2 text-left text-sm outline-none data-[highlighted]:bg-muted";
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`Account: ${name}`}
        className="size-10 shrink-0 cursor-pointer rounded-full border border-rule-strong bg-paper-raised text-sm font-semibold text-fox"
      >
        {initials}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="end" sideOffset={8}>
          <Menu.Popup className="min-w-48 rounded-lg border border-rule-strong bg-paper-raised p-1 text-ink shadow-[0_8px_24px_rgba(34,30,31,0.10)] outline-none">
            <p className="truncate px-3 pt-2 pb-1 text-sm text-ink-muted">{name}</p>
            <Menu.LinkItem render={<Link href="/settings" />} closeOnClick className={item}>
              Settings
            </Menu.LinkItem>
            <Menu.Item className={item} onClick={() => void signOutAction()}>
              Sign out
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

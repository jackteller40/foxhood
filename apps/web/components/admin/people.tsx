"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";

export type Person = {
  email: string;
  status: "active" | "invited" | "revoked" | "no invite";
  is_admin: boolean;
  last_login_at: string | null;
  holdings: number;
  spent_today_usd: number;
};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" }) : "never";

function Revoke({ email }: { email: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (error) return <span role="alert" className="text-sm text-fox">{error}</span>;
  if (!confirming) {
    return <button type="button" onClick={() => setConfirming(true)} className="cursor-pointer text-sm text-ink-muted hover:text-fox">Revoke</button>;
  }
  return (
    <span className="flex items-center gap-3 text-sm">
      <button type="button" className="cursor-pointer font-semibold text-fox hover:text-fox-dark"
        onClick={async () => {
          const err = await send("admin/invites/revoke", "POST", { email });
          if (err) return setError(err);
          router.refresh();
        }}>
        Revoke access
      </button>
      <button type="button" onClick={() => setConfirming(false)} className="cursor-pointer text-ink-muted hover:text-ink">Cancel</button>
    </span>
  );
}

export function People({ people }: { people: Person[] }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setMsg(null);
    const err = await send("admin/invites", "POST", { email: email.trim() });
    setBusy(false);
    if (err) return setMsg({ ok: false, text: err });
    setMsg({ ok: true, text: `Invited ${email.trim()}. They can sign in with that Google account now.` });
    setEmail("");
    router.refresh();
  }

  return (
    <div>
      <form onSubmit={invite} className="flex max-w-md gap-2">
        <label htmlFor="invite-email" className="sr-only">Email to invite</label>
        <input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="friend@gmail.com" autoComplete="off" className={inputClass} />
        <Button type="submit" disabled={busy || !email.trim()} className="h-10 px-4 font-semibold">{busy ? "Inviting…" : "Invite"}</Button>
      </form>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-2 ${msg.ok ? "text-up" : "text-fox"}`}>{msg.text}</p>}

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-[15px]">
          <thead>
            <tr className="border-b border-rule-strong text-left text-[13px] text-ink-muted">
              <th scope="col" className="py-2 pr-4 font-medium">Person</th>
              <th scope="col" className="py-2 pr-4 font-medium">Status</th>
              <th scope="col" className="py-2 pr-4 font-medium">Last sign-in</th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">Holdings</th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">AI today</th>
              <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.email} className="border-b border-rule">
                <td className="py-2.5 pr-4">{p.email}{p.is_admin && <span className="text-ink-muted"> (you, admin)</span>}</td>
                <td className={`py-2.5 pr-4 ${p.status === "revoked" ? "text-ink-muted" : ""}`}>
                  {{ active: "Active", invited: "Invited, not signed in yet", revoked: "Revoked", "no invite": "No invite" }[p.status]}
                </td>
                <td className="py-2.5 pr-4">{when(p.last_login_at)}</td>
                <td className="py-2.5 pr-4 text-right">{p.holdings}</td>
                <td className="py-2.5 pr-4 text-right">${p.spent_today_usd.toFixed(3)}</td>
                <td className="py-2.5 text-right">{!p.is_admin && (p.status === "active" || p.status === "invited") && <Revoke email={p.email} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

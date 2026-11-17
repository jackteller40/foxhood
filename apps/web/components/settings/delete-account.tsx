"use client";

import { useState } from "react";
import { inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";

export function DeleteAccount({ signOutAction }: { signOutAction: () => Promise<void> }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = typed.trim().toLowerCase() === "delete";

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    const err = await send("me", "DELETE", { confirm: "DELETE" });
    if (err) {
      setBusy(false);
      return setError(err);
    }
    await signOutAction();
  }

  return (
    <form onSubmit={remove} className="max-w-2xl">
      <p className="text-ink-muted">
        Permanently erases your holdings, watchlist, chats, briefs and saved notes. This can&apos;t be undone, so download your data
        first if you want a copy.
      </p>
      <label htmlFor="d-confirm" className="mt-4 block text-[15px] font-medium">Type “delete” to confirm</label>
      <div className="mt-1.5 flex max-w-sm gap-2">
        <input id="d-confirm" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className={inputClass} />
        <Button type="submit" variant="destructive" disabled={!ready || busy} className="h-10 px-4 font-semibold">
          {busy ? "Deleting…" : "Delete account"}
        </Button>
      </div>
      {error && <p role="alert" className="mt-2 text-fox">{error}</p>}
    </form>
  );
}

"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { send } from "@/components/field";
import type { Alert } from "@/lib/today";

// Today's alerts (big moves, earnings tomorrow, over your position limit). Dismissing hides one for the day.
export function Alerts({ initial }: { initial: Alert[] }) {
  const [alerts, setAlerts] = useState(initial);
  if (alerts.length === 0) return null;

  async function dismiss(id: string) {
    setAlerts((a) => a.filter((x) => x.id !== id)); // hide right away; it's only a dismissal
    await send(`alerts/${id}/dismiss`, "POST");
  }

  return (
    <section aria-label="Alerts" className="mt-6">
      <ul className="flex flex-col gap-2">
        {alerts.map((a) => (
          <li key={a.id} className="flex items-start gap-3 rounded-lg border-l-[3px] border-fox bg-paper-raised py-2.5 pr-2 pl-4">
            <p className="flex-1 py-0.5">{a.message}</p>
            <button type="button" onClick={() => void dismiss(a.id)} aria-label={`Dismiss: ${a.message}`}
              className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-ink-muted hover:bg-muted hover:text-ink">
              <X className="size-4" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

"use client";

import { useState } from "react";
import { inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";
import type { Settings } from "@/lib/today";

// Morning brief on or off, and the position limit the alerts check against.
export function Automation({ initial, email }: { initial: Settings; email: string }) {
  const [s, setS] = useState(initial);
  const [limit, setLimit] = useState(initial.max_position_pct?.toString() ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(fields: Partial<Settings>, done: string) {
    setBusy(true);
    setMsg(null);
    const err = await send("me/settings", "PATCH", fields);
    setBusy(false);
    if (err) return setMsg({ ok: false, text: err });
    setS((cur) => ({ ...cur, ...fields }));
    setMsg({ ok: true, text: done });
  }

  const limitNumber = limit.trim() === "" ? null : Number(limit);
  const limitValid = limitNumber === null || (limitNumber >= 1 && limitNumber <= 100);

  return (
    <div className="grid max-w-2xl gap-6">
      {([
        ["scheduled_briefs", "Write my brief every trading morning",
          "Ready by about 8:30 a.m. ET, so Today opens with it. Counts toward your daily AI limit.",
          "Your brief will be ready each trading morning.", "Morning briefs turned off."],
        ["email_briefs", "Email me the morning brief", `Sent to ${email} when it's written.`,
          "You'll get the brief by email.", "Brief emails turned off."],
        ["email_alerts", "Email me alerts", "One email per check with anything new, at most once per stock per day.",
          "You'll get alerts by email.", "Alert emails turned off."],
      ] as const).map(([key, label, hint, on, off]) => (
        <label key={key} className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" checked={s[key]} disabled={busy || (key === "email_briefs" && !s.scheduled_briefs)}
            onChange={(e) => void save({ [key]: e.target.checked }, e.target.checked ? on : off)}
            className="mt-1 size-4 accent-fox" />
          <span>
            <span className="font-medium">{label}</span>
            <span className="block text-ink-muted">{hint}</span>
          </span>
        </label>
      ))}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (limitValid) void save({ max_position_pct: limitNumber },
            limitNumber === null ? "Position limit cleared." : `You'll get an alert when a holding goes over ${limitNumber}%.`);
        }}
      >
        <label htmlFor="a-limit" className="text-[15px] font-medium">Position limit</label>
        <p id="a-limit-hint" className="text-ink-muted">Get an alert when one holding grows past this share of your portfolio. Leave empty for no limit.</p>
        <div className="mt-2 flex max-w-xs items-center gap-2">
          <div className="relative flex-1">
            <input id="a-limit" type="number" inputMode="decimal" min={1} max={100} step="any" value={limit}
              onChange={(e) => setLimit(e.target.value)} placeholder="25" aria-describedby="a-limit-hint" aria-invalid={!limitValid}
              className={`${inputClass} pr-8`} />
            <span aria-hidden="true" className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-ink-muted">%</span>
          </div>
          <Button type="submit" variant="outline" disabled={busy || !limitValid} className="h-10 bg-paper-raised px-4">Save</Button>
        </div>
        {!limitValid && <p className="mt-1.5 text-sm text-fox">Use a number from 1 to 100.</p>}
      </form>

      <p className="text-ink-muted">
        Alerts also fire when a holding moves 5% or more in a day, or reports earnings on the next trading day. They show at the top of Today.
      </p>
      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-up" : "text-fox"}>{msg.text}</p>}
    </div>
  );
}

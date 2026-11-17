"use client";

import { useState } from "react";
import { Field, inputClass, send } from "@/components/field";
import { Button } from "@/components/ui/button";

export type Profile = { email: string; name: string | null; persona: string | null; risk_tolerance: string; horizon: string | null; interests: string[] };

export function ProfileForm({ profile }: { profile: Profile }) {
  const [name, setName] = useState(profile.name ?? "");
  const [risk, setRisk] = useState(profile.risk_tolerance);
  const [horizon, setHorizon] = useState(profile.horizon ?? "");
  const [persona, setPersona] = useState(profile.persona ?? "");
  const [interests, setInterests] = useState(profile.interests.join(", "));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const err = await send("me/profile", "PATCH", {
      name: name.trim() || null,
      risk_tolerance: risk,
      horizon: horizon.trim() || null,
      persona: persona.trim() || null,
      interests: interests.split(",").map((s) => s.trim()).filter(Boolean).slice(0, 20),
    });
    setBusy(false);
    setMsg(err ? { ok: false, text: err } : { ok: true, text: "Saved. Foxhood will use this from your next question." });
  }

  return (
    <form onSubmit={save} className="grid max-w-2xl gap-5">
      <p className="text-ink-muted">Signed in as {profile.email}. Foxhood reads this to tailor its answers and briefs.</p>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field id="p-name" label="Name">
          <input id="p-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} className={inputClass} />
        </Field>
        <Field id="p-risk" label="Risk tolerance">
          <select id="p-risk" value={risk} onChange={(e) => setRisk(e.target.value)} className={inputClass}>
            <option value="low">Low: protect what I have</option>
            <option value="medium">Medium: balanced</option>
            <option value="high">High: comfortable with big swings</option>
          </select>
        </Field>
        <Field id="p-horizon" label="Time horizon" hint="How long you plan to hold, e.g. “5+ years”.">
          <input id="p-horizon" value={horizon} onChange={(e) => setHorizon(e.target.value)} maxLength={100} className={inputClass} />
        </Field>
        <Field id="p-persona" label="Investing style" hint="A few words, e.g. “long-term tech investor”.">
          <input id="p-persona" value={persona} onChange={(e) => setPersona(e.target.value)} maxLength={100} className={inputClass} />
        </Field>
      </div>
      <Field id="p-interests" label="Interests" hint="Separate with commas, e.g. semiconductors, dividends, energy.">
        <input id="p-interests" value={interests} onChange={(e) => setInterests(e.target.value)} className={inputClass} />
      </Field>
      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" disabled={busy} className="h-10 px-4 font-semibold">{busy ? "Saving…" : "Save profile"}</Button>
        {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-up" : "text-fox"}>{msg.text}</p>}
      </div>
    </form>
  );
}

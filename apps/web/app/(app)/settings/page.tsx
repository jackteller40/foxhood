import { Automation } from "@/components/settings/automation";
import { DeleteAccount } from "@/components/settings/delete-account";
import { type Note, Notes } from "@/components/settings/notes";
import { type Profile, ProfileForm } from "@/components/settings/profile-form";
import { apiFetch } from "@/lib/api";
import type { Settings } from "@/lib/today";
import { signOutAction } from "../actions";

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(path);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="border-t border-rule pt-8 pb-10 first:border-0 first:pt-0">
      <h2 id={id} className="mb-4 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default async function SettingsPage() {
  const [profile, notes, usage, prefs] = await Promise.all([
    get<Profile>("/me/profile"),
    get<Note[]>("/memories"),
    get<{ spent_usd: number; cap_usd: number }>("/usage/today"),
    get<Settings>("/me/settings"),
  ]);

  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-10 md:px-10">
      <h1 className="mb-10 text-3xl font-semibold tracking-tight">Settings</h1>
      {!profile ? (
        <p role="alert" className="text-fox">Couldn&apos;t load your settings. Is the API running?</p>
      ) : (
        <>
          <Section id="s-profile" title="Profile">
            <ProfileForm profile={profile} />
          </Section>
          {prefs && (
            <Section id="s-auto" title="Briefs and alerts">
              <Automation initial={prefs} email={profile.email} />
            </Section>
          )}
          <Section id="s-notes" title="What Foxhood remembers">
            <Notes notes={notes ?? []} />
          </Section>
          <Section id="s-usage" title="Today’s usage">
            {usage ? (
              <div className="max-w-md">
                <p>
                  <span className="text-[22px] font-semibold">${usage.spent_usd.toFixed(3)}</span>{" "}
                  <span className="text-ink-muted">of your ${usage.cap_usd.toFixed(2)} daily limit</span>
                </p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Share of today's limit used"
                  aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(Math.min(usage.spent_usd / usage.cap_usd, 1) * 100)}>
                  <div className="h-full rounded-full bg-ink" style={{ width: `${Math.min(usage.spent_usd / usage.cap_usd, 1) * 100}%` }} />
                </div>
                <p className="mt-2 text-sm text-ink-muted">Resets at midnight Eastern. Chat and briefs both count toward it.</p>
              </div>
            ) : (
              <p className="text-ink-muted">Usage is unavailable right now.</p>
            )}
          </Section>
          <Section id="s-data" title="Your data">
            <p className="max-w-2xl text-ink-muted">Everything Foxhood stores about you, as one JSON file.</p>
            <a href="/api/foxhood/me/export" download="foxhood-export.json"
              className="mt-3 inline-flex h-10 items-center rounded-lg border border-rule-strong bg-paper-raised px-4 text-sm font-medium hover:bg-muted">
              Download my data
            </a>
          </Section>
          <Section id="s-delete" title="Delete account">
            <DeleteAccount signOutAction={signOutAction} />
          </Section>
        </>
      )}
    </main>
  );
}

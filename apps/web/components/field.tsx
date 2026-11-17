import { errorMessage } from "@/lib/stream";

// Shared form styling for Portfolio and Settings.
export const inputClass =
  "h-10 w-full min-w-0 rounded-lg border border-rule-strong bg-paper-raised px-3 text-base text-ink placeholder:text-ink-muted/70 aria-invalid:border-fox";

export function Field({ id, label, hint, error, children }: {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-[15px] font-medium">{label}</label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-fox">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-ink-muted">{hint}</p>
      ) : null}
    </div>
  );
}

// Sends a JSON request through the API proxy and returns an error message, or null if it worked.
export async function send(path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown): Promise<string | null> {
  try {
    const res = await fetch(`/api/foxhood/${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return res.ok ? null : await errorMessage(res);
  } catch {
    return "Couldn't reach Foxhood. Check your connection and try again.";
  }
}

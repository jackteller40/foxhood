// Browser -> this route -> FastAPI. Runs only on the Next.js server: it signs the short-lived API token
// for the signed-in user, so the browser never sees a token or the API's address. Streams pass through
// untouched (server-sent events from chat, approvals and briefs).
import type { NextRequest } from "next/server";
import { apiFetch } from "@/lib/api";

// Only these API paths are reachable from the browser through this proxy ("*" = one path segment).
const ALLOWED_PATHS = [
  "me", "me/profile", "me/settings", "me/export", "alerts", "alerts/*/dismiss",
  "portfolio", "portfolio/history", "earnings/upcoming",
  "holdings", "holdings/*", "holdings/import/preview", "holdings/import/commit",
  "watchlist", "watchlist/*", "memories", "memories/*",
  "chat", "threads", "threads/*", "threads/*/approve",
  "briefs", "briefs/today", "usage/today",
  "admin/overview", "admin/runs", "admin/jobs", "admin/invites", "admin/invites/revoke",
];
const ALLOWED = new RegExp(`^(${ALLOWED_PATHS.map((p) => p.replaceAll("*", "[^/]+")).join("|")})$`);

async function forward(req: NextRequest, ctx: RouteContext<"/api/foxhood/[...path]">) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (path.some((seg) => seg === "." || seg === "..") || !ALLOWED.test(joined)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const target = "/" + path.map(encodeURIComponent).join("/") + req.nextUrl.search;
  const body = req.method === "GET" ? "" : await req.text(); // DELETE /me carries a confirmation body
  let upstream: Response;
  try {
    upstream = await apiFetch(target, {
      method: req.method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body || undefined,
      signal: req.signal, // stop reading if the browser goes away (the run itself still finishes on the API)
    });
  } catch (e) {
    const signedOut = e instanceof Error && e.message === "Not signed in";
    return Response.json({ detail: signedOut ? "Please sign in again." : "The Foxhood API is unreachable." },
                         { status: signedOut ? 401 : 502 });
  }

  const headers = new Headers({ "Cache-Control": "no-cache, no-transform" });
  const type = upstream.headers.get("content-type");
  if (type) headers.set("Content-Type", type);
  const disposition = upstream.headers.get("content-disposition"); // file downloads (data export)
  if (disposition) headers.set("Content-Disposition", disposition);
  if (type?.startsWith("text/event-stream")) headers.set("X-Accel-Buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers });
}

export { forward as GET, forward as POST, forward as PATCH, forward as DELETE };

import "server-only"; // build fails if this file is ever imported into browser code
import { SignJWT } from "jose";
import { auth } from "@/auth";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const secret = new TextEncoder().encode(process.env.API_JWT_SECRET);

// A 5-minute token proving to FastAPI who the signed-in user is.
async function apiToken(email: string, name?: string | null) {
  return new SignJWT({ email, name: name ?? undefined })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(email)
    .setIssuer("foxhood-web")
    .setAudience("foxhood-api")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) throw new Error("Not signed in");
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${await apiToken(email, session.user?.name)}` },
    cache: "no-store",
  });
}
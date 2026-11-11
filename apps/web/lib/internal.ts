import "server-only";
import { SignJWT } from "jose";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const secret = new TextEncoder().encode(process.env.API_JWT_SECRET);

// A 1-minute token that identifies this Next.js server (not a user) to the API.
async function serviceToken() {
  return new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject("foxhood-web")
    .setIssuer("foxhood-web")
    .setAudience("foxhood-internal")
    .setIssuedAt()
    .setExpirationTime("1m")
    .sign(secret);
}

export async function checkSignIn(email: string, googleSub: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/internal/auth/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${await serviceToken()}` },
      body: JSON.stringify({ email, google_sub: googleSub }),
      cache: "no-store",
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { allowed: boolean };
    return data.allowed === true;
  } catch {
    return false; // fail closed: if the API is unreachable, nobody signs in
  }
}
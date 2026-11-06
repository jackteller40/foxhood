import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// Invite list: only these Google accounts can sign in.
const allowed = new Set(
  (process.env.ALLOWED_EMAILS ?? "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean),
);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google], // reads AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET automatically
  pages: { signIn: "/", error: "/" }, // send refusals back to the landing page
  callbacks: {
    signIn({ profile }) {
      const email = profile?.email?.toLowerCase();
      const verified = (profile as { email_verified?: boolean } | undefined)?.email_verified === true;
      return Boolean(email && verified && allowed.has(email));
    },
  },
});
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { checkSignIn } from "@/lib/internal";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  pages: { signIn: "/", error: "/" },
  callbacks: {
    // The API's invite list decides who gets in.
    async signIn({ account, profile }) {
      const email = profile?.email?.toLowerCase();
      const verified = (profile as { email_verified?: boolean } | undefined)?.email_verified === true;
      if (account?.provider !== "google" || !email || !verified) return false;
      return checkSignIn(email, account.providerAccountId);
    },
    // Keep the Google account id (stable, unlike email) in the session.
    jwt({ token, account }) {
      if (account?.provider === "google") token.googleSub = account.providerAccountId;
      return token;
    },
    session({ session, token }) {
      session.user.googleSub = typeof token.googleSub === "string" ? token.googleSub : undefined;
      return session;
    },
  },
});
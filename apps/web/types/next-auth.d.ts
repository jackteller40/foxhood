import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: { googleSub?: string } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    googleSub?: string;
  }
}
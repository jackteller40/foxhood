import type { Metadata } from "next";
import Link from "next/link";
import { Wordmark } from "@/components/fox-mark";

export const metadata: Metadata = { title: "Privacy - Foxhood" };

const UPDATED = "November 18, 2026";
const CONTACT = "tellerjack40@gmail.com";

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="mt-10 mb-3 text-xl font-semibold tracking-tight">{children}</h2>;
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-[1200px] px-5 py-8 md:px-10">
      <Link href="/" aria-label="Foxhood home"><Wordmark size={26} /></Link>
      <article className="mt-12 max-w-[40em] pb-16 leading-relaxed [&_li]:mt-2 [&_p]:mt-3 [&_ul]:list-disc [&_ul]:pl-5">
        <h1 className="text-4xl font-semibold tracking-tight">Privacy</h1>
        <p className="text-ink-muted">Last updated {UPDATED}</p>
        <p>
          Foxhood is a small, invite-only research tool run by one person, Jack Teller, for a group of friends. This page says
          what it stores, who else sees any of it, and how to get your data out or delete it.
        </p>

        <H>What Foxhood stores</H>
        <ul>
          <li>Your Google account name, email address and account ID, to sign you in and check you&apos;re on the invite list.</li>
          <li>What you enter: your profile (name, risk tolerance, time horizon, investing style, interests), holdings, watchlist and saved notes.</li>
          <li>What Foxhood writes for you: chat conversations, briefs and alerts.</li>
          <li>Usage records: how much AI each request used and what it cost, to enforce daily limits.</li>
        </ul>
        <p>
          Your profile, holdings, watchlist, notes, conversations, briefs and alerts are encrypted before they reach the database,
          with keys kept separately in Google Secret Manager. Foxhood has no ads, no analytics or tracking scripts, and never sells
          or rents your data. The only cookie is the one that keeps you signed in.
        </p>

        <H>Services that handle your data</H>
        <ul>
          <li><strong className="font-semibold">Google</strong> handles sign-in and runs the servers (Google Cloud, United States).</li>
          <li><strong className="font-semibold">Neon</strong> hosts the database (United States). It only ever holds the encrypted versions of the data above.</li>
          <li>
            <strong className="font-semibold">Anthropic</strong> provides the AI (Claude). When you ask a question or a brief is written, the parts of
            your profile, holdings, watchlist and notes needed to answer are sent with it. Under Anthropic&apos;s terms for its API,
            this isn&apos;t used to train their models.
          </li>
          <li>
            <strong className="font-semibold">Tiingo, Finnhub and the Federal Reserve (FRED)</strong> supply market and economic data. They receive
            ticker symbols and dates only, never who you are or what you own.
          </li>
          <li>
            <strong className="font-semibold">Resend</strong> sends brief and alert emails if you have them turned on. It receives your email address and
            the email&apos;s contents.
          </li>
        </ul>

        <H>Your choices</H>
        <ul>
          <li>Turn brief and alert emails on or off in Settings.</li>
          <li>Download everything Foxhood stores about you, as one file, from Settings.</li>
          <li>
            Delete your account from Settings. It erases your data immediately. Backup copies kept for recovering from accidents
            expire on their own within 30 days.
          </li>
        </ul>

        <H>Good to know</H>
        <ul>
          <li>Foxhood is for adults. It&apos;s a research tool, not financial advice, and it can&apos;t place trades.</li>
          <li>If this page changes in a way that matters, you&apos;ll hear about it before it takes effect.</li>
        </ul>

        <H>Questions</H>
        <p>
          Email <a href={`mailto:${CONTACT}`} className="font-semibold text-fox hover:text-fox-dark">{CONTACT}</a>.
        </p>
      </article>
    </main>
  );
}

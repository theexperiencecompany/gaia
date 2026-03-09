import type { Metadata } from "next";
import Link from "next/link";

import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Inbox Zero with AI — Automated Email Triage by GAIA",
  description:
    "GAIA reads your inbox, labels emails by urgency, drafts replies, and creates tasks automatically. Reach inbox zero without spending hours in email. Free tier available.",
  path: "/inbox-zero-ai",
  keywords: [
    "inbox zero AI",
    "AI email triage",
    "automated inbox management",
    "email management AI",
    "AI for inbox zero",
    "AI email assistant",
    "Gmail AI triage",
    "automatic email sorting AI",
    "email automation tool",
    "smart inbox AI",
  ],
});

const faqs = [
  {
    question: "Does GAIA read my emails?",
    answer:
      "Yes — that's how it triages them. GAIA reads the subject, sender, and body of each email to classify urgency and draft replies. On the self-hosted tier, this processing happens entirely on your own server. On the cloud tier, emails are processed securely and never used for model training or shared with third parties.",
  },
  {
    question: "Can I customize how GAIA triages my inbox?",
    answer:
      "Yes. You can define custom rules in natural language — for example, 'anything from my investors is always urgent' or 'newsletters go straight to archive.' GAIA learns your preferences over time and applies them consistently.",
  },
  {
    question: "Will GAIA accidentally delete important emails?",
    answer:
      "GAIA never deletes emails. It labels and archives — which means everything is still there, just organized. The archive operation in Gmail moves emails out of your inbox but keeps them fully accessible. You can always find an archived email via search.",
  },
  {
    question: "Does this work with Google Workspace?",
    answer:
      "Yes. GAIA connects to Gmail via the official Google OAuth integration and works with both personal Gmail accounts and Google Workspace (formerly G Suite) accounts. Enterprise Workspace accounts may require admin approval for the OAuth connection.",
  },
];

const triageSteps = [
  {
    name: "Connect your Gmail account",
    text: "Authorize GAIA to access your Gmail via Google OAuth. This takes under 2 minutes and uses the official Google API — no password sharing, no third-party scraping.",
  },
  {
    name: "Set your triage preferences",
    text: "Tell GAIA in plain English which senders and topics are high priority, which are noise, and what your preferred reply style looks like. GAIA adapts to your preferences immediately.",
  },
  {
    name: "Wake up to an organized inbox",
    text: "GAIA runs your triage overnight (or in real-time during the day). You open your inbox to labeled, prioritized emails — and drafted replies waiting for your approval.",
  },
];

const fourThings = [
  {
    number: "01",
    headline: "Triages by urgency",
    description:
      "GAIA reads each email and classifies it: Urgent (needs your reply today), Normal (can wait), or Noise (newsletters, notifications, auto-responses). You see what needs you — nothing else.",
  },
  {
    number: "02",
    headline: "Drafts replies",
    description:
      "For emails that need a response, GAIA writes a draft in your voice using the full thread context. You review, edit if needed, and send — or reject and write your own. You stay in control.",
  },
  {
    number: "03",
    headline: "Converts emails to tasks",
    description:
      'Spotted an email with an action item? GAIA creates a task in your connected task manager (Todoist, Linear, etc.) automatically. "Review the Q2 proposal by Friday" becomes a real task, not a buried email.',
  },
  {
    number: "04",
    headline: "Archives or labels automatically",
    description:
      "Newsletters, order confirmations, Slack notifications, SaaS receipts — GAIA identifies these and moves them out of your inbox. They&apos;re still findable via search, just not cluttering your view.",
  },
];

export default function InboxZeroAiPage() {
  const webPageSchema = generateWebPageSchema(
    "Inbox Zero with AI — Automated Email Triage by GAIA",
    "GAIA reads your inbox, labels emails by urgency, drafts replies, and creates tasks automatically. Reach inbox zero without spending hours in email. Free tier available.",
    `${siteConfig.url}/inbox-zero-ai`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Inbox Zero with AI",
        url: `${siteConfig.url}/inbox-zero-ai`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    {
      name: "Inbox Zero with AI",
      url: `${siteConfig.url}/inbox-zero-ai`,
    },
  ]);

  const howToSchema = generateHowToSchema(
    "How to Reach Inbox Zero with GAIA AI",
    "Set up GAIA to automatically triage your Gmail inbox in three steps.",
    triageSteps,
  );

  const faqSchema = generateFAQSchema(faqs);

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
          howToSchema,
          generateProductSchema(),
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">Inbox Zero with AI</span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-medium text-violet-400">
            Works with Gmail &amp; Google Workspace
          </div>
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            Reach Inbox Zero with AI — GAIA Triages Your Email Automatically
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            GAIA reads every email, classifies it by urgency, drafts replies in
            your voice, converts action items to tasks, and archives the noise —
            automatically, every day.
          </p>
        </header>

        {/* The inbox zero problem */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Why inbox zero is so hard — and why existing solutions fail
          </h2>
          <div className="space-y-5 text-lg leading-relaxed text-zinc-300">
            <p>
              The average knowledge worker checks email 77 times per day and
              spends 2.5 hours in their inbox. Inbox zero sounds like a
              productivity hack. In practice, it requires constant vigilance
              that most people can&apos;t sustain.
            </p>
            <p>
              GTD frameworks and zero-inbox methodologies work briefly — then
              life gets busy, the inbox refills, and the guilt accumulates. The
              problem isn&apos;t your system. It&apos;s that managing email is
              genuinely time-consuming work that you shouldn&apos;t be doing
              manually.
            </p>
            <p>
              Gmail filters and rules help with known patterns, but they
              can&apos;t read context. They can&apos;t tell the difference
              between an urgent reply from a customer and a newsletter from that
              same domain. They don&apos;t draft responses. They don&apos;t
              create tasks.
            </p>
            <p className="font-medium text-white">
              The only real solution to email overload is an AI that can read,
              understand, and act — the way a human executive assistant would.
            </p>
          </div>
        </section>

        {/* The 4 things GAIA does */}
        <section className="mb-16">
          <h2 className="mb-8 text-3xl font-semibold text-white">
            The 4 things GAIA does to your inbox
          </h2>
          <div className="space-y-4">
            {fourThings.map((item) => (
              <div
                key={item.number}
                className="flex gap-5 rounded-2xl bg-zinc-800 p-6"
              >
                <span className="shrink-0 font-mono text-3xl font-bold text-zinc-600">
                  {item.number}
                </span>
                <div>
                  <h3 className="mb-2 text-lg font-semibold text-white">
                    {item.headline}
                  </h3>
                  <p className="text-sm leading-relaxed text-zinc-400">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Before / after */}
        <section className="mb-16">
          <h2 className="mb-8 text-3xl font-semibold text-white">
            Before and after GAIA
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-red-900/30 bg-red-950/20 p-6">
              <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-red-400">
                Before
              </p>
              <ul className="space-y-3">
                {[
                  "847 unread emails, 12 tabs open",
                  "90 minutes in inbox every morning",
                  "Missed follow-ups, slipped deadlines",
                  "Important emails buried in newsletters",
                  "Action items scattered across threads",
                  "Anxiety about what you might be missing",
                ].map((item) => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-sm text-zinc-300"
                  >
                    <span className="mt-0.5 shrink-0 text-red-400">
                      &#x2212;
                    </span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-2xl border border-emerald-900/30 bg-emerald-950/20 p-6">
              <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-emerald-400">
                After
              </p>
              <ul className="space-y-3">
                {[
                  "Morning briefing: 5 emails that need you",
                  "8 minutes in inbox — replies already drafted",
                  "Follow-ups tracked automatically",
                  "Noise archived, important items flagged",
                  "Action items in your task manager",
                  "Inbox zero by 10am, every day",
                ].map((item) => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-sm text-zinc-300"
                  >
                    <span className="mt-0.5 shrink-0 text-emerald-400">
                      &#x2714;
                    </span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* How to set it up */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            How to set up AI email triage in 3 steps
          </h2>
          <p className="mb-8 text-zinc-400">
            You can go from overflowing inbox to organized in under 20 minutes.
          </p>
          <ol className="space-y-4">
            {triageSteps.map((step, index) => (
              <li
                key={step.name}
                className="flex items-start gap-4 rounded-2xl bg-zinc-800 p-5"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-400/10 text-sm font-semibold text-violet-400">
                  {index + 1}
                </span>
                <div>
                  <p className="mb-1 font-semibold text-white">{step.name}</p>
                  <p className="text-sm leading-relaxed text-zinc-400">
                    {step.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* Works with */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-white">
            Works with Gmail
          </h2>
          <p className="mb-4 text-zinc-400">
            GAIA connects natively to Gmail and Google Workspace via the
            official Google API. Support for Outlook and other email providers
            is on the roadmap.
          </p>
          <div className="flex flex-wrap gap-2">
            {["Gmail (personal)", "Google Workspace", "G Suite"].map(
              (label) => (
                <span
                  key={label}
                  className="rounded-full bg-zinc-700 px-3 py-1 text-sm text-zinc-300"
                >
                  {label}
                </span>
              ),
            )}
            <span className="rounded-full border border-dashed border-zinc-600 px-3 py-1 text-sm text-zinc-500">
              Outlook — coming soon
            </span>
          </div>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <p className="mb-8 text-zinc-400">
            Common questions about GAIA&apos;s AI email triage.
          </p>
          <FAQAccordion faqs={faqs} />
        </section>

        {/* Explore more */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <Link
              href="/ai-chief-of-staff"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                AI Chief of Staff
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Go beyond email — see how GAIA manages your entire workday
                proactively.
              </p>
            </Link>
            <Link
              href="/open-source-ai-assistant"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                Open Source & Self-Host
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Run GAIA on your own servers with full privacy. MIT licensed and
                free to self-host.
              </p>
            </Link>
            <Link
              href="/for/startup-founders"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA for Founders
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                How founders specifically use GAIA to manage their operational
                overhead at scale.
              </p>
            </Link>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}

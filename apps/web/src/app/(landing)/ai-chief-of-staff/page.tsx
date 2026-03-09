import type { Metadata } from "next";
import Link from "next/link";

import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateFAQSchema,
  generateWebPageSchema,
  generatePageMetadata,
  generateBreadcrumbSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "AI Chief of Staff — Your Proactive AI That Runs Your Day | GAIA",
  description:
    "GAIA is your AI chief of staff: it reads your inbox, prepares briefings, schedules meetings, tracks follow-ups, and manages your day proactively — before you ask.",
  path: "/ai-chief-of-staff",
  keywords: [
    "AI chief of staff",
    "AI executive assistant",
    "proactive AI assistant",
    "AI that manages your day",
    "AI morning briefing",
    "AI for founders",
    "AI for executives",
    "personal AI chief of staff",
    "AI operations manager",
    "AI inbox management",
  ],
});

const faqs = [
  {
    question: "Can GAIA really replace a human chief of staff?",
    answer:
      "For most operational overhead — inbox triage, meeting prep, follow-up tracking, briefing generation, and routine delegation — yes. GAIA handles the administrative layer that occupies most of a chief of staff's calendar. It won't replace a strategic thought partner or someone who manages people, but for day-to-day operational work, it covers 70-80% of what founders and execs hire for.",
  },
  {
    question: "What does GAIA do automatically vs what do I need to ask?",
    answer:
      "GAIA sends your morning briefing automatically every day at your chosen time. It also runs scheduled workflows: daily summaries, weekly pipeline reviews, follow-up reminders. You ask GAIA for anything ad-hoc — drafting a reply, scheduling a meeting, pulling context on a deal — via natural language in chat or through the desktop app.",
  },
  {
    question: "How long does setup take?",
    answer:
      "Most people are fully configured in under 20 minutes. Connect Gmail and Google Calendar, set your briefing time, and GAIA starts working. Additional integrations (Slack, Notion, HubSpot, GitHub) each take 1-2 minutes to authorize.",
  },
  {
    question: "Is my email data private?",
    answer:
      "On the cloud tier, your data is processed with strict security controls and never used for model training. On the self-hosted tier, your email content never leaves your own infrastructure — GAIA processes everything locally using your own LLM API key.",
  },
];

const dayInTheLife = [
  {
    time: "7:00 AM",
    label: "Morning Briefing",
    description:
      "GAIA scans your inbox, calendar, and Slack overnight. You wake up to a crisp summary: 3 emails that need a reply, your first meeting in 2 hours, and one deal that went quiet.",
  },
  {
    time: "9:30 AM",
    label: "Meeting Prep",
    description:
      "Before your investor call, GAIA pulls the last thread, the deck you sent, and the open questions from your notes. You walk in prepared, not scrambling.",
  },
  {
    time: "12:00 PM",
    label: "Inbox Triage",
    description:
      'GAIA has drafted replies to 6 emails. You review and send. The other 14 are labeled and archived — none of them needed you. You spend 8 minutes on email, not 90.',
  },
  {
    time: "3:00 PM",
    label: "Follow-Up Tracking",
    description:
      "GAIA flags a prospect who hasn't replied in 5 days and drafts a follow-up. It also reminds you that your CTO is waiting on a decision from last week's thread.",
  },
  {
    time: "6:00 PM",
    label: "End-of-Day Wrap",
    description:
      "GAIA sends your end-of-day summary: what got done, what's open, and what needs attention tomorrow. You close your laptop knowing nothing fell through the cracks.",
  },
];

const capabilities = [
  {
    headline: "Reads your inbox at 7am",
    body: "Every morning, GAIA scans every email that arrived overnight and classifies each one: urgent reply needed, FYI only, or archive. You see what matters, nothing else.",
  },
  {
    headline: "Prepares your day's priorities",
    body: "GAIA cross-references your inbox, calendar, and task list to generate a ranked priority list. Not a dump of everything — a focused view of what actually needs you today.",
  },
  {
    headline: "Drafts replies in your voice",
    body: "For emails that need a response, GAIA drafts a reply using context from the full thread and your past communication style. You review and send — or edit and send.",
  },
  {
    headline: "Schedules follow-ups automatically",
    body: "Tell GAIA to follow up in 3 days if no reply, and it will — without another thought from you. It tracks every open thread and surfaces the right ones at the right time.",
  },
  {
    headline: "Alerts you to urgent items",
    body: "GAIA monitors for signals that need immediate attention: a board member replied to a thread you missed, a contract deadline in 24 hours, a deal that went cold.",
  },
  {
    headline: "Delegates via natural language",
    body: "Tell GAIA what needs to happen in plain English — 'schedule a 30-minute call with Alex next week, morning preferred' — and it handles the back-and-forth to make it happen.",
  },
];

export default function AiChiefOfStaffPage() {
  const webPageSchema = generateWebPageSchema(
    "AI Chief of Staff — Your Proactive AI That Runs Your Day | GAIA",
    "GAIA is your AI chief of staff: it reads your inbox, prepares briefings, schedules meetings, tracks follow-ups, and manages your day proactively — before you ask.",
    `${siteConfig.url}/ai-chief-of-staff`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "AI Chief of Staff",
        url: `${siteConfig.url}/ai-chief-of-staff`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    {
      name: "AI Chief of Staff",
      url: `${siteConfig.url}/ai-chief-of-staff`,
    },
  ]);

  const faqSchema = generateFAQSchema(faqs);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, faqSchema]} />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">AI Chief of Staff</span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-400/20 bg-blue-400/10 px-3 py-1 text-xs font-medium text-blue-400">
            For founders, executives &amp; senior ICs
          </div>
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            Your AI Chief of Staff — Proactively Manages Your Day Before You
            Ask
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            A great chief of staff handles your operational overhead so you can
            focus on what only you can do. GAIA does the same — for a fraction
            of the cost, available 24/7, with no ramp-up time.
          </p>
        </header>

        {/* The problem */}
        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            Most founders and executives can&apos;t afford a chief of staff
          </h2>
          <p className="mb-4 text-lg leading-relaxed text-zinc-300">
            A senior chief of staff costs $150K–$300K per year. They require
            onboarding, context-building, and trust before they add value. Most
            founders and executives at growing companies never hire one — not
            because they don&apos;t need one, but because it&apos;s not justified yet.
          </p>
          <p className="text-lg leading-relaxed text-zinc-300">
            The result: you spend 2–4 hours per day on email, meeting prep,
            follow-ups, and operational coordination. That&apos;s time taken from
            strategy, product, and the work that actually moves the needle.
          </p>
        </section>

        {/* How GAIA fills the role */}
        <section className="mb-16">
          <h2 className="mb-8 text-3xl font-semibold text-white">
            How GAIA fills the chief of staff role
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {capabilities.map((cap) => (
              <div key={cap.headline} className="rounded-2xl bg-zinc-800 p-6">
                <h3 className="mb-2 font-semibold text-white">
                  {cap.headline}
                </h3>
                <p className="text-sm leading-relaxed text-zinc-400">
                  {cap.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Who it's for */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-6 text-2xl font-semibold text-white">
            Who GAIA as chief of staff is for
          </h2>
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
              <div>
                <p className="font-semibold text-white">
                  Founders and early-stage CEOs
                </p>
                <p className="text-sm text-zinc-400">
                  Managing investor relations, team ops, sales, and product all
                  at once. GAIA handles the coordination layer.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
              <div>
                <p className="font-semibold text-white">
                  Executives at growth-stage companies
                </p>
                <p className="text-sm text-zinc-400">
                  Running departments, managing up, managing across. GAIA keeps
                  your commitments tracked and your inbox under control.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
              <div>
                <p className="font-semibold text-white">
                  Senior ICs overwhelmed by coordination
                </p>
                <p className="text-sm text-zinc-400">
                  Staff engineers, principal PMs, senior designers who spend
                  more time in email and meetings than doing deep work. GAIA
                  reclaims their focus time.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Day in the life */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            A day in the life with GAIA
          </h2>
          <p className="mb-8 text-zinc-400">
            What your workday looks like when you have an AI chief of staff
            running in the background.
          </p>
          <div className="space-y-0">
            {dayInTheLife.map((block, index) => (
              <div key={block.time} className="flex gap-6">
                <div className="flex flex-col items-center">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-semibold text-zinc-300">
                    {index + 1}
                  </div>
                  {index < dayInTheLife.length - 1 && (
                    <div className="mt-1 h-full w-px bg-zinc-700" />
                  )}
                </div>
                <div className="pb-8">
                  <div className="mb-1 flex items-center gap-3">
                    <span className="text-sm font-medium text-zinc-500">
                      {block.time}
                    </span>
                    <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs font-medium text-zinc-300">
                      {block.label}
                    </span>
                  </div>
                  <p className="text-zinc-300">{block.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <p className="mb-8 text-zinc-400">
            Common questions about using GAIA as your AI chief of staff.
          </p>
          <FAQAccordion faqs={faqs} />
        </section>

        {/* Explore more */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/for/startup-founders"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA for Founders
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                See how GAIA helps startup founders specifically — investor
                updates, team ops, pipeline management.
              </p>
            </Link>
            <Link
              href="/inbox-zero-ai"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                Inbox Zero with AI
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Deep dive into GAIA&apos;s email triage capabilities — how it
                reaches inbox zero automatically.
              </p>
            </Link>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}

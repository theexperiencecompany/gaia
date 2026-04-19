"use client";

import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";
import FAQAccordion from "@/components/seo/FAQAccordion";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import PersonaSEOSection from "@/features/landing/components/sections/PersonaSEOSection";

const ease = [0.22, 1, 0.36, 1] as const;

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
      "Newsletters, order confirmations, Slack notifications, SaaS receipts — GAIA identifies these and moves them out of your inbox. They're still findable via search, just not cluttering your view.",
  },
];

const beforeItems = [
  "847 unread emails, 12 tabs open",
  "90 minutes in inbox every morning",
  "Missed follow-ups, slipped deadlines",
  "Important emails buried in newsletters",
  "Action items scattered across threads",
  "Anxiety about what you might be missing",
];

const afterItems = [
  "Morning briefing: 5 emails that need you",
  "8 minutes in inbox — replies already drafted",
  "Follow-ups tracked automatically",
  "Noise archived, important items flagged",
  "Action items in your task manager",
  "Inbox zero by 10am, every day",
];

const painPoints = [
  "The average knowledge worker checks email 77 times per day and spends 2.5 hours in their inbox.",
  "GTD frameworks and zero-inbox methodologies work briefly — then life gets busy, the inbox refills, and the guilt accumulates.",
  "Gmail filters and rules help with known patterns, but they can't read context or tell the difference between an urgent customer reply and a newsletter from the same domain.",
  "Traditional email tools don't draft responses, create tasks, or understand the difference between noise and signal.",
];

function AnimatedCard({
  children,
  delay = 0,
  className = "",
}: {
  readonly children: React.ReactNode;
  readonly delay?: number;
  readonly className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.1 });

  return (
    <m.div
      ref={ref}
      initial={{ opacity: 0, y: 20 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.5, ease, delay }}
      className={className}
    >
      {children}
    </m.div>
  );
}

export default function InboxZeroAiClient() {
  return (
    <div className="w-full">
      {/* Hero */}
      <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-16 pt-24 text-center">
        <m.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-medium text-violet-400"
        >
          Works with Gmail &amp; Google Workspace
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Reach Inbox Zero with AI
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-zinc-300"
        >
          GAIA reads every email, classifies it by urgency, drafts replies in
          your voice, converts action items to tasks, and archives the noise —
          automatically, every day.
        </m.p>
      </section>

      {/* The inbox zero problem */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="The Problem"
          headline="Why inbox zero is so hard — and why existing solutions fail."
          description="The only real solution to email overload is an AI that can read, understand, and act — the way a human executive assistant would."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "google-calendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
            { id: "todoist", label: "Todoist" },
            { id: "notion", label: "Notion" },
          ]}
        />
        <div className="w-full max-w-3xl space-y-4 text-left">
          {painPoints.map((point, i) => (
            <AnimatedCard
              key={point}
              delay={i * 0.08}
              className="flex items-start gap-3 rounded-2xl bg-zinc-800/60 p-5"
            >
              <span className="mt-0.5 shrink-0 text-red-400">✕</span>
              <p className="text-lg leading-relaxed text-zinc-300">{point}</p>
            </AnimatedCard>
          ))}
        </div>
      </section>

      {/* The 4 things GAIA does */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="What GAIA Does"
          headline="The 4 things GAIA does to your inbox."
          description="GAIA isn't a filter — it's a full email triage system that reads, acts, and reports back."
        />
        <div className="w-full max-w-3xl space-y-4 text-left">
          {fourThings.map((item, i) => (
            <AnimatedCard
              key={item.number}
              delay={i * 0.08}
              className="flex gap-5 rounded-2xl bg-zinc-800/60 p-6"
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
            </AnimatedCard>
          ))}
        </div>
      </section>

      {/* Before / After */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Before & After"
          headline="Your inbox, transformed."
          description="See the difference GAIA makes from day one — less chaos, more clarity, every morning."
        />
        <div className="w-full max-w-3xl">
          <div className="grid gap-4 sm:grid-cols-2">
            <AnimatedCard className="rounded-2xl border border-red-900/30 bg-red-950/20 p-6 text-left">
              <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-red-400">
                Before
              </p>
              <ul className="space-y-3">
                {beforeItems.map((item) => (
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
            </AnimatedCard>
            <AnimatedCard
              delay={0.1}
              className="rounded-2xl border border-emerald-900/30 bg-emerald-950/20 p-6 text-left"
            >
              <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-emerald-400">
                After
              </p>
              <ul className="space-y-3">
                {afterItems.map((item) => (
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
            </AnimatedCard>
          </div>
        </div>
      </section>

      {/* How to set it up in 3 steps */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Setup"
          headline="How to set up AI email triage in 3 steps."
          description="You can go from overflowing inbox to organized in under 20 minutes."
        />
        <ol className="w-full max-w-3xl space-y-4 text-left">
          {triageSteps.map((step, index) => (
            <AnimatedCard
              key={step.name}
              delay={index * 0.1}
              className="flex items-start gap-4 rounded-2xl bg-zinc-800/60 p-5"
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
            </AnimatedCard>
          ))}
        </ol>
      </section>

      {/* Works with */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Integrations"
          headline="Works with Gmail — and everything around it."
          description="GAIA connects natively to Gmail and Google Workspace via the official Google API. It also creates tasks in Todoist, Linear, and Notion when email action items are detected."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "google-calendar", label: "Google Calendar" },
            { id: "todoist", label: "Todoist" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
          ]}
        />
        <AnimatedCard className="w-full max-w-3xl rounded-3xl bg-zinc-800/60 p-8 text-left">
          <div className="mb-4 flex flex-wrap gap-2">
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
          <p className="text-sm leading-relaxed text-zinc-400">
            Support for Outlook and other email providers is on the roadmap.
          </p>
        </AnimatedCard>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Common questions about GAIA&apos;s AI email triage.
        </p>
        <FAQAccordion faqs={faqs} />
      </section>

      {/* PersonaSEO Section */}
      <PersonaSEOSection
        persona="Email Power Users"
        stats={[
          { value: "2.5h", label: "avg daily email time" },
          { value: "8min", label: "with GAIA" },
          { value: "77x", label: "avg daily email checks" },
          { value: "inbox zero", label: "by 10am" },
        ]}
        painPoints={[
          "Spending 2.5+ hours per day in your inbox just to stay on top of it",
          "Missing important emails buried under newsletters and notifications",
          "Forgetting to follow up and letting conversations go cold",
          "Manually turning emails into tasks instead of having it happen automatically",
          "No consistent system that holds up when you get busy",
        ]}
        features={fourThings.map((t) => ({
          title: t.headline,
          description: t.description,
        }))}
        faqs={faqs}
        relatedRoles={[
          {
            href: "/ai-chief-of-staff",
            label: "AI Chief of Staff",
            description:
              "Go beyond email — see how GAIA manages your entire workday proactively.",
          },
          {
            href: "/for/startup-founders",
            label: "GAIA for Founders",
            description:
              "How founders specifically use GAIA to manage their operational overhead at scale.",
          },
          {
            href: "/open-source-ai-assistant",
            label: "Open Source & Self-Host",
            description:
              "Run GAIA on your own servers with full privacy. MIT licensed and free to self-host.",
          },
        ]}
      />

      <FinalSection />
    </div>
  );
}

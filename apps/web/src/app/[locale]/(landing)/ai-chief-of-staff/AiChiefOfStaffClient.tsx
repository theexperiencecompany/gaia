"use client";

import { Chip } from "@heroui/chip";
import * as m from "motion/react-m";
import FAQAccordion from "@/components/seo/FAQAccordion";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import PersonaSEOSection from "@/features/landing/components/sections/PersonaSEOSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";

const ease = [0.22, 1, 0.36, 1] as const;

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
      "GAIA has drafted replies to 6 emails. You review and send. The other 14 are labeled and archived — none of them needed you. You spend 8 minutes on email, not 90.",
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

const whoItsFor = [
  {
    title: "Founders and early-stage CEOs",
    description:
      "Managing investor relations, team ops, sales, and product all at once. GAIA handles the coordination layer.",
  },
  {
    title: "Executives at growth-stage companies",
    description:
      "Running departments, managing up, managing across. GAIA keeps your commitments tracked and your inbox under control.",
  },
  {
    title: "Senior ICs overwhelmed by coordination",
    description:
      "Staff engineers, principal PMs, senior designers who spend more time in email and meetings than doing deep work. GAIA reclaims their focus time.",
  },
];

export default function AiChiefOfStaffClient() {
  return (
    <div className="w-full">
      {/* Hero */}
      <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-16 pt-24 text-center">
        <div className="absolute inset-0 -z-10">
          <ProgressiveImage
            webpSrc="/images/wallpapers/bands_gradient_1.webp"
            pngSrc="/images/wallpapers/bands_gradient_1.png"
            alt="Gradient background"
            className="object-cover"
            shouldHaveInitialFade
            priority
          />
        </div>
        <m.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="relative z-10 mb-6"
        >
          <Chip variant="flat" color="primary" size="md">
            For founders, executives &amp; senior ICs
          </Chip>
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Your AI Chief of Staff —
          <br />
          Runs your day before you ask.
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          A great chief of staff handles your operational overhead so you can
          focus on what only you can do. GAIA does the same — for a fraction of
          the cost, available 24/7, with no ramp-up time.
        </m.p>
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.3 }}
          className="relative z-10"
        >
          <GetStartedButton
            text="See it in action"
            btnColor="#000000"
            classname="text-white! text-base h-12 rounded-2xl"
          />
        </m.div>
      </section>

      {/* Capabilities — How GAIA fills the role */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Chief of Staff"
          headline="How GAIA fills the chief of staff role."
          description="Most founders and executives can't afford a $150K–$300K human chief of staff. GAIA handles the operational layer — inbox triage, meeting prep, follow-ups, and briefings — starting immediately, no ramp-up required."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "slack", label: "Slack" },
            { id: "google-calendar", label: "Calendar" },
            { id: "notion", label: "Notion" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <div className="grid gap-4 text-left sm:grid-cols-2">
            {capabilities.map((cap) => (
              <div
                key={cap.headline}
                className="rounded-2xl bg-zinc-800/60 p-6"
              >
                <h3 className="mb-2 font-semibold text-white">
                  {cap.headline}
                </h3>
                <p className="text-sm leading-relaxed text-zinc-400">
                  {cap.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Who It's For */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Who It's For"
          headline="Built for people who run things."
          description="If you spend more than 2 hours a day on email, meeting prep, follow-ups, and operational coordination — GAIA is for you."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "slack", label: "Slack" },
            { id: "google-calendar", label: "Calendar" },
            { id: "notion", label: "Notion" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <div className="space-y-4 text-left">
            {whoItsFor.map((item) => (
              <div
                key={item.title}
                className="flex items-start gap-4 rounded-2xl bg-zinc-800/60 p-6"
              >
                <span className="mt-0.5 shrink-0 text-emerald-400">
                  &#x2714;
                </span>
                <div>
                  <p className="font-semibold text-white">{item.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Day in the Life — Timeline */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Day in the Life"
          headline="What your workday looks like with GAIA."
          description="GAIA runs in the background from the moment you wake up. Here's what a typical day looks like when you have an AI chief of staff handling the operational layer."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "slack", label: "Slack" },
            { id: "google-calendar", label: "Calendar" },
            { id: "notion", label: "Notion" },
            { id: "hubspot", label: "HubSpot" },
          ]}
        />
        <div className="w-full max-w-3xl text-left">
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
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Everything you need to know about GAIA as your AI chief of staff.
        </p>
        <FAQAccordion faqs={faqs} />
      </section>

      {/* SEO Section */}
      <PersonaSEOSection
        persona="Founders &amp; Executives"
        painPoints={[
          "Spending 2–4 hours a day on email triage, meeting prep, and follow-ups instead of high-leverage work.",
          "A senior chief of staff costs $150K–$300K per year — not justifiable until the company is much larger.",
          "Critical follow-ups fall through the cracks when you're context-switching across investor relations, team ops, and product.",
          "Morning scramble: no single view of what's urgent, what's on the calendar, and what needs a decision today.",
          "Manually updating the CRM, writing the investor update, scheduling back-and-forth — all work a system should handle.",
        ]}
        features={capabilities.map((cap) => ({
          title: cap.headline,
          description: cap.body,
        }))}
        stats={[
          { value: "70%", label: "operational work handled" },
          { value: "20min", label: "avg setup time" },
          { value: "24/7", label: "always on" },
          { value: "8-12h", label: "saved per week" },
        ]}
        faqs={faqs}
        relatedRoles={[
          {
            href: "/for/startup-founders",
            label: "GAIA for Founders",
            description:
              "See how GAIA helps startup founders specifically — investor updates, team ops, pipeline management.",
          },
          {
            href: "/inbox-zero-ai",
            label: "Inbox Zero with AI",
            description:
              "Deep dive into GAIA's email triage capabilities — how it reaches inbox zero automatically.",
          },
          {
            href: "/open-source-ai-assistant",
            label: "Open Source & Self-Host",
            description:
              "Run GAIA on your own infrastructure with full data control. MIT licensed and free forever.",
          },
        ]}
      />

      <FinalSection />
    </div>
  );
}

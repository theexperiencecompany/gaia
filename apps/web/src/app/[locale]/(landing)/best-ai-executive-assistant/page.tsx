import type { Metadata } from "next";
import Link from "next/link";

import BestAssistantHub from "@/components/seo/BestAssistantHub";
import {
  type BestHubConfig,
  generateBestHubMetadata,
} from "@/components/seo/bestAssistantHubConfig";
import { CURRENT_YEAR_TOKEN } from "@/lib/feature-data";

// GAIA excluded (it is row #1, "our pick"). Every slug must exist in
// public/data/comparisons/{slug}.json. Missing slugs throw at render.
const RANKED_SLUGS = [
  "copilot",
  "superhuman",
  "lindy-ai",
  "motion",
  "reclaim",
  "shortwave",
  "sanebox",
] as const;

const PICK_COUNT = RANKED_SLUGS.length + 1;

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-executive-assistant",
  pageTitle: `AI Executive Assistant Apps: ${PICK_COUNT} Best for ${CURRENT_YEAR_TOKEN}`,
  pageDescription: `${PICK_COUNT} AI executive assistant apps and tools, ranked by how much inbox, calendar and follow-up work they take over, including picks for Outlook users.`,
  keywords: [
    "ai executive assistant",
    "ai executive assistant app",
    "ai executive assistant tools",
    "free ai executive assistant",
    "ai executive assistant for outlook",
    "best ai executive assistant",
    `best ai executive assistant ${CURRENT_YEAR_TOKEN}`,
    "virtual executive assistant ai",
  ],
  breadcrumbName: "AI Executive Assistant Apps",
  heading: `AI Executive Assistant Apps: The ${PICK_COUNT} Worth Trying in ${CURRENT_YEAR_TOKEN}`,
  subheading:
    "Which app actually does the job of an executive assistant: reading the inbox, guarding the calendar and chasing follow-ups. GAIA is our pick, and every alternative links to a full comparison.",
  intro: (
    <>
      <p>
        An AI executive assistant app should do what a human EA does all day:
        read every email so you only see what needs you, keep your calendar
        sane, prepare you for the next meeting and chase what was promised. Most
        tools sold under the label do one slice of that. Email clients make you
        faster at the inbox, calendar tools defend your time, and agent builders
        let you assemble the rest yourself.
      </p>
      <p>
        We ranked the apps by how much of the whole job each one takes over.
        GAIA is our pick, and yes, we make it: it connects to your email,
        calendar, tasks and team tools and runs workflows on its own, on a
        schedule or when a new email arrives. If you want the concept rather
        than the shopping list, read{" "}
        <Link
          href="/learn/digital-executive-assistant"
          className="text-zinc-200 underline underline-offset-2 hover:text-white"
        >
          what a digital executive assistant is
        </Link>
        ; if you want the bigger operating role, see{" "}
        <Link
          href="/ai-chief-of-staff"
          className="text-zinc-200 underline underline-offset-2 hover:text-white"
        >
          GAIA as an AI chief of staff
        </Link>
        .
      </p>
      <p>
        On Outlook: GAIA connects to Outlook to read, draft and send email and
        to manage your calendar, and Microsoft Copilot lives inside Outlook
        itself. GAIA's automatic new-email workflows currently run on Gmail, so
        an Outlook-only executive gets GAIA on request rather than triggered by
        every new message. On price: there is no genuinely free AI executive
        assistant that acts on your accounts. GAIA's hosted service is paid, and
        self-hosting it is free for personal, noncommercial use.
      </p>
    </>
  ),
  tableAriaLabel: `Top ${PICK_COUNT} AI executive assistant apps ranked`,
  tableTitle: `The ${PICK_COUNT} AI executive assistant apps at a glance`,
  gaiaBestFor: "The whole EA job, across tools",
  gaiaTake:
    "Triages email, schedules, tracks follow-ups and runs workflows on its own.",
  pickBody:
    "GAIA works across Gmail or Outlook, Google Calendar, Slack, Notion, Linear, Todoist and the rest of your stack. It drafts and sends replies, schedules and moves meetings, turns commitments in email into todos, and runs workflows on a schedule or when something happens in a connected tool. You choose whether it asks before it sends, deletes or posts, and you can reach it from the web, the desktop app or WhatsApp, Telegram and iMessage. It is source-available under the PolyForm Noncommercial license.",
  pickCompareHref: "/compare/copilot",
  pickCompareLabel: "See GAIA vs Microsoft Copilot head-to-head",
  pickAlternativeHref: "/alternative-to/superhuman",
  pickAlternativeLabel: "Best Superhuman alternative guide",
  rankedSlugs: RANKED_SLUGS,
  bestFor: {
    copilot: "Executives standardized on Microsoft 365",
    superhuman: "Getting through email faster yourself",
    "lindy-ai": "Building single-purpose agents",
    motion: "Auto-scheduling tasks into the calendar",
    reclaim: "Defending focus time and habits",
    shortwave: "AI on top of a Gmail inbox",
    sanebox: "Filtering low-priority email",
  },
  shortVersion: {
    copilot: "AI inside Outlook, Teams and Office. Strongest inside Microsoft.",
    superhuman:
      "A fast, keyboard-driven email client. You still do the triage.",
    "lindy-ai": "Task-specific agents you set up one job at a time.",
    motion: "Plans your tasks onto your calendar. Leaves email to you.",
    reclaim: "Smart calendar blocking for people and teams.",
    shortwave: "An AI email client for Gmail, not a cross-tool assistant.",
    sanebox: "Sorts email into folders. Does not reply or schedule.",
  },
  faqs: [
    {
      question: "What is the best AI executive assistant app?",
      answer:
        "It depends on how much of the job you want handed over. If you want one assistant to read your email, manage your calendar, track follow-ups and run recurring workflows across your tools, GAIA is our pick. If you only want a faster inbox, Superhuman or Shortwave fit; if you live in Microsoft 365, Copilot is the native option.",
    },
    {
      question: "Is there a free AI executive assistant?",
      answer:
        "Not one that acts on your accounts at no cost. GAIA's hosted service is a paid subscription. Its code is source-available, so you can self-host it for personal, noncommercial use and pay only for your server and AI model.",
    },
    {
      question: "Which AI executive assistant works with Outlook?",
      answer:
        "Microsoft Copilot is built into Outlook. GAIA also connects to Outlook to read, draft and send email and manage your calendar from chat; its automatic new-email workflows currently run on Gmail.",
    },
    {
      question: "Can an AI executive assistant replace a human EA?",
      answer:
        "For the administrative layer (inbox triage, scheduling, follow-up tracking and routine replies) it covers a lot. It will not replace judgement about people, travel crises or relationships. If you have a human EA, GAIA can take the routine layer so they spend their time on that work instead.",
    },
    {
      question: "How is this different from an AI chief of staff?",
      answer:
        "An executive assistant manages your inbox and calendar; a chief of staff runs operations around you. GAIA can do both, and the AI chief of staff page covers the broader role.",
    },
  ],
  comparisonsTitle: "Compare GAIA with each app",
  alternativesTitle: "Alternative guides",
};

export function generateMetadata(): Metadata {
  return generateBestHubMetadata(CONFIG);
}

export default function BestAiExecutiveAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}

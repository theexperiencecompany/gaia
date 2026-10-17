import type { Metadata } from "next";
import Link from "next/link";

import BestAssistantHub, {
  type BestHubConfig,
} from "@/components/seo/BestAssistantHub";
import { generatePageMetadata } from "@/lib/seo";

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-calendar-assistant",
  pageTitle: "Best AI Calendar Assistant: 6 Top Picks for 2026",
  pageDescription:
    "We ranked 5 AI calendar assistants by how much scheduling busywork they remove. GAIA is our pick for auto-scheduling, buffers, and prep.",
  keywords: [
    "best AI calendar assistant",
    "AI calendar assistant",
    "best calendar AI",
    "Motion alternative",
    "Reclaim alternative",
    "AI scheduling assistant",
    "best AI calendar assistant 2026",
  ],
  breadcrumbName: "Best AI Calendar Assistant",
  heading: "Best AI Calendar Assistant: Our Top 6 for 2026",
  subheading:
    "Ranked by how much scheduling busywork each assistant removes, not by hype. GAIA is our pick. The rest are described fairly, with links to our full comparisons so you can check our work.",
  intro: (
    <>
      <p>
        Most calendar tools stop at the schedule itself: tasks placed on a grid,
        focus time defended, conflicts resolved. The meeting still needs prep,
        the follow-up still needs sending, and the buffer between back-to-backs
        still disappears.
      </p>
      <p>
        That is the test behind this ranking. We looked at the AI calendar
        assistants people actually use, from Motion and Reclaim to Sunsama,
        Akiflow, and Clockwise, and asked one question: how much of the work
        around your calendar disappears? Tools that only arrange time rank below
        tools that handle what fills it.
      </p>
      <p>
        GAIA is our pick, and yes, we make it. It sits at number one for one
        reason: it is the only assistant on this list that schedules meetings,
        enforces{" "}
        <Link
          href="/learn/buffer-time"
          className="underline underline-offset-2 hover:text-zinc-100"
        >
          buffer time
        </Link>
        , preps you beforehand, and follows up after, all connected to your
        email and tasks. Every competitor below is described in its own words
        from our published comparisons, each linked so you can verify every
        claim.
      </p>
    </>
  ),
  tableAriaLabel: "Top 6 AI calendar assistants ranked",
  tableTitle: "The top 6 at a glance",
  gaiaBestFor: "Proactive calendar work",
  gaiaTake:
    "Schedules, buffers, preps, and follows up across 50+ tools before you ask.",
  gaiaItemDescription:
    "Proactive productivity OS that schedules, buffers, and preps your calendar across 50+ tools before you ask.",
  pickBody:
    "GAIA is a proactive productivity OS that runs your calendar end to end. It schedules meetings around your preferences, enforces buffer time between back-to-backs, briefs you before important calls, and turns outcomes into tasks and follow-ups across Gmail, Slack, Notion, and more than 50 integrations. As an open-source project, everything touching the calendar is auditable in code.",
  pickCompareHref: "/compare/motion",
  pickCompareLabel: "See GAIA vs Motion head-to-head",
  pickAlternativeHref: "/alternative-to/motion",
  pickAlternativeLabel: "Best Motion alternative guide",
  // GAIA excluded (it is row #1, "our pick"). Every slug must exist in
  // public/data/comparisons/{slug}.json. Missing slugs throw at render.
  rankedSlugs: ["motion", "reclaim", "sunsama", "akiflow", "clockwise"],
  bestFor: {
    motion: "Auto-scheduling tasks into your calendar",
    reclaim: "Defending focus time for busy teams",
    sunsama: "A mindful daily planning ritual",
    akiflow: "One task inbox for power users",
    clockwise: "Unfragmenting team calendars",
  },
  shortVersion: {
    motion: "AI that schedules tasks into your calendar. Scheduling only.",
    reclaim: "Smart scheduling for teams. Optimizes time, not email or tasks.",
    sunsama:
      "Guided morning ritual, time-blocked day. Planning, not automation.",
    akiflow: "Tasks from 30+ tools in one keyboard-driven hub. You still plan.",
    clockwise: "Auto-scheduled focus time for large groups. Calendar only.",
  },
  faqs: [
    {
      question: "What is the best AI calendar assistant right now?",
      answer:
        "Motion earns its spot when tasks keep failing to fit the grid, Reclaim and Clockwise protect focus time for teams that book a lot of meetings, Sunsama runs a deliberately calm daily ritual, and Akiflow funnels tasks from everywhere into one keyboard-driven view. They all arrange the day; none of them work the loop around a meeting. GAIA takes number one because it does both: it books the event, guards the buffer before it, briefs you beforehand, and follows up afterward.",
    },
    {
      question: "Motion vs Reclaim vs GAIA: which should I pick?",
      answer:
        "Motion if what you want is a calendar that automatically makes room for your tasks. Reclaim if the problem lives with people: shared calendars where everyone's focus time gets eaten. GAIA if scheduling is only the entry point and you want the rest handled too: meetings booked off email, buffers kept honest, a brief before each call, and follow-up work routed back into your task tools.",
    },
    {
      question: "Is GAIA an open-source calendar assistant?",
      answer:
        "Yes. Because the code is public, you can verify what it writes onto your schedule, what it reads from your email, and how meeting details travel between tools, all before giving it access. It connects Gmail, Slack, Notion, and more than 50 other tools in total, so the calendar is audited in the same place as everything else it runs.",
    },
    {
      question:
        "Will GAIA work next to Sunsama, Akiflow, or my current planner?",
      answer:
        "Yes, and most users actually prefer that setup. Your planner keeps the morning ritual and the flat task list you enjoy; GAIA operates above it, creating events from email, keeping buffers intact between back-to-backs, prepping each meeting, and pushing outcomes back into whatever system holds your work. The ritual stays yours; the machinery becomes automatic.",
    },
  ],
  comparisonsTitle: "Every calendar comparison",
  alternativesTitle: "Every calendar alternative guide",
};

export function generateMetadata(): Metadata {
  return generatePageMetadata({
    title: CONFIG.pageTitle,
    description: CONFIG.pageDescription,
    path: CONFIG.pagePath,
    keywords: CONFIG.keywords,
  });
}

export default function BestAiCalendarAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}

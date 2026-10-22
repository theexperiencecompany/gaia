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
// Hoisted so the "Top N" copy below always equals GAIA + ranked runners-up.
const RANKED_SLUGS = [
  "motion",
  "reclaim",
  "sunsama",
  "akiflow",
  "clockwise",
] as const;

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-calendar-assistant",
  pageTitle: `Best AI Calendar Assistant: ${RANKED_SLUGS.length + 1} Top Picks for ${CURRENT_YEAR_TOKEN}`,
  pageDescription: `We ranked ${RANKED_SLUGS.length} AI calendar assistants by how much scheduling busywork they remove. GAIA is our pick for auto-scheduling, buffers, and prep.`,
  keywords: [
    "best AI calendar assistant",
    "AI calendar assistant",
    "best calendar AI",
    "Motion alternative",
    "Reclaim alternative",
    "AI scheduling assistant",
    `best AI calendar assistant ${CURRENT_YEAR_TOKEN}`,
  ],
  breadcrumbName: "Best AI Calendar Assistant",
  heading: `Best AI Calendar Assistant: Our Top ${RANKED_SLUGS.length + 1} for ${CURRENT_YEAR_TOKEN}`,
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
  tableAriaLabel: `Top ${RANKED_SLUGS.length + 1} AI calendar assistants ranked`,
  tableTitle: `The top ${RANKED_SLUGS.length + 1} at a glance`,
  gaiaBestFor: "Proactive calendar work",
  gaiaTake:
    "Schedules, buffers, preps, and follows up across your tools before you ask.",
  pickBody:
    "GAIA is a proactive productivity OS that runs your calendar end to end. It schedules meetings around your preferences, enforces buffer time between back-to-backs, briefs you before important calls, and turns outcomes into tasks and follow-ups across Gmail, Slack, Notion, and the rest of your tools. Its code is source-available under the PolyForm Noncommercial license, so you can inspect exactly how your data is handled.",
  pickCompareHref: "/compare/motion",
  pickCompareLabel: "See GAIA vs Motion head-to-head",
  pickAlternativeHref: "/alternative-to/motion",
  pickAlternativeLabel: "Best Motion alternative guide",
  rankedSlugs: RANKED_SLUGS,
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
        "There is no single best for everyone. Motion auto-schedules tasks, Reclaim and Clockwise defend team focus time, Sunsama guides a mindful planning ritual, and Akiflow unifies tasks for power users. GAIA is our pick because it covers the whole loop: scheduling meetings, enforcing buffers, prepping you beforehand, and connecting every event to your email and tasks.",
    },
    {
      question: "What is the best AI scheduling assistant?",
      answer:
        "For planning your own time, Motion and Reclaim auto-place tasks and focus blocks. For meetings with other people, Calendly and similar tools send a booking link. GAIA is our pick when scheduling starts in your inbox: it reads the request, finds a free slot on your calendar and drafts the reply, so meetings get booked without the back-and-forth.",
    },
    {
      question: "Motion vs Reclaim vs GAIA: which should I pick?",
      answer:
        "Pick Motion if your main problem is fitting tasks into your calendar, or Reclaim if your team needs focus time defended automatically. Pick GAIA if scheduling is only half the pain: GAIA schedules meetings, protects buffers, prepares briefs, and then handles the email and tasks around every event across your tools.",
    },
    {
      question: "Can I use GAIA alongside Motion, Sunsama, or Akiflow?",
      answer:
        "Yes. They solve different problems and work well together. Keep your planner for the daily ritual or the unified task view, and let GAIA handle the upstream layer: creating events from email, enforcing buffer time, prepping meetings, and running cross-tool workflows so there is less to plan.",
    },
    {
      question: "Is GAIA open source?",
      answer:
        "GAIA is source-available, not open source: the full code is public under the PolyForm Noncommercial license, which lets you read it and self-host it for personal, noncommercial use. The hosted service at heygaia.io is a paid subscription.",
    },
  ],
  comparisonsTitle: "Every calendar comparison",
  alternativesTitle: "Every calendar alternative guide",
};

export function generateMetadata(): Metadata {
  return generateBestHubMetadata(CONFIG);
}

export default function BestAiCalendarAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}

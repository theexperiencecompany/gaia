import type { Metadata } from "next";

import BestAssistantHub, {
  type BestHubConfig,
  generateBestHubMetadata,
} from "@/components/seo/BestAssistantHub";

// GAIA excluded (it is row #1, "our pick"). Every slug must exist in
// public/data/comparisons/{slug}.json. Missing slugs throw at render.
// Hoisted so the "Top N" copy below always equals GAIA + ranked runners-up.
const RANKED_SLUGS = [
  "superhuman",
  "sanebox",
  "shortwave",
  "missive",
  "spark",
] as const;

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-email-assistant",
  pageTitle: `Best AI Email Assistant: ${RANKED_SLUGS.length + 1} Top Picks for 2026`,
  pageDescription:
    "We ranked 5 AI email assistants by how much inbox work they take off your plate. GAIA is our pick for triage, drafts, and follow-ups.",
  keywords: [
    "best AI email assistant",
    "AI email assistant",
    "best email AI",
    "Superhuman alternative",
    "SaneBox alternative",
    "Shortwave alternative",
    "AI inbox assistant",
    "best AI email assistant 2026",
  ],
  breadcrumbName: "Best AI Email Assistant",
  heading: `Best AI Email Assistant: Our Top ${RANKED_SLUGS.length + 1} for 2026`,
  subheading:
    "Ranked by how much inbox work each assistant takes off your plate, not by hype. GAIA is our pick. The rest are described fairly, with links to our full comparisons so you can check our work.",
  intro: (
    <>
      <p>
        Every email tool promises inbox zero. Most of them deliver a faster way
        to do the same work yourself: keyboard shortcuts, smart folders, AI
        compose. The inbox still fills, and you still empty it.
      </p>
      <p>
        That is the test behind this ranking. We looked at the AI email
        assistants people actually use, from Superhuman and SaneBox to
        Shortwave, Missive, and Spark, and asked one question: how much of your
        inbox does it handle without you? Tools that only speed you up rank
        below tools that take the work away.
      </p>
      <p>
        GAIA is our pick, and yes, we make it. It sits at number one for one
        reason: it is the only assistant on this list that triages urgency,
        drafts replies, creates tasks from threads, and chases follow-ups on its
        own. Every competitor below is described in its own words from our
        published comparisons, each linked so you can verify every claim.
      </p>
    </>
  ),
  tableAriaLabel: `Top ${RANKED_SLUGS.length + 1} AI email assistants ranked`,
  tableTitle: `The top ${RANKED_SLUGS.length + 1} at a glance`,
  gaiaBestFor: "Proactive inbox work",
  gaiaTake:
    "Triages urgency, drafts replies, and creates tasks across 50+ tools before you ask.",
  gaiaItemDescription:
    "Proactive productivity OS that triages email, drafts replies, and creates tasks across 50+ tools before you ask.",
  pickBody:
    "GAIA is a proactive productivity OS that manages your inbox autonomously. It triages messages by urgency, drafts context-aware replies, converts threads into tasks and calendar events, and chains those actions into cross-tool workflows spanning Gmail, Slack, Notion, and more than 50 integrations. It is open source, so you can inspect exactly how your data is handled.",
  pickCompareHref: "/compare/superhuman",
  pickCompareLabel: "See GAIA vs Superhuman head-to-head",
  pickAlternativeHref: "/alternative-to/superhuman",
  pickAlternativeLabel: "Best Superhuman alternative guide",
  rankedSlugs: RANKED_SLUGS,
  bestFor: {
    superhuman: "Blazing through Gmail and Outlook by keyboard",
    sanebox: "Filtering any inbox into smart folders",
    shortwave: "AI writing and summaries inside Gmail",
    missive: "Teams sharing one inbox",
    spark: "A smarter cross-platform inbox",
  },
  shortVersion: {
    superhuman: "The fastest email client in the world. You do email faster.",
    sanebox: "A proven filter that moves non-urgent mail aside. Never acts.",
    shortwave: "Best-in-class AI writing help and summaries, Gmail only.",
    missive:
      "Shared inboxes and in-thread chat. Collaboration, not automation.",
    spark: "AI compose and Smart Inbox everywhere. A client, not an agent.",
  },
  faqs: [
    {
      question: "What is the best AI email assistant right now?",
      answer:
        "There is no single best for everyone. Email clients such as Superhuman, Shortwave, and Spark make you faster at doing email yourself, while SaneBox quietly filters noise aside. GAIA is our pick because it removes the work instead of speeding it up: it triages urgency, drafts replies, creates tasks from threads, and schedules follow-ups before you ask.",
    },
    {
      question: "Superhuman vs GAIA: should I pick speed or delegation?",
      answer:
        "Pick Superhuman if you enjoy living in your inbox and want to process it faster through keyboard discipline and a premium client. Pick GAIA if you would rather process less of it: GAIA reads, triages, replies, and converts email into tasks and calendar events autonomously, then connects those actions to 50+ other tools. One makes you faster, the other makes email smaller.",
    },
    {
      question: "Can I use GAIA alongside Superhuman, Shortwave, or Spark?",
      answer:
        "Yes. They solve different problems and work well together. Keep your favorite client for reading and sending, and let GAIA handle the layer underneath: triaging urgency, drafting replies, extracting action items, and chasing follow-ups across your inbox, calendar, and task tools.",
    },
    {
      question: "Is GAIA really open source?",
      answer:
        "Yes. GAIA is an open-source AI assistant that works across Gmail, Slack, Notion, GitHub, Calendar, Todoist, Linear, and more than 50 tools in total. Unlike email clients tied to one inbox, it connects your whole stack and manages email, calendar, tasks, and multi-step workflows on your behalf.",
    },
  ],
  comparisonsTitle: "Every email comparison",
  alternativesTitle: "Every email alternative guide",
};

export function generateMetadata(): Metadata {
  return generateBestHubMetadata(CONFIG);
}

export default function BestAiEmailAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}

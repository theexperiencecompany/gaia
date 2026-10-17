import type { Metadata } from "next";

import BestAssistantHub, {
  type BestHubConfig,
} from "@/components/seo/BestAssistantHub";
import { generatePageMetadata } from "@/lib/seo";

const CONFIG: BestHubConfig = {
  pagePath: "/best-ai-email-assistant",
  pageTitle: "Best AI Email Assistant: 6 Top Picks for 2026",
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
  heading: "Best AI Email Assistant: Our Top 6 for 2026",
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
  tableAriaLabel: "Top 6 AI email assistants ranked",
  tableTitle: "The top 6 at a glance",
  gaiaBestFor: "Proactive inbox work",
  gaiaTake:
    "Triages urgency, drafts replies, and creates tasks across 50+ tools before you ask.",
  gaiaItemDescription:
    "Proactive productivity OS that triages email, drafts replies, and creates tasks across 50+ tools before you ask.",
  pickBody:
    "GAIA is a proactive productivity OS that manages your inbox autonomously. It triages messages by urgency, drafts context-aware replies, converts threads into tasks and calendar events, and chains those actions into cross-tool workflows spanning Gmail, Slack, Notion, and more than 50 integrations. Being open source, the whole mail pipeline is yours to inspect.",
  pickCompareHref: "/compare/superhuman",
  pickCompareLabel: "See GAIA vs Superhuman head-to-head",
  pickAlternativeHref: "/alternative-to/superhuman",
  pickAlternativeLabel: "Best Superhuman alternative guide",
  // GAIA excluded (it is row #1, "our pick"). Every slug must exist in
  // public/data/comparisons/{slug}.json. Missing slugs throw at render.
  rankedSlugs: ["superhuman", "sanebox", "shortwave", "missive", "spark"],
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
        "It depends on how much of email you want off your plate. Superhuman and Spark reward you every time you are inside the client, Shortwave adds strong AI drafting inside Gmail, SaneBox sifts noise on its own, and Missive covers shared team inboxes. If you would rather have the inbox processed for you, GAIA is our pick: it triages urgency, drafts replies, turns threads into tasks, and schedules follow-ups before you ask.",
    },
    {
      question: "Is GAIA an open-source email assistant?",
      answer:
        "Yes, and you can check that in the repo rather than on a feature page. The code that classifies your mail, drafts replies, and routes follow-ups is public, so you can review exactly how your inbox is handled before trusting it. It hooks into Gmail, Slack, Notion, GitHub, Calendar, Todoist, Linear, and more than 50 tools in total, which is also why work that starts in email lands in your calendar, tasks, and Slack without extra wiring.",
    },
    {
      question: "Superhuman vs GAIA: should I pick speed or delegation?",
      answer:
        "Superhuman invests everything in the person doing the work: keyboard-first discipline that turns incoming mail into a fast, satisfying flow. GAIA invests in replacing the work: reading what arrived, drafting the replies, converting threads into tasks and events, and chasing every follow-up on its own. Choose speed when you like email; choose delegation when you would rather spend the day doing something else.",
    },
    {
      question: "Can I keep Superhuman, Shortwave, or Spark alongside GAIA?",
      answer:
        "Yes, and that pairing is common. Keep the client you like for reading and composing mail; GAIA sits underneath it, deciding which threads matter, extracting action items, and syncing follow-ups into your tasks, calendar, and cross-tool workflows. One layer makes writing mail fast, the other makes remembering it unnecessary.",
    },
  ],
  comparisonsTitle: "Every email comparison",
  alternativesTitle: "Every email alternative guide",
};

export function generateMetadata(): Metadata {
  return generatePageMetadata({
    title: CONFIG.pageTitle,
    description: CONFIG.pageDescription,
    path: CONFIG.pagePath,
    keywords: CONFIG.keywords,
  });
}

export default function BestAiEmailAssistantPage() {
  return <BestAssistantHub config={CONFIG} />;
}

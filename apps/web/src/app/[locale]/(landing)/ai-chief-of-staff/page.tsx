import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import AiChiefOfStaffClient from "./AiChiefOfStaffClient";

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
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />
      <AiChiefOfStaffClient />
    </>
  );
}

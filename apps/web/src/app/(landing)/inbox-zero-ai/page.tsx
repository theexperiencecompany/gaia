import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import InboxZeroAiClient from "./InboxZeroAiClient";

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
      <InboxZeroAiClient />
    </>
  );
}

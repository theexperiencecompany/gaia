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
import OpenSourceAIClient from "./OpenSourceAIClient";
import { OPEN_SOURCE_FAQS, SELF_HOST_STEPS } from "./openSourceContent";

export const metadata: Metadata = generatePageMetadata({
  title: "Open Source AI Assistant: Self-Host Your Personal AI",
  description:
    "GAIA is the open source AI assistant that manages your email, calendar, tasks, and workflows. Fully self-hostable. Your data stays on your servers.",
  path: "/open-source-ai-assistant",
  keywords: [
    "open source AI assistant",
    "self-hosted AI assistant",
    "open source personal AI",
    "self-hosted productivity app",
    "open source AI agent",
    "privacy-first AI assistant",
    "FOSS AI assistant",
    "AI assistant self-host",
    "open source ChatGPT alternative",
    "self-hosted ChatGPT alternative",
  ],
});

export default function OpenSourceAIAssistantPage() {
  const webPageSchema = generateWebPageSchema(
    "Open Source AI Assistant: Self-Host Your Personal AI | GAIA",
    "GAIA is the open source AI assistant that manages your email, calendar, tasks, and workflows. Fully self-hostable. Your data stays on your servers.",
    `${siteConfig.url}/open-source-ai-assistant`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Open Source AI Assistant",
        url: `${siteConfig.url}/open-source-ai-assistant`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    {
      name: "Open Source AI Assistant",
      url: `${siteConfig.url}/open-source-ai-assistant`,
    },
  ]);

  const howToSchema = generateHowToSchema(
    "How to Self-Host GAIA Open Source AI Assistant",
    "Deploy GAIA on your own server in three steps using Docker Compose.",
    SELF_HOST_STEPS,
  );

  const faqSchema = generateFAQSchema(OPEN_SOURCE_FAQS);

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          howToSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />
      <header className="mx-auto max-w-5xl px-6 pt-36 text-center">
        <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
          Open Source AI Assistant
        </h1>
        <p className="mx-auto max-w-2xl text-xl text-zinc-400">
          Self-host your personal AI. GAIA manages your email, calendar, tasks
          and workflows, and your data stays on your servers.
        </p>
      </header>
      <OpenSourceAIClient />
    </>
  );
}

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

const PAGE_TITLE = "Self-Hosted AI Assistant: Source-Available, on Your Server";
const PAGE_DESCRIPTION =
  "Looking for an open source AI assistant? GAIA's code is public under PolyForm Noncommercial, so you can self-host it for personal use. See the Docker setup.";

export const metadata: Metadata = generatePageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
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
    PAGE_TITLE,
    PAGE_DESCRIPTION,
    `${siteConfig.url}/open-source-ai-assistant`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Self-Hosted AI Assistant",
        url: `${siteConfig.url}/open-source-ai-assistant`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    {
      name: "Self-Hosted AI Assistant",
      url: `${siteConfig.url}/open-source-ai-assistant`,
    },
  ]);

  const howToSchema = generateHowToSchema(
    "How to Self-Host the GAIA AI Assistant",
    "Deploy GAIA on your own server in three steps with the GAIA CLI and Docker.",
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
          Self-Hosted AI Assistant, Source Code Included
        </h1>
        <p className="mx-auto max-w-2xl text-xl text-zinc-400">
          Looking for an open source AI assistant you can run yourself? GAIA's
          full source is public under the PolyForm Noncommercial license, so you
          can self-host it free for personal use. It manages your email,
          calendar, tasks and workflows from databases on your own server.
        </p>
      </header>
      <OpenSourceAIClient />
    </>
  );
}

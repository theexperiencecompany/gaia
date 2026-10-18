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

export const metadata: Metadata = generatePageMetadata({
  title: "Open Source AI Assistant: Self-Host Your Personal AI",
  description:
    "GAIA is the open source AI assistant that manages your email, calendar, tasks, and workflows. Fully self-hostable. Your data stays on your servers. Free forever.",
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

const faqs = [
  {
    question: "Is GAIA really free to self-host?",
    answer:
      "Yes. GAIA is MIT-licensed open source software. You can deploy it on your own infrastructure with one command and use it indefinitely at no cost. There is no per-seat charge, no usage limits, and no expiring trial. You only pay for the compute you run it on.",
  },
  {
    question: "What data does GAIA store?",
    answer:
      "When self-hosted, GAIA stores data exclusively on your own servers: PostgreSQL for structured data, MongoDB for documents, Redis for caching, and ChromaDB for vector embeddings. Nothing is sent to GAIA's servers. You control every byte.",
  },
  {
    question: "Can I audit GAIA's code?",
    answer:
      "Absolutely. The full source code is on GitHub at github.com/theexperiencecompany/gaia. Every line of the backend, frontend, and agent logic is publicly readable. You can inspect exactly how your data is processed, stored, and used.",
  },
  {
    question: "What are the system requirements to self-host GAIA?",
    answer:
      "GAIA runs via Docker Compose. You need a Linux server (or macOS/Windows for local dev) with at least 8 GB RAM and Docker (the installer sets Docker up for you on Ubuntu and Debian). A VPS with 2 vCPUs and 8 GB RAM is enough for a single user. The full stack includes PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ, all orchestrated by Docker Compose.",
  },
];

const selfHostSteps = [
  {
    name: "Install the GAIA CLI",
    text: "Run `curl -fsSL https://heygaia.io/install.sh | sh`. It sets up Node.js if needed and installs the `gaia` command.",
  },
  {
    name: "Run gaia up",
    text: "Run `gaia up`. It installs Docker if it is missing, downloads GAIA's setup files and images, writes the configuration, and starts every service: the API, worker, databases, and message broker. No Git needed.",
  },
  {
    name: "Finish setup in the browser",
    text: "Open the address `gaia up` prints, create the admin account, and paste your AI provider key. GAIA is running on your server.",
  },
];

export default function OpenSourceAIAssistantPage() {
  const webPageSchema = generateWebPageSchema(
    "Open Source AI Assistant: Self-Host Your Personal AI | GAIA",
    "GAIA is the open source AI assistant that manages your email, calendar, tasks, and workflows. Fully self-hostable. Your data stays on your servers. Free forever.",
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
    selfHostSteps,
  );

  const faqSchema = generateFAQSchema(faqs);

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
      <OpenSourceAIClient />
    </>
  );
}

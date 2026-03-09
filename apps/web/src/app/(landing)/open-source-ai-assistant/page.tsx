import type { Metadata } from "next";
import Link from "next/link";

import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Open Source AI Assistant — Self-Host Your Personal AI | GAIA",
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
      "Yes. GAIA is MIT-licensed open source software. You can clone the repository, deploy it on your own infrastructure, and use it indefinitely at no cost. There is no per-seat charge, no usage limits, and no expiring trial. You only pay for the compute you run it on.",
  },
  {
    question: "What data does GAIA store?",
    answer:
      "When self-hosted, GAIA stores data exclusively on your own servers — PostgreSQL for structured data, MongoDB for documents, Redis for caching, and ChromaDB for vector embeddings. Nothing is sent to GAIA's servers. You control every byte.",
  },
  {
    question: "Can I audit GAIA's code?",
    answer:
      "Absolutely. The full source code is on GitHub at github.com/theexperiencecompany/gaia. Every line of the backend, frontend, and agent logic is publicly readable. You can inspect exactly how your data is processed, stored, and used.",
  },
  {
    question: "What are the system requirements to self-host GAIA?",
    answer:
      "GAIA runs via Docker Compose. You need a Linux server (or macOS/Windows for local dev) with at least 4GB RAM and Docker installed. A modern VPS with 2 vCPUs and 4GB RAM is sufficient for a single user. The full stack includes PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ — all orchestrated by Docker Compose.",
  },
];

const selfHostSteps = [
  {
    name: "Clone the repository",
    text: "Run `git clone https://github.com/theexperiencecompany/gaia.git` to get the full source code on your machine.",
  },
  {
    name: "Configure your environment",
    text: "Copy `.env.example` to `.env` in the `apps/api` directory. Add your LLM API key, OAuth credentials for Gmail/Calendar, and any other integrations you want to enable.",
  },
  {
    name: "Deploy with Docker Compose",
    text: "Run `cd infra/docker && docker compose up` to start all services — the API, worker, databases, and message broker — in one command. GAIA is running on your server.",
  },
];

const comparisonRows = [
  {
    feature: "Source code",
    gaia: "Open source (MIT)",
    chatgpt: "Closed source",
    copilot: "Closed source",
    notionAI: "Closed source",
  },
  {
    feature: "Self-hostable",
    gaia: "Yes — Docker Compose",
    chatgpt: "No",
    copilot: "No",
    notionAI: "No",
  },
  {
    feature: "Data location",
    gaia: "Your servers",
    chatgpt: "OpenAI's servers",
    copilot: "Microsoft's servers",
    notionAI: "Notion's servers",
  },
  {
    feature: "Pricing model",
    gaia: "Free (self-host) / cloud tier",
    chatgpt: "Per-message / subscription",
    copilot: "Per-seat subscription",
    notionAI: "Per-seat subscription",
  },
  {
    feature: "Email management",
    gaia: "Yes — full triage + drafts",
    chatgpt: "No",
    copilot: "Limited (Outlook only)",
    notionAI: "No",
  },
  {
    feature: "Calendar management",
    gaia: "Yes — schedule, reschedule",
    chatgpt: "No",
    copilot: "Yes (M365 only)",
    notionAI: "No",
  },
  {
    feature: "Proactive actions",
    gaia: "Yes — acts without prompting",
    chatgpt: "No",
    copilot: "Limited",
    notionAI: "No",
  },
  {
    feature: "Integrations",
    gaia: "50+ via MCP",
    chatgpt: "GPT plugins / limited",
    copilot: "M365 ecosystem",
    notionAI: "Notion only",
  },
];

export default function OpenSourceAIAssistantPage() {
  const webPageSchema = generateWebPageSchema(
    "Open Source AI Assistant — Self-Host Your Personal AI | GAIA",
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

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">Open Source AI Assistant</span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-400">
            MIT License — Free to self-host
          </div>
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            The Open Source AI Assistant That Manages Your Whole Work Life
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            GAIA is fully open source, self-hostable via Docker, and covers
            email, calendar, tasks, and 50+ integrations. Your data stays on
            your servers — always.
          </p>
        </header>

        {/* What makes GAIA different */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            What makes GAIA different from every other AI assistant
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl bg-zinc-800 p-6">
              <div className="mb-3 text-2xl">&#x1F512;</div>
              <h3 className="mb-2 text-lg font-semibold text-white">
                MIT Licensed
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                The entire codebase — backend, frontend, and agents — is
                published under the MIT license. Use it, fork it, modify it. No
                restrictions.
              </p>
            </div>
            <div className="rounded-2xl bg-zinc-800 p-6">
              <div className="mb-3 text-2xl">&#x1F4E6;</div>
              <h3 className="mb-2 text-lg font-semibold text-white">
                Self-Hostable via Docker
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                One `docker compose up` command brings up the entire stack. No
                complex cloud setup, no vendor lock-in. Run it on any VPS, home
                server, or cloud VM.
              </p>
            </div>
            <div className="rounded-2xl bg-zinc-800 p-6">
              <div className="mb-3 text-2xl">&#x1F4C1;</div>
              <h3 className="mb-2 text-lg font-semibold text-white">
                Data Stays on Your Servers
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Your emails, calendar events, tasks, and conversation history
                are stored in databases you own and control. Zero telemetry to
                GAIA's infrastructure.
              </p>
            </div>
            <div className="rounded-2xl bg-zinc-800 p-6">
              <div className="mb-3 text-2xl">&#x1F527;</div>
              <h3 className="mb-2 text-lg font-semibold text-white">
                No Vendor Lock-In
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Swap the LLM backend, add custom tools, modify agent behavior,
                or integrate internal systems. GAIA's architecture is designed
                for extensibility.
              </p>
            </div>
          </div>
        </section>

        {/* What it does */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            What GAIA actually does for you
          </h2>
          <ul className="space-y-3">
            {[
              "Triages your inbox — labels emails by urgency, drafts replies, archives noise",
              "Manages your calendar — schedules meetings, handles conflicts, sends invites",
              "Tracks your tasks — syncs with Todoist, Linear, GitHub Issues, and more",
              "Sends proactive briefings — your day's priorities at 7am, without asking",
              "Connects 50+ tools via MCP — Slack, Notion, HubSpot, GitHub, Google Workspace",
              "Runs automated workflows — recurring tasks, follow-ups, reports, on a schedule",
            ].map((item) => (
              <li key={item} className="flex items-start gap-3 text-zinc-300">
                <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Why open source matters */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-6 text-2xl font-semibold text-white">
            Why open source matters for an AI assistant
          </h2>
          <div className="space-y-5">
            <div>
              <h3 className="mb-1 font-semibold text-white">Privacy</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Closed AI assistants send your emails, calendar events, and work
                context to corporate servers for processing. With GAIA
                self-hosted, your data never leaves your infrastructure.
              </p>
            </div>
            <div>
              <h3 className="mb-1 font-semibold text-white">Customization</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Need a custom integration with your internal tools? Want to
                change how the agent reasons about your tasks? You have full
                access to the code — modify anything.
              </p>
            </div>
            <div>
              <h3 className="mb-1 font-semibold text-white">
                No per-seat pricing
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                ChatGPT charges per message. Copilot charges per seat.
                Self-hosted GAIA has no usage-based charges. Pay for compute,
                not for AI assistance.
              </p>
            </div>
            <div>
              <h3 className="mb-1 font-semibold text-white">Auditability</h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                You can read every line of code that processes your data. No
                black boxes, no hidden telemetry, no undisclosed data sharing.
              </p>
            </div>
          </div>
        </section>

        {/* Comparison table */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            GAIA (open source) vs closed AI assistants
          </h2>
          <ComparisonTable
            ariaLabel="GAIA open source vs closed AI assistants"
            columns={[
              {
                key: "feature",
                label: "Feature",
                headerClassName: "text-zinc-500",
                cellClassName: "font-medium text-zinc-300",
              },
              {
                key: "gaia",
                label: "GAIA",
                headerClassName: "text-primary",
                cellClassName: "text-emerald-400",
              },
              {
                key: "chatgpt",
                label: "ChatGPT",
                headerClassName: "text-zinc-400",
                cellClassName: "text-zinc-400",
              },
              {
                key: "copilot",
                label: "Copilot",
                headerClassName: "text-zinc-400",
                cellClassName: "text-zinc-400",
              },
              {
                key: "notionAI",
                label: "Notion AI",
                headerClassName: "text-zinc-400",
                cellClassName: "text-zinc-400",
              },
            ]}
            rows={comparisonRows}
          />
        </section>

        {/* How to self-host */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            How to self-host GAIA in 3 steps
          </h2>
          <p className="mb-8 text-zinc-400">
            No Kubernetes required. No cloud account needed. Just Docker.
          </p>
          <ol className="space-y-4">
            {selfHostSteps.map((step, index) => (
              <li
                key={step.name}
                className="flex items-start gap-4 rounded-2xl bg-zinc-800 p-5"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-sm font-semibold text-emerald-400">
                  {index + 1}
                </span>
                <div>
                  <p className="mb-1 font-semibold text-white">{step.name}</p>
                  <p className="text-sm leading-relaxed text-zinc-400">
                    {step.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <div className="mt-6 flex items-center gap-4">
            <Link
              href="https://github.com/theexperiencecompany/gaia"
              className="inline-flex items-center gap-2 rounded-2xl bg-zinc-800 px-5 py-3 text-sm font-medium text-white transition hover:bg-zinc-700"
              target="_blank"
              rel="noopener noreferrer"
            >
              View on GitHub &#x2197;
            </Link>
            <Link
              href="https://docs.heygaia.io"
              className="inline-flex items-center gap-2 rounded-2xl border border-zinc-700 px-5 py-3 text-sm font-medium text-zinc-300 transition hover:border-zinc-500 hover:text-white"
              target="_blank"
              rel="noopener noreferrer"
            >
              Read the docs &#x2197;
            </Link>
          </div>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <p className="mb-8 text-zinc-400">
            Common questions about self-hosting GAIA.
          </p>
          <FAQAccordion faqs={faqs} />
        </section>

        {/* Explore more */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            <Link
              href="/ai-chief-of-staff"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                AI Chief of Staff
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                See how GAIA acts as your proactive AI chief of staff — managing
                your entire workday autonomously.
              </p>
            </Link>
            <Link
              href="/inbox-zero-ai"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                Inbox Zero with AI
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                How GAIA automatically triages your Gmail and reaches inbox zero
                every day.
              </p>
            </Link>
            <Link
              href="/compare"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA vs Competitors
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                See detailed head-to-head comparisons of GAIA against other AI
                and productivity tools.
              </p>
            </Link>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}

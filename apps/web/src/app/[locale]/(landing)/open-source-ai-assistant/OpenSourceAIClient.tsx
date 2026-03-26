"use client";

import Link from "next/link";
import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import PersonaSEOSection from "@/features/landing/components/sections/PersonaSEOSection";

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

const differentiators = [
  {
    title: "MIT Licensed",
    description:
      "The entire codebase — backend, frontend, and agents — is published under the MIT license. Use it, fork it, modify it. No restrictions.",
  },
  {
    title: "Self-Hostable via Docker",
    description:
      "One `docker compose up` command brings up the entire stack. No complex cloud setup, no vendor lock-in. Run it on any VPS, home server, or cloud VM.",
  },
  {
    title: "Data Stays on Your Servers",
    description:
      "Your emails, calendar events, tasks, and conversation history are stored in databases you own and control. Zero telemetry to GAIA's infrastructure.",
  },
  {
    title: "No Vendor Lock-In",
    description:
      "Swap the LLM backend, add custom tools, modify agent behavior, or integrate internal systems. GAIA's architecture is designed for extensibility.",
  },
];

const checklistItems = [
  "Triages your inbox — labels emails by urgency, drafts replies, archives noise",
  "Manages your calendar — schedules meetings, handles conflicts, sends invites",
  "Tracks your tasks — syncs with Todoist, Linear, GitHub Issues, and more",
  "Sends proactive briefings — your day's priorities at 7am, without asking",
  "Connects 50+ tools via MCP — Slack, Notion, HubSpot, GitHub, Google Workspace",
  "Runs automated workflows — recurring tasks, follow-ups, reports, on a schedule",
];

const openSourceReasons = [
  {
    title: "Privacy",
    description:
      "Closed AI assistants send your emails, calendar events, and work context to corporate servers for processing. With GAIA self-hosted, your data never leaves your infrastructure.",
  },
  {
    title: "Customization",
    description:
      "Need a custom integration with your internal tools? Want to change how the agent reasons about your tasks? You have full access to the code — modify anything.",
  },
  {
    title: "No per-seat pricing",
    description:
      "ChatGPT charges per message. Copilot charges per seat. Self-hosted GAIA has no usage-based charges. Pay for compute, not for AI assistance.",
  },
  {
    title: "Auditability",
    description:
      "You can read every line of code that processes your data. No black boxes, no hidden telemetry, no undisclosed data sharing.",
  },
];

export default function OpenSourceAIClient() {
  return (
    <div className="w-full">
      {/* What makes GAIA different */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Open Source"
          headline="What makes GAIA different from every other AI assistant"
          description="GAIA is the only AI assistant that's fully open source, self-hostable, and designed to manage your entire work life — without sending your data anywhere."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <div className="grid gap-4 sm:grid-cols-2 text-left">
            {differentiators.map((item) => (
              <div key={item.title} className="rounded-2xl bg-zinc-800/60 p-6">
                <h3 className="mb-2 text-lg font-semibold text-white">
                  {item.title}
                </h3>
                <p className="text-sm leading-relaxed text-zinc-400">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* What GAIA does */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Capabilities"
          headline="What GAIA actually does for you"
          description="A proactive AI assistant that handles the repetitive work across every tool you use — so you can focus on what matters."
          integrations={[
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
            { id: "slack", label: "Slack" },
            { id: "notion", label: "Notion" },
            { id: "github", label: "GitHub" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <ul className="space-y-3 text-left">
            {checklistItems.map((item) => (
              <li key={item} className="flex items-start gap-3 text-zinc-300">
                <span className="mt-1 shrink-0 text-emerald-400">&#x2714;</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Why open source matters */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Why Open Source"
          headline="Why open source matters for an AI assistant"
          description="Privacy, auditability, and true ownership. The four pillars that make self-hosted GAIA fundamentally different from closed AI tools."
        />
        <div className="w-full max-w-3xl">
          <div className="rounded-3xl bg-zinc-800/60 p-8">
            <div className="space-y-6 text-left">
              {openSourceReasons.map((reason) => (
                <div key={reason.title}>
                  <h3 className="mb-1 font-semibold text-white">
                    {reason.title}
                  </h3>
                  <p className="text-sm leading-relaxed text-zinc-400">
                    {reason.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Comparison table */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Comparison"
          headline="GAIA (open source) vs closed AI assistants"
          description="See how GAIA stacks up against ChatGPT, Copilot, and Notion AI across the features that matter most."
        />
        <div className="w-full max-w-4xl overflow-x-auto">
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
        </div>
      </section>

      {/* How to self-host */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Self-Hosting"
          headline="How to self-host GAIA in 3 steps"
          description="No Kubernetes required. No cloud account needed. Just Docker. Get GAIA running on your own server in minutes."
          integrations={[{ id: "github", label: "GitHub" }]}
        />
        <div className="w-full max-w-3xl">
          <ol className="space-y-4 text-left">
            {selfHostSteps.map((step, index) => (
              <li
                key={step.name}
                className="flex items-start gap-4 rounded-2xl bg-zinc-800/60 p-5"
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
        </div>
      </section>

      {/* FAQ */}
      <section className="mx-auto w-full max-w-3xl px-6 py-20 sm:py-28">
        <h2 className="mb-2 text-center font-serif text-4xl font-normal text-white sm:text-5xl">
          Frequently asked questions
        </h2>
        <p className="mb-10 text-center text-zinc-400">
          Common questions about self-hosting GAIA.
        </p>
        <FAQAccordion faqs={faqs} />
      </section>

      {/* PersonaSEO section */}
      <PersonaSEOSection
        persona="Open Source Users"
        stats={[
          { value: "MIT", label: "open source license" },
          { value: "1 cmd", label: "docker compose up" },
          { value: "50+", label: "integrations" },
          { value: "free", label: "to self-host" },
        ]}
        painPoints={[
          "Closed AI assistants send your sensitive emails and work context to corporate servers with no visibility into how it's used.",
          "Per-seat and per-message pricing makes AI assistants prohibitively expensive for teams and power users.",
          "You can't audit, modify, or trust a black-box AI system with your most sensitive professional data.",
          "Vendor lock-in means your workflows break the moment a service changes pricing, shuts down, or deprecates an API.",
          "No way to integrate internal tools, custom data sources, or proprietary systems with closed platforms.",
        ]}
        features={differentiators}
        faqs={faqs}
        relatedRoles={[
          {
            href: "/ai-chief-of-staff",
            label: "AI Chief of Staff",
            description:
              "See how GAIA acts as your proactive AI chief of staff — managing your entire workday autonomously.",
          },
          {
            href: "/inbox-zero-ai",
            label: "Inbox Zero with AI",
            description:
              "How GAIA automatically triages your Gmail and reaches inbox zero every day.",
          },
          {
            href: "/compare",
            label: "GAIA vs Competitors",
            description:
              "See detailed head-to-head comparisons of GAIA against other AI and productivity tools.",
          },
        ]}
      />

      <FinalSection />
    </div>
  );
}

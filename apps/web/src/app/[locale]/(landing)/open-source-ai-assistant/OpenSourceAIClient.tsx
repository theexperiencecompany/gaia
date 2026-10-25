"use client";

import { ArrowUpRight01Icon, Tick02Icon } from "@icons";
import Link from "next/link";
import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import SectionHeader from "@/features/landing/components/demo/founders-demo/SectionHeader";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import PersonaSEOSection from "@/features/landing/components/sections/PersonaSEOSection";
import { OPEN_SOURCE_FAQS, SELF_HOST_STEPS } from "./openSourceContent";

const HOSTED_ASSISTANTS = [
  { key: "chatgpt", label: "ChatGPT" },
  { key: "copilot", label: "Copilot" },
  { key: "notionAI", label: "Notion AI" },
] as const;

type HostedAssistantKey = (typeof HOSTED_ASSISTANTS)[number]["key"];

function sameForEveryHostedAssistant(
  answer: string,
): Record<HostedAssistantKey, string> {
  return { chatgpt: answer, copilot: answer, notionAI: answer };
}

const comparisonRows = [
  {
    feature: "Source code",
    gaia: "Public (PolyForm Noncommercial)",
    ...sameForEveryHostedAssistant("Closed"),
  },
  {
    feature: "Self-hostable",
    gaia: "Yes, Docker via the GAIA CLI",
    ...sameForEveryHostedAssistant("No"),
  },
  {
    feature: "Where your data is stored",
    gaia: "Databases on your server",
    chatgpt: "OpenAI's servers",
    copilot: "Microsoft's servers",
    notionAI: "Notion's servers",
  },
  {
    feature: "Free to self-host",
    gaia: "Yes, for noncommercial use",
    ...sameForEveryHostedAssistant("No"),
  },
  {
    feature: "Bring your own LLM key",
    gaia: "Yes, OpenAI or Google Gemini",
    ...sameForEveryHostedAssistant("No"),
  },
  {
    feature: "Modify the agent's code",
    gaia: "Yes",
    ...sameForEveryHostedAssistant("No"),
  },
];

const differentiators = [
  {
    title: "Source-Available",
    description:
      "The entire codebase (backend, frontend and agents) is public under the PolyForm Noncommercial license. Read it, fork it and self-host it for personal and noncommercial use.",
  },
  {
    title: "Self-Hostable via Docker",
    description:
      "One command, `gaia up`, installs Docker if it is missing, writes the configuration and starts the whole stack. Run it on a laptop, a home server or any VPS.",
  },
  {
    title: "Your Data in Your Databases",
    description:
      "Email context, calendar events, tasks, memories and conversation history are stored in databases you own. Analytics and error reporting stay off unless you add your own keys.",
  },
  {
    title: "No Vendor Lock-In",
    description:
      "Pick your LLM provider, add custom MCP servers, change agent behavior or connect internal systems. You own the deployment and the code that runs it.",
  },
];

const checklistItems = [
  "Triages your inbox: labels emails by urgency, drafts replies, archives noise",
  "Manages your calendar: schedules meetings, handles conflicts, sends invites",
  "Tracks your tasks: syncs with Todoist, Linear, GitHub Issues, and more",
  "Sends proactive briefings: your day's priorities each morning, without asking",
  "Connects your tools: Slack, Notion, HubSpot, GitHub, Google Workspace, plus any MCP server you add",
  "Runs automated workflows: recurring tasks, follow-ups, reports, on a schedule",
];

const openSourceReasons = [
  {
    title: "Privacy",
    description:
      "Hosted assistants keep your email, calendar and work context on the vendor's servers. Self-hosted GAIA keeps it in your own databases; only the prompts for each request go to the LLM provider you chose, under your own account.",
  },
  {
    title: "Customization",
    description:
      "Need a custom integration with your internal tools? Want to change how the agent reasons about your tasks? You have the code. Modify anything for your own noncommercial use.",
  },
  {
    title: "No per-seat pricing",
    description:
      "Hosted assistants charge a subscription per user. Self-hosted GAIA has no seat or usage fee of its own: you pay for your server and your LLM provider's usage.",
  },
  {
    title: "Auditability",
    description:
      "You can read every line of code that processes your data and see exactly which external services it calls. No black boxes, no undisclosed data sharing.",
  },
];

const sourceAvailableFacts = [
  {
    title: "Open source vs source-available",
    description:
      "Open source licenses (MIT, Apache, GPL) allow any use, including commercial. GAIA's PolyForm Noncommercial license gives you the code, the right to modify it and the right to self-host it, but commercial use needs a separate license. For a personal assistant, the practical freedoms are the same.",
  },
  {
    title: "What stays on your server",
    description:
      "PostgreSQL, MongoDB, Redis, ChromaDB, RabbitMQ and per-user file storage all run in Docker on your machine, and memory embeddings are computed locally with no external API.",
  },
  {
    title: "What leaves your server",
    description:
      "Each request's prompt goes to your LLM provider (OpenAI or Google Gemini). Connected apps such as Gmail and Google Calendar are reached through Composio with your own key. Nothing is sent to GAIA's infrastructure.",
  },
  {
    title: "When GAIA is not the right fit",
    description:
      "If you need an assistant that runs fully offline on local models, or you want to resell or embed it commercially without a license, look elsewhere. GAIA needs a hosted LLM and is licensed for noncommercial use.",
  },
];

interface TitledCard {
  title: string;
  description: string;
}

function TitledCardGrid({ cards }: { readonly cards: readonly TitledCard[] }) {
  return (
    <div className="grid gap-4 text-left sm:grid-cols-2">
      {cards.map((card) => (
        <div key={card.title} className="rounded-2xl bg-zinc-800/60 p-6">
          <h3 className="mb-2 text-lg font-semibold text-white">
            {card.title}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {card.description}
          </p>
        </div>
      ))}
    </div>
  );
}

export default function OpenSourceAIClient() {
  return (
    <div className="w-full">
      {/* What makes GAIA different */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Source-Available"
          headline="A self-hosted AI assistant that does real work"
          description="Many open source AI assistant projects are chat interfaces for a model. GAIA is a full personal assistant you can run yourself: it manages email, calendar, tasks and workflows from databases on your own server."
          integrations={[
            { id: "github", label: "GitHub" },
            { id: "notion", label: "Notion" },
            { id: "slack", label: "Slack" },
            { id: "gmail", label: "Gmail" },
            { id: "googlecalendar", label: "Calendar" },
          ]}
        />
        <div className="w-full max-w-3xl">
          <TitledCardGrid cards={differentiators} />
        </div>
      </section>

      {/* What GAIA does */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Capabilities"
          headline="What GAIA actually does for you"
          description="A proactive AI assistant that handles the repetitive work across every tool you use, so you can focus on what matters."
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
                <Tick02Icon className="mt-1 h-4 w-4 shrink-0 text-emerald-400" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Why public source matters */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Why Self-Host"
          headline="Why public source code matters for an AI assistant"
          description="An assistant reads your email and acts in your accounts. Being able to read its code and choose where it runs changes how far you can trust it."
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

      {/* Source-available, plainly */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="The Fine Print"
          headline="What self-hosting GAIA actually means"
          description="The license, the data flow and the limits, stated plainly before you install anything."
        />
        <div className="w-full max-w-3xl">
          <TitledCardGrid cards={sourceAvailableFacts} />
        </div>
      </section>

      {/* Comparison table */}
      <section className="flex flex-col items-center px-6 py-20 text-center sm:py-28">
        <SectionHeader
          label="Comparison"
          headline="Self-hosted GAIA vs hosted AI assistants"
          description="How GAIA compares with ChatGPT, Copilot and Notion AI on ownership, hosting and control."
        />
        <div className="w-full max-w-4xl overflow-x-auto">
          <ComparisonTable
            ariaLabel="Self-hosted GAIA vs hosted AI assistants"
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
              ...HOSTED_ASSISTANTS.map((assistant) => ({
                ...assistant,
                headerClassName: "text-zinc-400",
                cellClassName: "text-zinc-400",
              })),
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
          description="No Kubernetes required. You need Docker, Node.js 20+ and an API key for OpenAI or Google Gemini."
          integrations={[{ id: "github", label: "GitHub" }]}
        />
        <div className="w-full max-w-3xl">
          <ol className="space-y-4 text-left">
            {SELF_HOST_STEPS.map((step, index) => (
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
              View on GitHub
              <ArrowUpRight01Icon className="h-4 w-4" />
            </Link>
            <Link
              href="https://docs.heygaia.io"
              className="inline-flex items-center gap-2 rounded-2xl border border-zinc-700 px-5 py-3 text-sm font-medium text-zinc-300 transition hover:border-zinc-500 hover:text-white"
              target="_blank"
              rel="noopener noreferrer"
            >
              Read the docs
              <ArrowUpRight01Icon className="h-4 w-4" />
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
        <FAQAccordion faqs={OPEN_SOURCE_FAQS} />
      </section>

      {/* PersonaSEO section */}
      <PersonaSEOSection
        persona="Open Source Users"
        stats={[
          { value: "Public", label: "source on GitHub" },
          { value: "1 cmd", label: "gaia up" },
          { value: "1 click", label: "OAuth integrations" },
          { value: "free", label: "to self-host" },
        ]}
        painPoints={[
          "Closed AI assistants send your sensitive emails and work context to corporate servers with no visibility into how it's used.",
          "Per-seat subscriptions make AI assistants expensive for teams and power users.",
          "You can't audit, modify, or trust a black-box AI system with your most sensitive professional data.",
          "Vendor lock-in means your workflows break the moment a service changes pricing, shuts down, or deprecates an API.",
          "No way to integrate internal tools, custom data sources, or proprietary systems with closed platforms.",
        ]}
        features={differentiators}
        faqs={OPEN_SOURCE_FAQS}
        relatedRoles={[
          {
            href: "/ai-chief-of-staff",
            label: "AI Chief of Staff",
            description:
              "See how GAIA acts as your proactive AI chief of staff, managing your entire workday autonomously.",
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

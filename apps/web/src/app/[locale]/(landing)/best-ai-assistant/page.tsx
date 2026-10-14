import type { Metadata } from "next";
import Link from "next/link";

import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import {
  getAllAlternatives,
  getAlternative,
} from "@/features/alternatives/data/alternativesData";
import {
  type ComparisonData,
  getAllComparisons,
  getComparison,
} from "@/features/comparisons/data/comparisonsData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

const PAGE_PATH = "/best-ai-assistant";
const PAGE_TITLE = "Best AI Assistant: 12 Top Picks for 2026";
const PAGE_DESCRIPTION =
  "We ranked 12 AI assistants by how much real work they take off your plate. GAIA is our pick for email, calendar, and tasks. Compare all 12.";

export function generateMetadata(): Metadata {
  return generatePageMetadata({
    title: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    path: PAGE_PATH,
    keywords: [
      "best AI assistant",
      "best ChatGPT alternative",
      "ChatGPT alternative",
      "Claude alternative",
      "Gemini alternative",
      "AI assistant comparison",
      "best AI assistant 2026",
      "proactive AI assistant",
    ],
  });
}

/**
 * Ranked competitors, GAIA excluded (it is row #1, "our pick").
 * Every slug must exist in `public/data/comparisons/{slug}.json`.
 * Copy below (taglines, descriptions, verdicts) is reused verbatim from
 * those files. No invented prices, specs, or claims.
 */
const RANKED_SLUGS = [
  "chatgpt",
  "claude",
  "gemini",
  "copilot",
  "perplexity",
  "grok",
  "deepseek",
  "google-assistant",
  "lindy-ai",
  "cursor-ai",
  "notion-ai",
] as const;

const BEST_FOR: Record<string, string> = {
  chatgpt: "On-demand answers, drafts, and code",
  claude: "Reasoning and long-form writing",
  gemini: "Work inside Google Workspace",
  copilot: "Work inside Microsoft 365",
  perplexity: "Research with citations",
  grok: "Real-time answers with X data",
  deepseek: "Low-cost coding model",
  "google-assistant": "Voice commands and smart home",
  "lindy-ai": "Small agents for specific tasks",
  "cursor-ai": "AI-assisted code editing",
  "notion-ai": "Writing inside Notion",
};

const SHORT_VERSION: Record<string, string> = {
  chatgpt: "The most recognized chatbot. Reactive: it waits for your prompt.",
  claude: "Excels at reasoning and conversation inside a chat window.",
  gemini: "Makes Gmail, Docs, and Sheets smarter. Stays inside Google.",
  copilot: "AI across Word, Excel, Teams, and Outlook.",
  perplexity: "AI-powered search and research. Does not run your workflow.",
  grok: "Conversational AI with live social and news intelligence.",
  deepseek: "Open-weight LLM with strong coding and free API access.",
  "google-assistant":
    "Voice-first help and quick answers, not deep productivity work.",
  "lindy-ai": "Focused AI agents for specific tasks, not one unified system.",
  "cursor-ai":
    "An AI-first editor for code. GAIA covers everything outside it.",
  "notion-ai": "Writes and summarizes within your Notion workspace.",
};

const FAQS = [
  {
    question: "What is the best AI assistant right now?",
    answer:
      "There is no single best for everyone. Chatbots such as ChatGPT and Claude wait for your prompts and answer inside a conversation window, while GAIA monitors your email, calendar, and tasks and acts before you ask. If most of your day is email, meetings, and follow-ups, a proactive assistant takes more off your plate than a reactive chatbot.",
  },
  {
    question: "What is the best ChatGPT alternative for productivity?",
    answer:
      "GAIA is our pick for an open-source ChatGPT alternative. ChatGPT answers questions, drafts text, and writes code on demand, but it will not proactively manage your inbox or automate workflows. GAIA monitors your email, calendar, and tasks and acts before you ask, with a free tier available.",
  },
  {
    question: "Is GAIA really open source?",
    answer:
      "Yes. GAIA is an open-source AI assistant that works across Gmail, Slack, Notion, GitHub, Calendar, Todoist, Linear, and more than 50 tools in total. Unlike assistants tied to one suite, it connects your whole stack and manages email, calendar, tasks, and multi-step workflows on your behalf.",
  },
  {
    question: "Can I use GAIA alongside ChatGPT or Claude?",
    answer:
      "Yes. They solve different problems and work well together. Use ChatGPT or Claude for deep reasoning, content creation, and analytical tasks inside conversations, and use GAIA to run your actual workflow: triaging email, managing your calendar, keeping tasks current, and automating work across your tools.",
  },
  {
    question:
      "Which AI assistant should teams on Google Workspace or Microsoft 365 pick?",
    answer:
      "Choose Gemini if your work lives primarily in Google Workspace and you want AI inside Gmail, Docs, and Sheets. Choose Microsoft Copilot if your organization is standardized on Microsoft 365 with Word, Excel, and Teams. Choose GAIA if your tools span beyond one suite and you want one proactive assistant orchestrating email, calendar, tasks, and workflows across all of them.",
  },
];

interface RankedPick {
  readonly data: ComparisonData;
  readonly hasAlternativePage: boolean;
}

export default async function BestAiAssistantPage() {
  const [picks, allComparisons, allAlternatives] = await Promise.all([
    Promise.all(
      RANKED_SLUGS.map(async (slug): Promise<RankedPick | undefined> => {
        const data = await getComparison(slug);
        if (!data) return undefined;
        const alternative = await getAlternative(slug);
        return { data, hasAlternativePage: alternative !== undefined };
      }),
    ),
    getAllComparisons(),
    getAllAlternatives(),
  ]);

  const ranked: RankedPick[] = picks.filter(
    (p): p is RankedPick => p !== undefined,
  );

  const sortedComparisons = [...allComparisons].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
  const sortedAlternatives = [...allAlternatives].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  const pageUrl = `${siteConfig.url}${PAGE_PATH}`;

  const webPageSchema = generateWebPageSchema(
    PAGE_TITLE,
    PAGE_DESCRIPTION,
    pageUrl,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Best AI Assistant", url: pageUrl },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Best AI Assistant", url: pageUrl },
  ]);

  const itemListSchema = generateItemListSchema(
    [
      {
        name: "GAIA (our pick)",
        url: siteConfig.url,
        description:
          "Proactive productivity OS that monitors email, calendar, and tasks across 50+ tools and acts before you ask.",
      },
      ...ranked.map((pick) => ({
        name: `GAIA vs ${pick.data.name}`,
        url: `${siteConfig.url}/compare/${pick.data.slug}`,
        description: pick.data.tagline,
      })),
    ],
    "Article",
  );

  const faqSchema = generateFAQSchema(FAQS);

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          itemListSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">Best AI Assistant</span>
        </nav>

        <header className="mb-12">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            Best AI Assistant: Our Top 12 for 2026
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            Ranked by how much real work each assistant takes off your plate,
            not by hype. GAIA is our pick. The rest are described fairly, with
            links to our full comparisons so you can check our work.
          </p>
        </header>

        <section className="mb-16 space-y-5 text-lg leading-relaxed text-zinc-300">
          <p>
            We built GAIA because chatbots wait. You prompt, they answer, and
            the work of your day still sits in your inbox. A great assistant
            should do the opposite: notice what needs doing and handle it before
            you ask.
          </p>
          <p>
            That is the test behind this ranking. We looked at the AI assistants
            people actually use, from ChatGPT and Claude to Gemini, Copilot, and
            Perplexity, and asked one question: how much of your real work does
            it take off your plate? Tools that only answer rank below tools that
            act.
          </p>
          <p>
            GAIA is our pick, and yes, we make it. It sits at number one for one
            reason: it is the only assistant on this list that monitors your
            email, calendar, and tasks across more than 50 tools and acts on its
            own. Every competitor below is described in its own words from our
            published comparisons, each linked so you can verify every claim.
          </p>
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            The top 12 at a glance
          </h2>
          <ComparisonTable
            ariaLabel="Top 12 AI assistants ranked"
            columns={[
              {
                key: "rank",
                label: "#",
                headerClassName: "text-zinc-500",
                cellClassName: "font-medium text-zinc-300",
              },
              {
                key: "assistant",
                label: "Assistant",
                headerClassName: "text-primary",
                cellClassName: "font-medium text-white",
              },
              {
                key: "bestFor",
                label: "Best for",
                headerClassName: "text-zinc-500",
                cellClassName: "text-zinc-300",
              },
              {
                key: "take",
                label: "The short version",
                headerClassName: "text-zinc-500",
                cellClassName: "text-zinc-400",
              },
            ]}
            rows={[
              {
                rank: "1",
                assistant: "GAIA (our pick)",
                bestFor: "Proactive daily work",
                take: "Monitors email, calendar, and tasks across 50+ tools and acts before you ask.",
              },
              ...ranked.map((pick, index) => ({
                rank: String(index + 2),
                assistant: pick.data.name,
                bestFor: BEST_FOR[pick.data.slug] ?? pick.data.tagline,
                take: SHORT_VERSION[pick.data.slug] ?? pick.data.tagline,
              })),
            ]}
          />
        </section>

        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-white">
            Our pick: GAIA
          </h2>
          <p className="mb-4 text-lg leading-relaxed text-zinc-300">
            GAIA is a proactive productivity OS that manages your digital life
            autonomously. It monitors email, calendar, and tools around the
            clock and takes action before you ask, with more than 50 native
            integrations including Gmail, Slack, Notion, GitHub, Calendar,
            Todoist, and Linear. It is open source, so you can inspect exactly
            how your data is handled.
          </p>
          <div className="flex flex-wrap gap-4 text-sm">
            <Link
              href="/compare/chatgpt"
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              See GAIA vs ChatGPT head-to-head
            </Link>
            <Link
              href="/alternative-to/chatgpt"
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              Best ChatGPT alternative guide
            </Link>
          </div>
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            The 11 runners-up, in order
          </h2>
          <ol className="mb-10 space-y-2 text-zinc-400">
            {ranked.map((pick, index) => (
              <li key={pick.data.slug}>
                <span className="mr-2 text-zinc-500">{index + 2}.</span>
                <a
                  href={`#pick-${pick.data.slug}`}
                  className="underline underline-offset-2 hover:text-zinc-200"
                >
                  {pick.data.name}
                </a>
              </li>
            ))}
          </ol>

          <div className="space-y-10">
            {ranked.map((pick, index) => (
              <section
                key={pick.data.slug}
                id={`pick-${pick.data.slug}`}
                className="scroll-mt-32 rounded-3xl bg-zinc-800 p-8"
              >
                <p className="mb-1 text-sm text-zinc-500">#{index + 2} of 12</p>
                <h3 className="mb-1 text-2xl font-semibold text-white">
                  {pick.data.name}
                </h3>
                <p className="mb-4 text-sm text-zinc-500">
                  {pick.data.tagline}
                </p>
                <p className="mb-4 leading-relaxed text-zinc-300">
                  {pick.data.description}
                </p>
                <p className="mb-6 leading-relaxed text-zinc-400">
                  {pick.data.verdict}
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <Link
                    href={`/compare/${pick.data.slug}`}
                    className="text-zinc-300 underline underline-offset-2 hover:text-white"
                  >
                    GAIA vs {pick.data.name}: full comparison
                  </Link>
                  {pick.hasAlternativePage && (
                    <Link
                      href={`/alternative-to/${pick.data.slug}`}
                      className="text-zinc-300 underline underline-offset-2 hover:text-white"
                    >
                      Best {pick.data.name} alternative guide
                    </Link>
                  )}
                </div>
              </section>
            ))}
          </div>
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Common questions
          </h2>
          <FAQAccordion faqs={FAQS} />
        </section>

        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            Every GAIA comparison
          </h2>
          <p className="mb-6 leading-relaxed text-zinc-400">
            We publish a full head-to-head for each tool below. Start from the{" "}
            <Link
              href="/compare"
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              comparisons hub
            </Link>{" "}
            or jump straight in:
          </p>
          <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
            {sortedComparisons.map((comparison) => (
              <li key={comparison.slug} className="break-inside-avoid">
                <Link
                  href={`/compare/${comparison.slug}`}
                  className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
                >
                  GAIA vs {comparison.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            Every alternative guide
          </h2>
          <p className="mb-6 leading-relaxed text-zinc-400">
            Migration-focused guides with fit scores and switch steps. Browse
            the{" "}
            <Link
              href="/alternative-to"
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              alternatives hub
            </Link>{" "}
            or jump straight in:
          </p>
          <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
            {sortedAlternatives.map((alternative) => (
              <li key={alternative.slug} className="break-inside-avoid">
                <Link
                  href={`/alternative-to/${alternative.slug}`}
                  className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
                >
                  Best {alternative.name} alternative
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </article>
      <FinalSection />
    </>
  );
}

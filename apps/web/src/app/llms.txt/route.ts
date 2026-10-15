/**
 * GET /llms.txt — crawler/LLM feed of GAIA's public pages.
 *
 * Previously built on next-llms-txt auto-discovery, which walks
 * `src/app/[locale]/(landing)` with fs at request time. That source tree does
 * not exist on Cloudflare Workers (OpenNext), so production returned a
 * header with zero page links. This route instead enumerates pages from the
 * same static data getters the sitemap uses — no fs in the request path, only
 * the feature-data loader (fs at build time, ASSETS binding at the edge).
 */

import { getAllAlternatives } from "@/features/alternatives/data/alternativesData";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getAllPersonas } from "@/features/personas/data/personasData";
import { siteConfig } from "@/lib/seo";

export const revalidate = 3600;

const BASE_URL = siteConfig.url;

interface LlmsEntry {
  title: string;
  url: string;
  description?: string;
}

/** Key landing pages not covered by the data-driven sections below. */
const STATIC_PAGES: LlmsEntry[] = [
  {
    title: siteConfig.name,
    url: BASE_URL,
    description: siteConfig.description,
  },
  {
    title: "Features",
    url: `${BASE_URL}/features`,
    description:
      "GAIA features: email triage, calendar automation, todos, workflows and 50+ integrations.",
  },
  {
    title: "Pricing",
    url: `${BASE_URL}/pricing`,
    description:
      "GAIA pricing: free tier and Pro plans for your personal AI assistant.",
  },
  {
    title: "Download",
    url: `${BASE_URL}/download`,
    description: "Download GAIA for web, desktop and mobile.",
  },
  {
    title: "Marketplace",
    url: `${BASE_URL}/marketplace`,
    description: "Browse GAIA integrations and community workflows.",
  },
  {
    title: "Use cases",
    url: `${BASE_URL}/use-cases`,
    description: "Ready-made GAIA workflows for email, calendar and tasks.",
  },
  {
    title: "Blog",
    url: `${BASE_URL}/blog`,
    description: "GAIA blog: productivity, AI assistants and automation.",
  },
  {
    title: "Learn: AI glossary",
    url: `${BASE_URL}/learn`,
    description:
      "Plain-language definitions of AI and productivity concepts, and how GAIA uses them.",
  },
  {
    title: "Compare AI assistants",
    url: `${BASE_URL}/compare`,
    description:
      "Side-by-side comparisons of GAIA with other AI assistants and productivity tools.",
  },
  {
    title: "GAIA as an alternative",
    url: `${BASE_URL}/alternative-to`,
    description:
      "Why people switch to GAIA from other AI assistants and productivity apps.",
  },
  {
    title: "Automate your tools",
    url: `${BASE_URL}/automate`,
    description: "Guides for connecting pairs of tools with GAIA automations.",
  },
  {
    title: "Who GAIA helps",
    url: `${BASE_URL}/for`,
    description:
      "How founders, developers, sales teams and more use GAIA as their AI assistant.",
  },
  {
    title: "Best AI assistant",
    url: `${BASE_URL}/best-ai-assistant`,
    description: "What makes GAIA the best AI assistant for getting work done.",
  },
  {
    title: "Best AI email assistant",
    url: `${BASE_URL}/best-ai-email-assistant`,
    description:
      "GAIA ranked against Superhuman, SaneBox, Shortwave, Missive and Spark.",
  },
  {
    title: "Best AI calendar assistant",
    url: `${BASE_URL}/best-ai-calendar-assistant`,
    description:
      "GAIA ranked against Motion, Reclaim, Sunsama, Akiflow and Clockwise.",
  },
  {
    title: "Open-source AI assistant",
    url: `${BASE_URL}/open-source-ai-assistant`,
    description:
      "GAIA is an open-source personal AI assistant you can self-host.",
  },
  {
    title: "AI chief of staff",
    url: `${BASE_URL}/ai-chief-of-staff`,
    description:
      "GAIA as your AI chief of staff: inbox, calendar and follow-ups handled.",
  },
  {
    title: "Inbox zero with AI",
    url: `${BASE_URL}/inbox-zero-ai`,
    description: "Reach inbox zero with GAIA's AI email triage and drafting.",
  },
  {
    title: "FAQ",
    url: `${BASE_URL}/faq`,
    description: "Frequently asked questions about GAIA.",
  },
  {
    title: "About",
    url: `${BASE_URL}/about`,
    description: "GAIA's mission and the team behind it.",
  },
  {
    title: "Manifesto",
    url: `${BASE_URL}/manifesto`,
    description: "Why GAIA exists: a personal AI assistant for everyone.",
  },
  {
    title: "Contact",
    url: `${BASE_URL}/contact`,
    description: "Get in touch with the GAIA team.",
  },
];

/** Collapse whitespace so titles/descriptions stay on one markdown line. */
function oneLine(value: string): string {
  return value
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Escape square brackets so titles can't break the `[title](url)` syntax. */
function escapeTitle(value: string): string {
  return oneLine(value).replaceAll("[", "(").replaceAll("]", ")");
}

function toLine(entry: LlmsEntry): string {
  const description = entry.description
    ? `: ${oneLine(entry.description)}`
    : "";
  return `- [${escapeTitle(entry.title)}](${entry.url})${description}`;
}

function section(heading: string, entries: LlmsEntry[]): string[] {
  const sorted = [...entries].sort((a, b) => a.title.localeCompare(b.title));
  return [`## ${heading}`, "", ...sorted.map(toLine), ""];
}

async function buildBody(): Promise<string> {
  const [terms, comparisons, alternatives, combos, personas] =
    await Promise.all([
      getAllGlossaryTerms(),
      getAllComparisons(),
      getAllAlternatives(),
      getAllCombos(),
      getAllPersonas(),
    ]);

  // Mirror the sitemap: entries with a canonicalSlug are near-duplicates
  // whose canonical points at the primary entry — list the primary only.
  const learn = terms
    .filter((term) => !term.canonicalSlug)
    .map(
      (term): LlmsEntry => ({
        title: term.metaTitle,
        url: `${BASE_URL}/learn/${term.slug}`,
        description: term.metaDescription,
      }),
    );

  const compare = comparisons.map(
    (comparison): LlmsEntry => ({
      title: comparison.metaTitle,
      url: `${BASE_URL}/compare/${comparison.slug}`,
      description: comparison.metaDescription,
    }),
  );

  const alternativeTo = alternatives.map(
    (alternative): LlmsEntry => ({
      title: alternative.metaTitle,
      url: `${BASE_URL}/alternative-to/${alternative.slug}`,
      description: alternative.metaDescription,
    }),
  );

  const automate = combos
    .filter((combo) => !combo.canonicalSlug)
    .map(
      (combo): LlmsEntry => ({
        title: combo.metaTitle,
        url: `${BASE_URL}/automate/${combo.slug}`,
        description: combo.metaDescription,
      }),
    );

  const whoUses = personas.map(
    (persona): LlmsEntry => ({
      title: persona.metaTitle,
      url: `${BASE_URL}/for/${persona.slug}`,
      description: persona.metaDescription,
    }),
  );

  return [
    `# ${siteConfig.short_name}`,
    "",
    `> ${siteConfig.description}`,
    "",
    ...section("Main pages", STATIC_PAGES),
    ...section("Learn: AI glossary", learn),
    ...section("Compare: GAIA vs alternatives", compare),
    ...section("Switch to GAIA", alternativeTo),
    ...section("Automate: connect your tools", automate),
    ...section("Who GAIA helps", whoUses),
  ].join("\n");
}

export async function GET(): Promise<Response> {
  let body: string;
  try {
    body = await buildBody();
  } catch (error) {
    // A data load failure must not 500 the feed: crawlers still get the
    // header plus the key landing pages.
    console.error("Failed to build llms.txt, serving static pages:", error);
    body = [
      `# ${siteConfig.short_name}`,
      "",
      `> ${siteConfig.description}`,
      "",
      ...section("Main pages", STATIC_PAGES),
    ].join("\n");
  }
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

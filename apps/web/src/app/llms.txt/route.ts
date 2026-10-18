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
  name: string;
  url: string;
  notes?: string;
}

/** Key landing pages not covered by the data-driven sections below. */
const STATIC_PAGES: LlmsEntry[] = [
  {
    name: siteConfig.name,
    url: BASE_URL,
    notes: siteConfig.description,
  },
  {
    name: "Features",
    url: `${BASE_URL}/features`,
    notes:
      "GAIA features: email triage, calendar automation, todos, workflows and integrations across your tools.",
  },
  {
    name: "Pricing",
    url: `${BASE_URL}/pricing`,
    notes:
      "GAIA pricing: hosted GAIA is one paid Pro plan; self-hosting is free for non-commercial use.",
  },
  {
    name: "Download",
    url: `${BASE_URL}/download`,
    notes: "Download GAIA for web, desktop and mobile.",
  },
  {
    name: "Marketplace",
    url: `${BASE_URL}/marketplace`,
    notes: "Browse GAIA integrations and community workflows.",
  },
  {
    name: "Use cases",
    url: `${BASE_URL}/use-cases`,
    notes: "Ready-made GAIA workflows for email, calendar and tasks.",
  },
  {
    name: "Blog",
    url: `${BASE_URL}/blog`,
    notes: "GAIA blog: productivity, AI assistants and automation.",
  },
  {
    name: "Learn: AI glossary",
    url: `${BASE_URL}/learn`,
    notes:
      "Plain-language definitions of AI and productivity concepts, and how GAIA uses them.",
  },
  {
    name: "Compare AI assistants",
    url: `${BASE_URL}/compare`,
    notes:
      "Side-by-side comparisons of GAIA with other AI assistants and productivity tools.",
  },
  {
    name: "GAIA as an alternative",
    url: `${BASE_URL}/alternative-to`,
    notes:
      "Why people switch to GAIA from other AI assistants and productivity apps.",
  },
  {
    name: "Automate your tools",
    url: `${BASE_URL}/automate`,
    notes: "Guides for connecting pairs of tools with GAIA automations.",
  },
  {
    name: "Who GAIA helps",
    url: `${BASE_URL}/for`,
    notes:
      "How founders, developers, sales teams and more use GAIA as their AI assistant.",
  },
  {
    name: "Best AI assistant",
    url: `${BASE_URL}/best-ai-assistant`,
    notes: "What makes GAIA the best AI assistant for getting work done.",
  },
  {
    name: "Best AI email assistant",
    url: `${BASE_URL}/best-ai-email-assistant`,
    notes:
      "GAIA ranked against Superhuman, SaneBox, Shortwave, Missive and Spark.",
  },
  {
    name: "Best AI calendar assistant",
    url: `${BASE_URL}/best-ai-calendar-assistant`,
    notes:
      "GAIA ranked against Motion, Reclaim, Sunsama, Akiflow and Clockwise.",
  },
  {
    name: "Open-source AI assistant",
    url: `${BASE_URL}/open-source-ai-assistant`,
    notes:
      "GAIA's code is source-available (PolyForm Noncommercial) and self-hostable.",
  },
  {
    name: "AI chief of staff",
    url: `${BASE_URL}/ai-chief-of-staff`,
    notes:
      "GAIA as your AI chief of staff: inbox, calendar and follow-ups handled.",
  },
  {
    name: "Inbox zero with AI",
    url: `${BASE_URL}/inbox-zero-ai`,
    notes: "Reach inbox zero with GAIA's AI email triage and drafting.",
  },
  {
    name: "Best AI executive assistant apps",
    url: `${BASE_URL}/best-ai-executive-assistant`,
    notes:
      "GAIA ranked against Copilot, Superhuman, Lindy, Motion and other EA tools.",
  },
  {
    name: "AI assistant on WhatsApp, Telegram and iMessage",
    url: `${BASE_URL}/ai-assistant-whatsapp-telegram-imessage`,
    notes: "What GAIA does when you text it, and how to link each chat app.",
  },
  {
    name: "AI assistant with memory",
    url: `${BASE_URL}/ai-assistant-with-memory`,
    notes: "What GAIA remembers about you, and how to view, edit or delete it.",
  },
  {
    name: "AI assistant like Jarvis",
    url: `${BASE_URL}/ai-assistant-like-jarvis`,
    notes:
      "Proactive workflows, voice, wake word and desktop app, and the limits.",
  },
  {
    name: "AI assistant that can see your screen",
    url: `${BASE_URL}/ai-assistant-that-can-see-your-screen`,
    notes: "How GAIA's desktop app takes and reads screenshots.",
  },
  {
    name: "AI assistant that uses your computer",
    url: `${BASE_URL}/ai-assistant-that-uses-your-computer`,
    notes:
      "GAIA's desktop actions and cloud browser tasks, and what it cannot do.",
  },
  {
    name: "How to use AI as a personal assistant",
    url: `${BASE_URL}/how-to-use-ai-as-a-personal-assistant`,
    notes: "Step-by-step setup of GAIA as a personal assistant.",
  },
  {
    name: "FAQ",
    url: `${BASE_URL}/faq`,
    notes: "Frequently asked questions about GAIA.",
  },
  {
    name: "About",
    url: `${BASE_URL}/about`,
    notes: "GAIA's mission and the team behind it.",
  },
  {
    name: "Manifesto",
    url: `${BASE_URL}/manifesto`,
    notes: "Why GAIA exists: a personal AI assistant for everyone.",
  },
  {
    name: "Contact",
    url: `${BASE_URL}/contact`,
    notes: "Get in touch with the GAIA team.",
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
  const notes = entry.notes ? `: ${oneLine(entry.notes)}` : "";
  return `- [${escapeTitle(entry.name)}](${entry.url})${notes}`;
}

function section(heading: string, entries: LlmsEntry[]): string[] {
  const sorted = [...entries].sort((a, b) => a.name.localeCompare(b.name));
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

  // _slugs.json is the live page set: consolidated victims are excluded
  // there (they 308 via canonical-redirects.mjs), so no marker filtering here.
  const learn = terms.map(
    (term): LlmsEntry => ({
      name: term.metaTitle,
      url: `${BASE_URL}/learn/${term.slug}`,
      notes: term.metaDescription,
    }),
  );

  const compare = comparisons.map(
    (comparison): LlmsEntry => ({
      name: comparison.metaTitle,
      url: `${BASE_URL}/compare/${comparison.slug}`,
      notes: comparison.metaDescription,
    }),
  );

  const alternativeTo = alternatives.map(
    (alternative): LlmsEntry => ({
      name: alternative.metaTitle,
      url: `${BASE_URL}/alternative-to/${alternative.slug}`,
      notes: alternative.metaDescription,
    }),
  );

  const automate = combos.map(
    (combo): LlmsEntry => ({
      name: combo.metaTitle,
      url: `${BASE_URL}/automate/${combo.slug}`,
      notes: combo.metaDescription,
    }),
  );

  const whoUses = personas.map(
    (persona): LlmsEntry => ({
      name: persona.metaTitle,
      url: `${BASE_URL}/for/${persona.slug}`,
      notes: persona.metaDescription,
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
  return new Response(await buildBody(), {
    status: 200,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

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
import { MARKETING_PAGES } from "@/lib/marketingPages";
import { siteConfig } from "@/lib/seo";

export const revalidate = 3600;

const BASE_URL = siteConfig.url;

interface LlmsEntry {
  name: string;
  url: string;
  notes?: string;
}

const STATIC_PAGES: LlmsEntry[] = MARKETING_PAGES.map((page) => ({
  name: page.title,
  url: `${BASE_URL}${page.path}`,
  notes: page.description,
}));

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

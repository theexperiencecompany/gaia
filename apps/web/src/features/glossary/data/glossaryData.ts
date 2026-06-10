/**
 * Glossary terms — `/learn/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/glossary/{slug}.json`
 * (regenerate via `pnpm tsx scripts/extract-static-data.ts`). At Cloudflare
 * runtime they are fetched via the ASSETS binding instead of being bundled
 * into handler.mjs.
 */

import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";

export interface GlossaryTerm {
  slug: string;
  term: string;
  metaTitle: string;
  metaDescription: string;
  definition: string;
  extendedDescription: string;
  keywords: string[];
  category: string;
  howGaiaUsesIt: string;
  relatedTerms: string[];
  faqs: Array<{ question: string; answer: string }>;
  /** When set, this page's canonical points to /learn/{canonicalSlug} — concentrates PageRank on the primary entry. */
  canonicalSlug?: string;
  /** Slugs of comparison pages that are genuinely related to this term (e.g. tools that implement the concept). */
  relatedComparisons?: string[];
}

const FEATURE = "glossary";

export async function getGlossaryTerm(
  slug: string,
): Promise<GlossaryTerm | undefined> {
  return getFeatureEntry<GlossaryTerm>(FEATURE, slug);
}

export async function getAllGlossaryTermSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

export async function getAllGlossaryTerms(): Promise<GlossaryTerm[]> {
  return getAllFeatureEntries<GlossaryTerm>(FEATURE);
}

export async function getGlossaryTermsByCategory(
  category: string,
): Promise<GlossaryTerm[]> {
  const all = await getAllGlossaryTerms();
  return all.filter((term) => term.category === category);
}

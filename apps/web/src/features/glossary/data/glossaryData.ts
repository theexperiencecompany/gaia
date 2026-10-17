/**
 * Glossary terms — `/learn/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/glossary/{slug}.json`,
 * which is the source. At Cloudflare runtime they are fetched via the ASSETS binding instead of being bundled
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
  /**
   * Marks this term as a consolidated near-duplicate of /learn/{canonicalSlug}.
   * The page 308-redirects via `canonical-redirects.mjs`; entries with this
   * field are excluded from `_slugs.json` (the page set) and must never be
   * linked, listed or emitted.
   */
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

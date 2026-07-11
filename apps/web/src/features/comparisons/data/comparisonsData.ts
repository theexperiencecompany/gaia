/**
 * Comparison pages data — `/compare/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/comparisons/{slug}.json`
 * (regenerate via `pnpm tsx scripts/extract-static-data.ts`). At Cloudflare
 * runtime they are fetched via the ASSETS binding instead of being bundled
 * into handler.mjs.
 */

import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";

export interface ComparisonFeatureRow {
  [key: string]: string;
  feature: string;
  gaia: string;
  competitor: string;
}

export interface ComparisonData {
  slug: string;
  name: string;
  tagline: string;
  description: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  rows: ComparisonFeatureRow[];
  gaiaAdvantages: string[];
  competitorAdvantages: string[];
  domain: string;
  verdict: string;
  faqs: Array<{ question: string; answer: string }>;
  relatedPersonas?: string[];
  /**
   * Switching-intent content merged from the former /alternative-to/[slug]
   * family — one canonical page per competitor keyword.
   */
  whyPeopleLook?: string;
  painPoints?: string[];
  gaiaFitScore?: number;
  gaiaReplaces?: string[];
  migrationSteps?: string[];
  /** FAQs from the alternative page not already covered by `faqs` — rendered after them. */
  alternativeFaqs?: Array<{ question: string; answer: string }>;
  /** Real editorial dates derived from git history (YYYY-MM-DD) — see scripts note in PR. */
  datePublished?: string;
  dateModified?: string;
}

const FEATURE = "comparisons";

export async function getComparison(
  slug: string,
): Promise<ComparisonData | undefined> {
  return getFeatureEntry<ComparisonData>(FEATURE, slug);
}

export async function getAllComparisonSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

export async function getAllComparisons(): Promise<ComparisonData[]> {
  return getAllFeatureEntries<ComparisonData>(FEATURE);
}

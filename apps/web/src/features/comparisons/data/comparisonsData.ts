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

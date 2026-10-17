/**
 * Integration combo pages — `/automate/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/combos/{slug}.json`,
 * which is the source. At Cloudflare runtime they are fetched via the ASSETS binding instead of being bundled
 * into handler.mjs.
 */

import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";

export interface IntegrationCombo {
  slug: string;
  toolA: string;
  toolASlug: string;
  toolB: string;
  toolBSlug: string;
  tagline: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  useCases: Array<{ title: string; description: string }>;
  howItWorks: Array<{ step: string; description: string }>;
  faqs: Array<{ question: string; answer: string }>;
  /**
   * Marks this combo as a consolidated near-duplicate of /automate/{canonicalSlug}
   * (reverse-order pairs). The page 308-redirects via `canonical-redirects.mjs`;
   * entries with this field are excluded from `_slugs.json` (the page set) and
   * must never be linked, listed or emitted.
   */
  canonicalSlug?: string;
}

const FEATURE = "combos";

export async function getCombo(
  slug: string,
): Promise<IntegrationCombo | undefined> {
  return getFeatureEntry<IntegrationCombo>(FEATURE, slug);
}

export async function getAllComboSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

export async function getAllCombos(): Promise<IntegrationCombo[]> {
  return getAllFeatureEntries<IntegrationCombo>(FEATURE);
}

/**
 * Integration combo pages — `/automate/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/combos/{slug}.json`
 * (regenerate via `pnpm tsx scripts/extract-static-data.ts`). At Cloudflare
 * runtime they are fetched via the ASSETS binding instead of being bundled
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
  /** When set, this page's canonical points to /automate/{canonicalSlug} — use for reverse-order duplicate combos (e.g. github-slack → slack-github). */
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

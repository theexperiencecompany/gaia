/**
 * Alternative-to pages data — `/alternative-to/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/alternatives/{slug}.json`
 * (regenerate with `pnpm tsx scripts/extract-static-data.ts`). At build time
 * they're read from disk; at Cloudflare runtime they're fetched via the
 * ASSETS binding. This keeps ~3 MB of static SEO content out of handler.mjs.
 *
 * The TypeScript interface stays here so authors get type checking on
 * `entries/{slug}.ts` source files (which the codegen reads to produce JSON).
 */

import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";

export interface AlternativeData {
  slug: string;
  name: string;
  domain: string;
  category:
    | "task-manager"
    | "ai-assistant"
    | "calendar"
    | "email"
    | "automation"
    | "notes"
    | "productivity-suite";
  tagline: string;
  painPoints: string[];
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  whyPeopleLook: string;
  gaiaFitScore: number;
  gaiaReplaces: string[];
  gaiaAdvantages: string[];
  migrationSteps: string[];
  faqs: Array<{ question: string; answer: string }>;
  comparisonRows?: Array<{
    feature: string;
    gaia: string;
    competitor: string;
  }>;
}

const FEATURE = "alternatives";

export async function getAllAlternatives(): Promise<AlternativeData[]> {
  return getAllFeatureEntries<AlternativeData>(FEATURE);
}

export async function getAlternative(
  slug: string,
): Promise<AlternativeData | undefined> {
  return getFeatureEntry<AlternativeData>(FEATURE, slug);
}

export async function getAllAlternativeSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

export async function getAlternativesByCategory(
  category: AlternativeData["category"],
): Promise<AlternativeData[]> {
  const all = await getAllAlternatives();
  return all.filter((a) => a.category === category);
}

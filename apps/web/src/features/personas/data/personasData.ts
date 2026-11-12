/**
 * Persona pages data — `/for/[slug]`
 *
 * Per-slug entries live in `apps/web/public/data/personas/{slug}.json`.
 * At Cloudflare runtime they are fetched via the ASSETS binding instead of
 * being bundled into handler.mjs.
 */

import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";

export interface PersonaFeature {
  title: string;
  description: string;
}

export interface PersonaData {
  slug: string;
  title: string;
  role: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  painPoints: string[];
  howGaiaHelps: PersonaFeature[];
  relevantIntegrations: string[];
  faqs: Array<{ question: string; answer: string }>;
  relatedComparisons?: string[];
}

const FEATURE = "personas";

export async function getPersona(
  slug: string,
): Promise<PersonaData | undefined> {
  return getFeatureEntry<PersonaData>(FEATURE, slug);
}

export async function getAllPersonaSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

export async function getAllPersonas(): Promise<PersonaData[]> {
  return getAllFeatureEntries<PersonaData>(FEATURE);
}

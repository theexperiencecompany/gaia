/**
 * The marketplace's apps as GET /integrations/public/{id} sends them: GAIA's own
 * integrations and the community's published MCP servers, from production.
 */

import type { PublicIntegrationDetailResponse } from "@shared/api/generated";

import FIXTURE from "./apps.fixture.json";

export const MARKETPLACE_PATH = "/dev/marketplace";

export type App = PublicIntegrationDetailResponse;

export const APPS: App[] = FIXTURE as App[];

/** The API's category keys, as plain words. */
const CATEGORY_LABELS: Record<string, string> = {
  productivity: "Productivity",
  communication: "Communication",
  developer: "Developer",
  social_media: "Social",
  business: "Business",
  news: "News",
  lifestyle: "Lifestyle",
  capabilities: "Web and tools",
  education: "Education",
  finance: "Finance",
  analytics: "Analytics",
  "ai-ml": "AI",
  personal: "Personal",
  other: "Other",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function isByGaia(app: App): boolean {
  return app.source === "platform";
}

export function findApp(slug: string): App | undefined {
  return APPS.find((app) => app.slug === slug || app.integrationId === slug);
}

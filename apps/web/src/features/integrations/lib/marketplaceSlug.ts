import { MARKETPLACE_PATH } from "@/features/integrations/lib/marketplaceDirectoryPages";

/** The URL slug for an integration's API slug: native ids such as "google_maps" use underscores, marketplace URLs hyphens. */
export function marketplaceSlug(apiSlug: string): string {
  return apiSlug.replaceAll("_", "-");
}

/** The marketplace page for an integration's API slug. */
export function marketplacePath(apiSlug: string): string {
  return `${MARKETPLACE_PATH}/${marketplaceSlug(apiSlug)}`;
}

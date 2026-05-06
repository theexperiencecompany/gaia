/**
 * Resolve avatar + display name for a workflow creator across all surfaces
 * (cards, detail pages, sidebars). Centralizes the "system" → GAIA Team
 * convention so card and detail pages stay in sync.
 */

const SYSTEM_CREATOR_ID = "system";
const GAIA_LOGO_SRC = "/images/logos/experience_black_bg.png";

export interface ResolvableCreator {
  id?: string | null;
  name?: string | null;
  avatar?: string | null;
}

export function isSystemCreator(
  creator: ResolvableCreator | null | undefined,
): boolean {
  return creator?.id === SYSTEM_CREATOR_ID;
}

export function resolveCreatorAvatar(
  creator: ResolvableCreator | null | undefined,
): string | undefined {
  if (isSystemCreator(creator)) return GAIA_LOGO_SRC;
  return creator?.avatar ?? undefined;
}

export function resolveCreatorName(
  creator: ResolvableCreator | null | undefined,
): string {
  if (isSystemCreator(creator)) return "GAIA Team";
  return creator?.name?.trim() || "Unknown";
}

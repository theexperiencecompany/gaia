/**
 * Resolve avatar + display name for a workflow creator across all surfaces
 * (cards, detail pages, sidebars). Centralizes the "system" → GAIA Team
 * convention so card and detail pages stay in sync.
 */

import type { WorkflowCreator } from "@shared/api/generated";

type ResolvableCreator = Partial<WorkflowCreator>;

const SYSTEM_CREATOR_ID = "system";
// The GAIA mark, not the Experience Company one — these surfaces are attributed
// to "GAIA Team", so the logo has to match the name.
const GAIA_LOGO_SRC = "/brand/gaia_logo.svg";

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

/**
 * Canonical React Query keys for integrations and tools.
 *
 * Use these instead of inline string-array keys so invalidation/refetch targets
 * stay consistent across hooks, pages, and components. Values match the keys
 * used elsewhere in the app (incl. mobile), so cache identity is preserved.
 *
 * Backend data model (PR #816): a single personalized catalog at
 * GET /integrations/me, plus per-integration tools at GET /integrations/{id}/tools.
 */
export const integrationKeys = {
  /** Prefix — invalidating this busts the catalog, per-integration tools, and instructions. */
  all: ["integrations"] as const,
  /** The personalized catalog (GET /integrations/me). */
  me: ["integrations", "me"] as const,
  /** One integration's tools (GET /integrations/{id}/tools). */
  tools: (integrationId: string) =>
    ["integrations", integrationId, "tools"] as const,
  /** One integration's custom instructions. */
  instructions: (integrationId: string) =>
    ["integrations", "instructions", integrationId] as const,
};

export const toolKeys = {
  /** Prefix — invalidating this busts the unified workspace tools list. */
  all: ["tools"] as const,
  /** The unified workspace tools list (GET /tools). */
  available: ["tools", "available"] as const,
};

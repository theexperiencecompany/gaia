/**
 * Canonical React Query keys for integrations and tools.
 *
 * Use these instead of inline string-array keys so invalidation/refetch targets
 * stay consistent across hooks, pages, and components. Values match the keys
 * used elsewhere in the app (incl. mobile), so cache identity is preserved.
 *
 * The catalog snapshot and status map are separate queries; per-integration
 * tools are still fetched on demand at GET /integrations/{id}/tools.
 */
export const integrationKeys = {
  /** Prefix — invalidating this busts the catalog, status, per-integration tools, and instructions. */
  all: ["integrations"] as const,
  /** Fast personalized catalog snapshot. */
  me: ["integrations", "me"] as const,
  /** The independently refreshed connection map (GET /integrations/status). */
  status: ["integrations", "status"] as const,
  /** One integration's tools (GET /integrations/{id}/tools). */
  tools: (integrationId: string) =>
    ["integrations", integrationId, "tools"] as const,
  /** The accounts connected to one integration (GET /integrations/{id}/accounts). */
  accounts: (integrationId: string) =>
    ["integrations", integrationId, "accounts"] as const,
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

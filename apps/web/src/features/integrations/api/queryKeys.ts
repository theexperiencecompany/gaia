/**
 * Canonical React Query keys for integrations and tools.
 *
 * Use these instead of inline string-array keys so invalidation/refetch targets
 * stay consistent across hooks, pages, and components.
 */
export const integrationKeys = {
  all: ["integrations"] as const,
  config: ["integrations", "config"] as const,
  user: ["integrations", "user"] as const,
  status: ["integrations", "status"] as const,
  instructions: (integrationId: string) =>
    ["integrations", "instructions", integrationId] as const,
};

export const toolKeys = {
  all: ["tools"] as const,
  available: ["tools", "available"] as const,
};

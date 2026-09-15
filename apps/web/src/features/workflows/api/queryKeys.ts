/**
 * Canonical React Query keys for workflows.
 *
 * Use these instead of inline string-array keys so invalidation/refetch
 * targets stay consistent across hooks, pages, and components.
 */
export const workflowKeys = {
  /** Prefix — invalidating this busts every workflow query. */
  all: ["workflows"] as const,
  /** The user's workflow list (GET /workflows). */
  list: () => ["workflows", "list"] as const,
};

/** Canonical React Query keys for the user's instructions, one entry per scope. */
export const instructionsKeys = {
  all: ["instructions"] as const,
  scope: (scope: string) => ["instructions", scope] as const,
};

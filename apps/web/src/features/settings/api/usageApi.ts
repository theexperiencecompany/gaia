import type { UsageHistoryEntry } from "@shared/api/generated";

export type { UsageHistoryEntry } from "@shared/api/generated";

import { api } from "@/lib/api/typed";

export const usageApi = {
  getUsageSummary: () => api.get("/api/v1/usage/summary"),

  getUsageHistory: async (
    days: number = 30,
    featureKey?: string,
  ): Promise<UsageHistoryEntry[]> => {
    const history = await api.get("/api/v1/usage/history", {
      query: { days, feature_key: featureKey },
    });
    // Backend returns newest-first; charts consume chronological order.
    return [...history].sort((a, b) => a.date.localeCompare(b.date));
  },

  // The activity grid and the user's standing.
  getUsageActivity: (days: number = 365) =>
    api.get("/api/v1/usage/activity", { query: { days } }),
};

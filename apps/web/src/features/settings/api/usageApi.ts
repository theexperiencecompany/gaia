import type { UsageHistoryEntry } from "@shared/api/generated";

export type { UsageHistoryEntry } from "@shared/api/generated";

import type { UsageActivity } from "@shared/types";
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

  /**
   * The activity grid and the user's standing.
   *
   * `tier` is a plain `str` on the API model, so the generated type widens the
   * four badge names to `string`; the UI indexes its TIERS table by them. The
   * narrowing belongs on the API side (a StrEnum) — until then it is stated
   * here, once, instead of at every read.
   */
  getUsageActivity: async (days: number = 365): Promise<UsageActivity> =>
    (await api.get("/api/v1/usage/activity", {
      query: { days },
    })) as UsageActivity,
};

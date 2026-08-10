import type { FeatureUsage, UsageActivity, UsageSummary } from "@shared/types";
import { apiauth } from "@/lib/api/client";

export interface UsageHistoryEntry {
  date: string;
  plan_type: string;
  features: Record<string, Pick<FeatureUsage, "title" | "periods">>;
}

class UsageApiService {
  async getUsageSummary(): Promise<UsageSummary> {
    const response = await apiauth.get("/usage/summary");
    return response.data;
  }

  async getUsageHistory(
    days: number = 30,
    featureKey?: string,
  ): Promise<UsageHistoryEntry[]> {
    const params = new URLSearchParams({ days: days.toString() });
    if (featureKey) {
      params.append("feature_key", featureKey);
    }

    const response = await apiauth.get(`/usage/history?${params}`);
    // Backend returns newest-first; charts consume chronological order.
    return response.data.sort((a: UsageHistoryEntry, b: UsageHistoryEntry) =>
      a.date.localeCompare(b.date),
    );
  }

  async getUsageActivity(days: number = 365): Promise<UsageActivity> {
    const response = await apiauth.get(`/usage/activity?days=${days}`);
    return response.data;
  }
}

export const usageApi = new UsageApiService();

import type { FeatureUsage, UsageSummary } from "@shared/types";
import { apiauth } from "@/lib/api/client";

export type {
  FeatureUsage,
  TokenUsage,
  TokenUsagePeriod,
  UsagePeriod,
  UsageSummary,
} from "@shared/types";

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
    return response.data;
  }
}

export const usageApi = new UsageApiService();

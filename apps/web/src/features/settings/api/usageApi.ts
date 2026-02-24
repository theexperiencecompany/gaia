import { apiauth } from "@/lib/api";

interface UsagePeriod {
  used: number;
  limit: number;
  percentage: number;
  reset_time?: string;
  remaining: number;
}

interface FeatureUsage {
  title: string;
  description: string;
  category: string;
  periods: {
    hour?: UsagePeriod;
    day?: UsagePeriod;
    month?: UsagePeriod;
  };
}

interface TokenUsage {
  title: string;
  periods: {
    day?: {
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      limit: number;
      percentage: number;
      remaining: number;
    };
    month?: {
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      limit: number;
      percentage: number;
      remaining: number;
    };
  };
}

interface UsageSummary {
  user_id: string;
  plan_type: string;
  features: Record<string, FeatureUsage>;
  token_usage: Record<string, TokenUsage>;
  last_updated: string;
}

interface UsageHistoryEntry {
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

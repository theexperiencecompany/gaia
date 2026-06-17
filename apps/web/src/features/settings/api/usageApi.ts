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

export interface CreditSpend {
  key: string;
  title: string;
  credits: number;
}

export interface CreditPeriod {
  used: number;
  limit: number;
  remaining: number;
  reset_time: string;
  breakdown: CreditSpend[];
}

export interface CreditGrant {
  remaining: number;
  expires_at: string;
}

export interface CreditBalance {
  plan_type: string;
  allotment_remaining: number;
  topup_remaining: number;
  total_remaining: number;
  periods: { day: CreditPeriod; month: CreditPeriod };
  topup_grants: CreditGrant[];
}

export interface CreditPack {
  key: string;
  credits: number;
  price_cents: number;
  name: string;
}

export interface ActionCost {
  key: string;
  title: string;
  credits: number;
}

export interface UsageCatalog {
  credit_value_usd: number;
  chat_message_estimate: string;
  action_costs: ActionCost[];
  plan_credits: { free: number; pro: number; max: number };
}

class UsageApiService {
  async getUsageSummary(): Promise<UsageSummary> {
    const response = await apiauth.get("/usage/summary");
    return response.data;
  }

  async getCreditBalance(): Promise<CreditBalance> {
    const response = await apiauth.get("/usage/credits");
    return response.data;
  }

  async getCreditPacks(): Promise<CreditPack[]> {
    const response = await apiauth.get("/payments/credit-packs");
    return response.data;
  }

  async getUsageCatalog(): Promise<UsageCatalog> {
    const response = await apiauth.get("/usage/catalog");
    return response.data;
  }

  async purchaseCreditPack(packKey: string): Promise<{ payment_link: string }> {
    const response = await apiauth.post(
      `/payments/credit-packs/${packKey}/checkout`,
    );
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

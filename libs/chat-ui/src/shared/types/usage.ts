export interface UsagePeriod {
  used: number;
  limit: number;
  percentage: number;
  reset_time?: string;
  remaining: number;
}

export interface FeatureUsage {
  title: string;
  description: string;
  category: string;
  periods: {
    hour?: UsagePeriod;
    day?: UsagePeriod;
    month?: UsagePeriod;
  };
}

export interface TokenUsagePeriod {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  limit: number;
  percentage: number;
  remaining: number;
}

export interface TokenUsage {
  title: string;
  periods: {
    day?: TokenUsagePeriod;
    month?: TokenUsagePeriod;
  };
}

export interface UsageSummary {
  user_id: string;
  plan_type: string;
  features: Record<string, FeatureUsage>;
  token_usage: Record<string, TokenUsage>;
  last_updated: string;
}

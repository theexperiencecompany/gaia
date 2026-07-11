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
  /** The Pro tier's limits for this feature, for the free-plan upgrade comparison. */
  upgrade?: { day: number; month: number };
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

/** One cost-budget window: only how much of the allowance is used (0-100) and
 * when it resets. The backend never sends raw USD spend — see cost_budget.py. */
export interface BudgetWindow {
  percentage: number;
  reset_time: string;
}

export interface UsageBudget {
  /** Daily AI-usage allowance (free = usage wall, pro = abuse guard). */
  daily: BudgetWindow;
  /** Monthly compute allowance — pro only; null on free. */
  monthly: BudgetWindow | null;
  /** Largest single task the plan can run, in tokens (capability, not a meter). */
  per_request_token_ceiling: number;
}

export interface ActivityDay {
  /** UTC date, YYYY-MM-DD. */
  date: string;
  /** Total actions (tool calls + messages) that day. */
  count: number;
}

/** Year activity heatmap + the user's standing. Served by /usage/activity,
 * backed by the daily-rollup collection (see usage_daily). */
export interface UsageActivity {
  days: ActivityDay[];
  total: number;
  /** Longest run of consecutive active days in the window. */
  streak: number;
  /** Percentile of this user's activity vs all users (0-100), or null. */
  percentile: number | null;
  /** Badge tier from the percentile, or null when unranked. */
  tier: "diamond" | "gold" | "silver" | "bronze" | null;
}

export interface UsageSummary {
  user_id: string;
  plan_type: string;
  features: Record<string, FeatureUsage>;
  budget: UsageBudget;
  last_updated: string;
  /** Vestigial: the summary endpoint does not currently populate this. */
  token_usage?: Record<string, TokenUsage>;
}

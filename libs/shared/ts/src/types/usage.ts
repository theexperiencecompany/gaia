import type { Schema } from "../api/generated";
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

/** One cost-budget window: only how much of the allowance is used (0-100) and
 * when it resets. The backend never sends raw USD spend — see cost_budget.py. */
export type BudgetWindow = Schema<"BudgetWindow">;

export type UsageBudget = Schema<"UsageBudget">;

export type ActivityDay = Schema<"ActivityDay">;

/** Year activity heatmap + the user's standing. Served by /usage/activity,
 * backed by the daily-rollup collection (see usage_daily). */
export interface UsageActivity {
  days: ActivityDay[];
  total: number;
  /** Input + output tokens across the whole window. */
  total_tokens: number;
  /** Consecutive active days ending now (current streak, not historical best). */
  streak: number;
  /** Percentile of this user's activity vs all users (0-100), or null. */
  percentile: number | null;
  /** Badge tier from the percentile, or null when unranked. */
  tier: "diamond" | "gold" | "silver" | "bronze" | null;
}

export type UsageSummary = Schema<"UsageSummary">;

import type {
  FeaturePeriodUsage,
  FeatureUsageSummary,
  UsageActivityResponse,
} from "../api/generated";

export type {
  ActivityDay,
  BudgetWindow,
  UsageBudget,
  UsageSummary,
} from "../api/generated";
export type UsagePeriod = FeaturePeriodUsage;
export type FeatureUsage = FeatureUsageSummary;
export type UsageActivity = UsageActivityResponse;

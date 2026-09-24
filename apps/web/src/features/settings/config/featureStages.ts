import type { FeatureStage } from "@shared/api/generated";

/** The chip shown next to a user-toggleable feature; typed so a new stage cannot ship unlabeled. */
export const FEATURE_STAGE_LABELS: Record<FeatureStage, string> = {
  experimental: "Experimental",
};

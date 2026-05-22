import { AI_INTELLIGENCE_FEATURES } from "./features/aiIntelligence";
import { AUTOMATION_FEATURES } from "./features/automation";
import { INTEGRATIONS_FEATURES } from "./features/integrations";
import { MULTI_PLATFORM_FEATURES } from "./features/multiPlatform";
import { PRODUCTIVITY_FEATURES } from "./features/productivity";
import type { FeatureCategory, FeatureData } from "./featuresData.types";

export type {
  FeatureBenefit,
  FeatureCategory,
  FeatureData,
  FeatureFAQ,
  FeatureUseCase,
  HowItWorksStep,
} from "./featuresData.types";

export const FEATURE_CATEGORIES: FeatureCategory[] = [
  "AI Intelligence",
  "Productivity",
  "Automation",
  "Integrations",
  "Multi-Platform",
];

export const CATEGORY_COLORS: Record<
  FeatureCategory,
  { icon: string; bg: string }
> = {
  "AI Intelligence": { icon: "#a855f7", bg: "rgba(168,85,247,0.12)" },
  Productivity: { icon: "#22c55e", bg: "rgba(34,197,94,0.12)" },
  Automation: { icon: "#f97316", bg: "rgba(249,115,22,0.12)" },
  Integrations: { icon: "#3b82f6", bg: "rgba(59,130,246,0.12)" },
  "Multi-Platform": { icon: "#ec4899", bg: "rgba(236,72,153,0.12)" },
};

export const FEATURES: FeatureData[] = [
  ...AI_INTELLIGENCE_FEATURES,
  ...PRODUCTIVITY_FEATURES,
  ...AUTOMATION_FEATURES,
  ...INTEGRATIONS_FEATURES,
  ...MULTI_PLATFORM_FEATURES,
];

export function getFeatureBySlug(slug: string): FeatureData | undefined {
  return FEATURES.find((f) => f.slug === slug);
}

export function getFeaturesByCategory(
  category: FeatureCategory,
): FeatureData[] {
  return FEATURES.filter((f) => f.category === category);
}

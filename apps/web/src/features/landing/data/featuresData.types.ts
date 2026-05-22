export type FeatureCategory =
  | "AI Intelligence"
  | "Productivity"
  | "Automation"
  | "Integrations"
  | "Multi-Platform";

export interface FeatureBenefit {
  icon: string;
  title: string;
  description: string;
}

export interface HowItWorksStep {
  number: string;
  title: string;
  description: string;
}

export interface FeatureFAQ {
  question: string;
  answer: string;
}

export interface FeatureUseCase {
  title: string;
  description: string;
}

export interface FeatureData {
  slug: string;
  category: FeatureCategory;
  icon: string;
  title: string;
  tagline: string;
  headline: string;
  subheadline: string;
  benefits: [FeatureBenefit, FeatureBenefit, FeatureBenefit];
  howItWorks?: [HowItWorksStep, HowItWorksStep, HowItWorksStep];
  faqs?: [FeatureFAQ, FeatureFAQ, FeatureFAQ, FeatureFAQ];
  useCases?: [FeatureUseCase, FeatureUseCase, FeatureUseCase];
  relatedSlugs?: [string, string, string];
  demoComponent: string;
}

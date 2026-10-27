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
  /** Search-result title: what people search for this feature, in the snippet range of src/config/seoSnippet.json. */
  metaTitle: string;
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

/** One group of linked capabilities in the /features at-a-glance list. */
export interface CapabilityGroup {
  heading: string;
  items: { text: string; href: string }[];
}

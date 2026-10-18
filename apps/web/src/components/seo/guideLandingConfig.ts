import { fillCurrentYear } from "@/lib/feature-data";
import { generatePageMetadata } from "@/lib/seo";

export interface GuideLink {
  readonly href: string;
  readonly label: string;
  readonly description: string;
}

export interface GuideSection {
  readonly heading: string;
  readonly paragraphs: readonly string[];
  readonly bullets?: readonly string[];
}

export interface GuideStep {
  readonly name: string;
  readonly text: string;
}

export interface GuideFaq {
  readonly question: string;
  readonly answer: string;
}

/** One English-only marketing guide: a direct answer, the sections a query's variants ask for, then limits, FAQ and links. */
export interface GuideLandingConfig {
  readonly path: string;
  readonly title: string;
  readonly description: string;
  readonly keywords: readonly string[];
  readonly breadcrumbName: string;
  readonly heading: string;
  /** The first paragraph: answers the query outright, before any section. */
  readonly answer: string;
  readonly sections: readonly GuideSection[];
  /** Rendered as a numbered list and emitted as HowTo JSON-LD. */
  readonly steps?: {
    readonly heading: string;
    readonly items: readonly GuideStep[];
  };
  /** What GAIA does not do, stated plainly so the page never oversells. */
  readonly limits?: {
    readonly heading: string;
    readonly items: readonly string[];
  };
  readonly faqs: GuideFaq[];
  readonly related: readonly GuideLink[];
}

export function generateGuideMetadata(config: GuideLandingConfig) {
  return generatePageMetadata({
    title: fillCurrentYear(config.title),
    description: fillCurrentYear(config.description),
    path: config.path,
    keywords: config.keywords.map(fillCurrentYear),
  });
}

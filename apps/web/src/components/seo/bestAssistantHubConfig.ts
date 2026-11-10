import type { ReactNode } from "react";
import { fillCurrentYear } from "@/lib/feature-data";
import { generatePageMetadata } from "@/lib/seo";

export interface BestHubUseCase {
  readonly heading: string;
  readonly body: ReactNode;
}

export interface BestHubConfig {
  readonly pagePath: string;
  readonly pageTitle: string;
  readonly pageDescription: string;
  readonly keywords: string[];
  readonly breadcrumbName: string;
  readonly heading: string;
  readonly subheading: string;
  readonly intro: ReactNode;
  readonly tableAriaLabel: string;
  readonly tableTitle: string;
  readonly gaiaBestFor: string;
  readonly gaiaTake: string;
  readonly pickBody: string;
  readonly pickCompareHref: string;
  readonly pickCompareLabel: string;
  readonly pickAlternativeHref: string;
  readonly pickAlternativeLabel: string;
  /** Slugs in rank order, GAIA excluded. Each must resolve via getComparison. */
  readonly rankedSlugs: readonly string[];
  readonly bestFor: Record<string, string>;
  readonly shortVersion: Record<string, string>;
  /** Sections answering the query's variants (by use, by device), rendered after the pick. */
  readonly useCaseSections?: readonly BestHubUseCase[];
  readonly faqs: Array<{ question: string; answer: string }>;
  readonly comparisonsTitle: string;
  readonly alternativesTitle: string;
}

export function generateBestHubMetadata(
  config: Pick<
    BestHubConfig,
    "pageTitle" | "pageDescription" | "pagePath" | "keywords"
  >,
) {
  return generatePageMetadata({
    title: fillCurrentYear(config.pageTitle),
    description: config.pageDescription,
    path: config.pagePath,
    keywords: config.keywords.map(fillCurrentYear),
  });
}

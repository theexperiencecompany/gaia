import type { ReactNode } from "react";
import { generatePageMetadata } from "@/lib/seo";

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
  readonly faqs: Array<{ question: string; answer: string }>;
  readonly comparisonsTitle: string;
  readonly alternativesTitle: string;
  /**
   * When true, the bottom link lists cover every comparison and
   * alternative guide instead of just this hub's ranked pool.
   */
  readonly listAll?: boolean;
}

export function generateBestHubMetadata(
  config: Pick<
    BestHubConfig,
    "pageTitle" | "pageDescription" | "pagePath" | "keywords"
  >,
) {
  return generatePageMetadata({
    title: config.pageTitle,
    description: config.pageDescription,
    path: config.pagePath,
    keywords: config.keywords,
  });
}

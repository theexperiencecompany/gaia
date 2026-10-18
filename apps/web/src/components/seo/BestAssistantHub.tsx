import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { fillCurrentYear } from "@/lib/feature-data";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { BestHubFaq, BestHubPick } from "./BestHubClosing";
import {
  BestHubAlternativeLinks,
  BestHubComparisonLinks,
} from "./BestHubGuideLinks";
import { BestHubRunnersUp } from "./BestHubRankedSections";
import { BestHubIntro, BestHubTable } from "./BestHubRanking";
import { BestHubBreadcrumb, BestHubHeader } from "./BestHubSections";
import { BestHubUseCases } from "./BestHubUseCases";
import type { BestHubConfig } from "./bestAssistantHubConfig";
import { loadBestHubData } from "./bestAssistantHubData";

export default async function BestAssistantHub({
  config,
}: {
  readonly config: BestHubConfig;
}) {
  const { ranked, listedComparisons, listedAlternatives } =
    await loadBestHubData(config);

  const pageUrl = `${siteConfig.url}${config.pagePath}`;
  const breadcrumbItems = [
    { name: "Home", url: siteConfig.url },
    { name: config.breadcrumbName, url: pageUrl },
  ];

  const webPageSchema = generateWebPageSchema(
    fillCurrentYear(config.pageTitle),
    config.pageDescription,
    pageUrl,
    breadcrumbItems,
  );

  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbItems);

  const itemListSchema = generateItemListSchema([
    {
      name: "GAIA (our pick)",
      url: siteConfig.url,
    },
    ...ranked.map((pick) => ({
      name: `GAIA vs ${pick.data.name}`,
      url: `${siteConfig.url}${pick.compareHref}`,
    })),
  ]);

  const faqSchema = generateFAQSchema(config.faqs);

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          itemListSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <BestHubBreadcrumb config={config} />
        <BestHubHeader config={config} />
        <BestHubIntro config={config} />
        <BestHubTable config={config} ranked={ranked} />
        <BestHubPick config={config} />
        <BestHubUseCases sections={config.useCaseSections ?? []} />
        <BestHubRunnersUp ranked={ranked} />
        <BestHubFaq config={config} />
        <BestHubComparisonLinks
          title={config.comparisonsTitle}
          comparisons={listedComparisons}
        />
        <BestHubAlternativeLinks
          title={config.alternativesTitle}
          alternatives={listedAlternatives}
        />
      </article>
      <FinalSection />
    </>
  );
}

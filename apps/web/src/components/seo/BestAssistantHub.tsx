import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import {
  BestHubAlternativeLinks,
  BestHubComparisonLinks,
  BestHubRunnersUp,
} from "./BestHubRankedSections";
import {
  BestHubBreadcrumb,
  BestHubFaq,
  BestHubHeader,
  BestHubIntro,
  BestHubPick,
  BestHubTable,
} from "./BestHubSections";
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
    config.pageTitle,
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

import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { fillCurrentYear } from "@/lib/feature-data";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { GuideFaqSection, GuideRelatedLinks } from "./GuideLandingClosing";
import { GuideBodySection, GuideHeader } from "./GuideLandingSections";
import { GuideLimitList, GuideStepList } from "./GuideLandingSteps";
import type { GuideLandingConfig } from "./guideLandingConfig";

export default function GuideLanding({
  config,
}: {
  readonly config: GuideLandingConfig;
}) {
  const title = fillCurrentYear(config.title);
  const pageUrl = `${siteConfig.url}${config.path}`;
  const breadcrumbItems = [
    { name: "Home", url: siteConfig.url },
    { name: config.breadcrumbName, url: pageUrl },
  ];

  const schemas = [
    generateWebPageSchema(title, config.description, pageUrl, breadcrumbItems),
    generateBreadcrumbSchema(breadcrumbItems),
    generateFAQSchema(config.faqs),
    generateProductSchema(),
    ...(config.steps
      ? [
          generateHowToSchema(config.steps.heading, config.description, [
            ...config.steps.items,
          ]),
        ]
      : []),
  ];

  return (
    <>
      <JsonLd data={schemas} />
      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <GuideHeader config={config} />
        {config.sections.map((section) => (
          <GuideBodySection key={section.heading} section={section} />
        ))}
        {config.steps && <GuideStepList steps={config.steps} />}
        {config.limits && <GuideLimitList limits={config.limits} />}
        <GuideFaqSection faqs={config.faqs} />
        <GuideRelatedLinks links={config.related} />
      </article>
      <FinalSection />
    </>
  );
}

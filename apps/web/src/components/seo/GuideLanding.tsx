import JsonLd from "@/components/seo/JsonLd";
import { getGuide } from "@/features/guides/data/guidesData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
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

export default async function GuideLanding({
  slug,
}: {
  readonly slug: string;
}) {
  const guide = await getGuide(slug);
  const pageUrl = `${siteConfig.url}/${guide.slug}`;
  const breadcrumbItems = [
    { name: "Home", url: siteConfig.url },
    { name: guide.breadcrumbName, url: pageUrl },
  ];

  const schemas = [
    generateWebPageSchema(
      guide.metaTitle,
      guide.metaDescription,
      pageUrl,
      breadcrumbItems,
    ),
    generateBreadcrumbSchema(breadcrumbItems),
    generateFAQSchema(guide.faqs),
    generateProductSchema(),
    ...(guide.steps
      ? [
          generateHowToSchema(guide.steps.heading, guide.metaDescription, [
            ...guide.steps.items,
          ]),
        ]
      : []),
  ];

  return (
    <>
      <JsonLd data={schemas} />
      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <GuideHeader guide={guide} />
        {guide.sections.map((section) => (
          <GuideBodySection key={section.heading} section={section} />
        ))}
        {guide.steps && <GuideStepList steps={guide.steps} />}
        {guide.limits && <GuideLimitList limits={guide.limits} />}
        <GuideFaqSection faqs={guide.faqs} />
        <GuideRelatedLinks links={guide.related} />
      </article>
      <FinalSection />
    </>
  );
}

import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { Thing, WithContext } from "schema-dts";
import JsonLd from "@/components/seo/JsonLd";
import { FeatureDetailClient } from "@/features/landing/components/features/FeatureDetailClient";
import {
  FEATURES,
  getFeatureBySlug,
} from "@/features/landing/data/featuresData";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface Props {
  params: Promise<{ slug: string; locale: string }>;
}

export async function generateStaticParams() {
  return FEATURES.map((f) => ({ slug: f.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const feature = getFeatureBySlug(slug);
  if (!feature) return {};

  return generatePageMetadata({
    title: `${feature.title}`,
    description: feature.subheadline,
    path: `/features/${slug}`,
    keywords: [
      feature.title,
      `GAIA ${feature.title}`,
      `AI ${feature.title}`,
      feature.category,
      `${feature.category} AI`,
      feature.tagline,
      "GAIA features",
      "AI assistant features",
      "personal AI",
      "productivity AI",
    ],
  });
}

export default async function FeatureDetailPage({ params }: Props) {
  const { slug } = await params;
  const feature = getFeatureBySlug(slug);
  if (!feature) notFound();

  const pageUrl = `${siteConfig.url}/features/${slug}`;

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Features", url: `${siteConfig.url}/features` },
    { name: feature.title, url: pageUrl },
  ]);

  const webPageSchema = generateWebPageSchema(
    `${feature.title} — GAIA`,
    feature.subheadline,
    pageUrl,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Features", url: `${siteConfig.url}/features` },
      { name: feature.title, url: pageUrl },
    ],
  );

  const schemas: WithContext<Thing>[] = [breadcrumbSchema, webPageSchema];

  if (feature.faqs) {
    schemas.push(generateFAQSchema([...feature.faqs]));
  }

  if (feature.howItWorks) {
    schemas.push(
      generateHowToSchema(
        `How to use ${feature.title} in GAIA`,
        feature.subheadline,
        feature.howItWorks.map((step) => ({
          name: step.title,
          text: step.description,
        })),
      ),
    );
  }

  return (
    <>
      <JsonLd data={schemas} />
      <FeatureDetailClient feature={feature} />
    </>
  );
}

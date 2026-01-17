import type { Metadata } from "next";
import { notFound } from "next/navigation";

import JsonLd from "@/components/seo/JsonLd";
import { generateBreadcrumbSchema, siteConfig } from "@/lib/seo";

import { IntegrationDetailClient } from "./client";

// Revalidate every minute for fresher data
export const revalidate = 60;

// Fetch integration data for metadata and page
async function getIntegration(slug: string) {
  const apiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  const baseUrl = apiUrl.replace(/\/$/, "");

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(`${baseUrl}/integrations/public/${slug}`, {
      next: { revalidate: 60 },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) return null;
    return response.json();
  } catch (error) {
    console.error(`[marketplace/${slug}] Failed to fetch integration:`, error);
    return null;
  }
}

// Fetch all integrations for static generation
async function getAllIntegrations() {
  const apiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  const baseUrl = apiUrl.replace(/\/$/, "");

  try {
    const response = await fetch(
      `${baseUrl}/integrations/community?limit=100`,
      {
        next: { revalidate: 60 },
      },
    );
    if (!response.ok) return [];
    const data = await response.json();
    return data.integrations || [];
  } catch (error) {
    console.error("[marketplace] Failed to fetch integrations for SSG:", error);
    return [];
  }
}

/**
 * Generate static params for all public integrations.
 * This enables search engines to crawl and index all integration pages.
 */
export async function generateStaticParams() {
  const integrations = await getAllIntegrations();
  return integrations.map((i: { slug: string }) => ({ slug: i.slug }));
}

interface Props {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const integration = await getIntegration(slug);

  if (!integration) {
    return {
      title: "Integration Not Found | GAIA",
    };
  }

  const url = `${siteConfig.url}/marketplace/${slug}`;
  const ogImage = `/api/og/integration?slug=${slug}`;

  return {
    title: `${integration.name} | GAIA Marketplace`,
    description: integration.description,
    alternates: {
      canonical: url,
    },
    keywords: [
      integration.name,
      "MCP integration",
      "AI integration",
      integration.category,
      "GAIA",
    ].filter(Boolean),
    openGraph: {
      title: `${integration.name} - MCP Integration`,
      description: integration.description,
      url,
      siteName: siteConfig.fullName,
      images: [{ url: ogImage, width: 1200, height: 630 }],
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: `${integration.name} - MCP Integration`,
      description: integration.description,
      images: [ogImage],
    },
  };
}

export default async function IntegrationPage({ params }: Props) {
  const { slug } = await params;
  const integration = await getIntegration(slug);

  if (!integration) {
    notFound();
  }

  // Generate structured data for SEO
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Marketplace", url: `${siteConfig.url}/marketplace` },
    { name: integration.name, url: `${siteConfig.url}/marketplace/${slug}` },
  ]);

  const integrationSchema = {
    "@context": "https://schema.org" as const,
    "@type": "SoftwareApplication" as const,
    name: integration.name,
    description: integration.description,
    url: `${siteConfig.url}/marketplace/${slug}`,
    applicationCategory: "Integration",
    operatingSystem: "Web",
    offers: {
      "@type": "Offer" as const,
      price: "0",
      priceCurrency: "USD",
    },
    ...(integration.creator && {
      author: {
        "@type": "Person" as const,
        name: integration.creator.name,
      },
    }),
  };

  return (
    <>
      <JsonLd data={[breadcrumbSchema, integrationSchema]} />
      <IntegrationDetailClient integration={integration} />
    </>
  );
}

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IntegrationDetailClient } from "./client";

// Fetch integration data for metadata
async function getIntegration(slug: string) {
  const apiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  // Remove trailing slash if present
  const baseUrl = apiUrl.replace(/\/$/, "");

  try {
    // Add timeout to prevent hanging during SSR
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
    // Log for debugging but don't crash
    console.error(`[marketplace/${slug}] Failed to fetch integration:`, error);
    return null;
  }
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

  return {
    title: `${integration.name} | GAIA Marketplace`,
    description: integration.description,
    openGraph: {
      title: integration.name,
      description: integration.description,
      images: [`/marketplace/${slug}/opengraph-image`],
    },
  };
}

export default async function IntegrationPage({ params }: Props) {
  const { slug } = await params;
  const integration = await getIntegration(slug);

  if (!integration) {
    notFound();
  }

  return <IntegrationDetailClient integration={integration} />;
}

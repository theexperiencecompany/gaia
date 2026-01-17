import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IntegrationDetailClient } from "./client";

// Fetch integration data for metadata
async function getIntegration(slug: string) {
  try {
    const response = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/integrations/public/${slug}`,
      { next: { revalidate: 60 } }, // Cache for 60 seconds
    );
    if (!response.ok) return null;
    return response.json();
  } catch {
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

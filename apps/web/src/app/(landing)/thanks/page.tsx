import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import { tools } from "@/data/tools";
import Thanks from "@/features/thanks/components/Thanks";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface ToolMetadata {
  title: string | null;
  description: string | null;
  favicon: string | null;
  website_name: string | null;
  website_image: string | null;
  url: string;
}

export const metadata: Metadata = generatePageMetadata({
  title: "Tools We Love",
  description:
    "Discover the incredible open-source projects and tools that power GAIA. We celebrate the amazing communities and maintainers behind these projects that make building great software possible.",
  path: "/thanks",
  keywords: [
    "open source",
    "developer tools",
    "software tools",
    "GAIA stack",
    "tech stack",
    "developer ecosystem",
    "open source community",
    "software infrastructure",
  ],
});

async function fetchToolsMetadata(): Promise<Record<string, ToolMetadata>> {
  const logPrefix = "[Thanks Page]";

  try {
    const apiUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (!apiUrl) {
      console.error(`
╔════════════════════════════════════════════════════════════════╗
║  ${logPrefix} ERROR: API base URL not configured               ║
║  NEXT_PUBLIC_API_BASE_URL environment variable is missing      ║
║  Tool metadata will not be fetched                             ║
╚════════════════════════════════════════════════════════════════╝
      `);
      return {};
    }

    console.log(
      `${logPrefix} Fetching metadata for ${tools.length} tools from: ${apiUrl}`,
    );

    const urls = tools.map((tool) => tool.url);
    const baseUrl = apiUrl.replace(/\/$/, ""); // Remove trailing slash if present
    const response = await fetch(`${baseUrl}/fetch-url-metadata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }),
      next: { revalidate: 2592000 }, // Revalidate once per month (30 days)
    });

    if (!response.ok) {
      console.error(`
╔════════════════════════════════════════════════════════════════╗
║  ${logPrefix} ERROR: Failed to fetch tool metadata             ║
║  API URL: ${apiUrl}
║  Status: ${response.status} ${response.statusText}
║  Tool icons and images will not be displayed                   ║
╚════════════════════════════════════════════════════════════════╝
      `);
      return {};
    }

    const data = await response.json();
    const resultCount = Object.keys(data.results || {}).length;
    console.log
      (`${logPrefix} ✓ Successfully fetched metadata for ${resultCount}/${tools.length} tools,
    `);
    return data.results || {};
  } catch (error) {
    console.error(`
╔════════════════════════════════════════════════════════════════╗
║  ${logPrefix} ERROR: Exception while fetching tool metadata    ║
║  API URL: ${process.env.NEXT_PUBLIC_API_BASE_URL || "NOT SET"}
║  Error: ${error instanceof Error ? error.message : String(error)}
║  Tool icons and images will not be displayed                   ║
╚════════════════════════════════════════════════════════════════╝
    `);
    return {};
  }
}

export default async function ThanksPage() {
  const toolsMetadata = await fetchToolsMetadata();
  const webPageSchema = generateWebPageSchema(
    "Tools We Love",
    "Discover the incredible open-source projects and tools that power GAIA.",
    `${siteConfig.url}/thanks`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Tools We Love", url: `${siteConfig.url}/thanks` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Tools We Love", url: `${siteConfig.url}/thanks` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <Thanks toolsMetadata={toolsMetadata} />
    </>
  );
}

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import JsonLd from "@/components/seo/JsonLd";
import { MarketplaceDirectory } from "@/features/integrations/components/MarketplaceDirectory";
import {
  MARKETPLACE_PATH,
  marketplaceDirectoryPages,
} from "@/features/integrations/lib/marketplaceDirectoryPages";
import {
  getAllCommunityIntegrations,
  getNativeIntegrations,
} from "@/features/integrations/lib/serverMarketplaceApi";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { hubPagePath } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const revalidate = 3600;

interface PageProps {
  readonly params: Promise<{ readonly page: string }>;
}

async function loadDirectoryPages() {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  return marketplaceDirectoryPages(native, community);
}

function pageTitle(page: number, total: number): string {
  return `AI Integration Marketplace: Page ${page} of ${total}`;
}

function pageDescription(page: number, total: number): string {
  return `Page ${page} of ${total} of the GAIA integration directory: every AI integration and MCP server you can connect, from Gmail and Slack to Notion and GitHub.`;
}

/** No build-time paths: the page reads the API, so each path renders on its first request into the ISR cache. */
export function generateStaticParams() {
  return [];
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const page = Number((await params).page);
  const total = (await loadDirectoryPages()).length;
  return generatePageMetadata({
    title: pageTitle(page, total),
    description: pageDescription(page, total),
    path: hubPagePath(MARKETPLACE_PATH, page),
    image: "/api/og/integrations",
  });
}

export default async function MarketplaceDirectoryPage({ params }: PageProps) {
  const page = Number((await params).page);
  const pages = await loadDirectoryPages();
  const hubPage = pages.find(
    (candidate) => candidate.page > 1 && candidate.page === page,
  );
  if (!hubPage) notFound();

  const pageUrl = `${siteConfig.url}${hubPagePath(MARKETPLACE_PATH, page)}`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: "Marketplace", url: `${siteConfig.url}${MARKETPLACE_PATH}` },
    { name: `Page ${page}`, url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(
            pageTitle(page, pages.length),
            pageDescription(page, pages.length),
            pageUrl,
            breadcrumbs,
          ),
          generateBreadcrumbSchema(breadcrumbs),
        ]}
      />
      <div className="min-h-screen pt-16 pb-16">
        <div className="relative z-1 mx-auto mt-10 max-w-7xl px-6">
          <h1 className="mb-4 font-serif text-5xl font-normal text-foreground md:text-7xl">
            Integration Marketplace
          </h1>
          <MarketplaceDirectory hubPage={hubPage} totalPages={pages.length} />
        </div>
        <FinalSection />
      </div>
    </>
  );
}

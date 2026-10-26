import type { Metadata } from "next";
import UseCasesPageClient from "@/app/[locale]/(landing)/use-cases/client";
import JsonLd from "@/components/seo/JsonLd";
import { getCommunityWorkflowsServer } from "@/features/workflows/lib/serverWorkflowsApi";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Use Cases & Workflows",
  description:
    "Browse workflows that automate email, meetings, and scheduling with GAIA, including ones built by the community that you can run in your own account.",
  path: "/use-cases",
  image: "/api/og/use-cases",
  keywords: [
    "GAIA workflows",
    "AI automation workflows",
    "productivity workflows",
    "use cases",
    "automation examples",
    "community workflows",
    "AI task automation",
  ],
});

export const revalidate = 3600; // Revalidate every hour

export default async function UseCasesPage() {
  const { workflows: communityWorkflows } =
    await getCommunityWorkflowsServer(8);

  const webPageSchema = generateWebPageSchema(
    "Use Cases & Workflows",
    "Explore powerful workflows and use cases for GAIA. Discover how others are using AI to automate tasks.",
    `${siteConfig.url}/use-cases`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
  ]);
  const itemListInput: Array<{ name: string; url: string }> = [];
  for (const workflow of communityWorkflows) {
    if (!workflow.slug) continue;
    itemListInput.push({
      name: workflow.title,
      url: `${siteConfig.url}/use-cases/${workflow.slug}`,
    });
  }
  const itemListSchema = generateItemListSchema(itemListInput);

  return (
    <div className="relative h-fit min-h-screen pt-16 sm:pt-24">
      {/* No FAQPage schema here: this list page renders no visible FAQs,
          and FAQ rich results require the questions to be on the page. */}
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <UseCasesPageClient communityWorkflows={communityWorkflows} />
    </div>
  );
}

import type { Metadata } from "next";
import UseCasesPageClient from "@/app/[locale]/(landing)/use-cases/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  type CommunityWorkflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";
import { useCasesFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Use Cases & Workflows",
  description:
    "Explore powerful workflows and use cases for GAIA. Discover how others are using AI to automate tasks, manage emails, schedule meetings, and boost productivity with community-built workflows.",
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
  let communityWorkflows: CommunityWorkflow[] = [];

  try {
    const response = await workflowApi.getCommunityWorkflows(8, 0);
    communityWorkflows = response.workflows;
  } catch (error) {
    console.error("Error loading community workflows:", error);
  }

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
  const itemListInput: Array<{
    name: string;
    url: string;
    description: string;
  }> = [];
  for (const workflow of communityWorkflows) {
    if (!workflow.slug) continue;
    itemListInput.push({
      name: workflow.title,
      url: `${siteConfig.url}/use-cases/${workflow.slug}`,
      description: workflow.description || "",
    });
  }
  const itemListSchema = generateItemListSchema(itemListInput, "Article");

  const faqSchema = generateFAQSchema(useCasesFAQs);

  return (
    <div className="relative h-fit min-h-screen pt-16 sm:pt-24">
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, itemListSchema, faqSchema]}
      />

      <UseCasesPageClient communityWorkflows={communityWorkflows} />
    </div>
  );
}

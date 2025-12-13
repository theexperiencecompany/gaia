import type { Metadata } from "next";
import Image from "next/image";

import UseCasesPageClient from "@/app/(landing)/use-cases/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  type CommunityWorkflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";
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
    "Explore powerful workflows and use cases for GAIA. Discover how others are using AI to automate tasks, manage emails, schedule meetings, and boost productivity with community-built workflows.",
  path: "/use-cases",
  keywords: [
    "GAIA workflows",
    "AI automation workflows",
    "productivity workflows",
    "use cases",
    "automation examples",
    "community workflows",
    "workflow templates",
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
  const itemListSchema = generateItemListSchema(
    communityWorkflows.map((workflow) => ({
      name: workflow.title,
      url: `${siteConfig.url}/use-cases/${workflow.id}`,
      description: workflow.description || "",
    })),
    "Article",
  );

  return (
    <div className="relative h-fit min-h-screen pt-110">
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />
      <div className="absolute inset-0 top-0 z-0 h-[70vh] w-[100%]">
        <Image
          src={"/images/wallpapers/meadow.webp"}
          alt="GAIA Use-Cases Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-center opacity-80"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-gradient-to-t from-background to-transparent" />
      </div>

      <UseCasesPageClient communityWorkflows={communityWorkflows} />
    </div>
  );
}

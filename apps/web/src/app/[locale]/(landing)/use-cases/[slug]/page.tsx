import type { Metadata } from "next";
import { notFound } from "next/navigation";
import UseCaseDetailClient from "@/app/[locale]/(landing)/use-cases/[slug]/client";
import JsonLd from "@/components/seo/JsonLd";
import type { UseCase } from "@/features/use-cases/types";
import {
  type Workflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";
import { generateBreadcrumbSchema, siteConfig } from "@/lib/seo";
import {
  generateUseCaseMetadata,
  generateUseCaseStructuredData,
} from "@/utils/seoUtils";

interface PageProps {
  params: Promise<{ readonly slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  try {
    const isDev = process.env.NODE_ENV === "development";

    if (isDev) {
      const resp = await workflowApi.getExploreWorkflows(50, 0);
      return resp.workflows.map((w) => ({ slug: w.slug || w.id }));
    }

    const exploreLimit = 1000;
    const exploreResp = await workflowApi.getExploreWorkflows(exploreLimit, 0);
    const exploreParams = exploreResp.workflows.map((w) => ({
      slug: w.slug || w.id,
    }));

    const { fetchAllPaginated } = await import("@/lib/fetchAll");
    const communityWorkflows = await fetchAllPaginated(
      async (limit, offset) => {
        const resp = await workflowApi.getCommunityWorkflows(limit, offset);
        return {
          items: resp.workflows,
          total: resp.total || 0,
          hasMore: resp.workflows.length === limit,
        };
      },
      100,
    );
    const communityParams = communityWorkflows.map((w) => ({
      slug: w.slug || w.id,
    }));

    const allParams = [...exploreParams, ...communityParams];
    return allParams;
  } catch (error) {
    console.error("Error generating static params for use-cases:", error);
    return [];
  }
}

export const dynamicParams = true;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  try {
    const response = await workflowApi.getPublicWorkflow(slug);
    const workflow = response.workflow;

    const workflowAsUseCase: UseCase = {
      title: workflow.title,
      description: workflow.description || "",
      detailed_description: workflow.description,
      slug,
      action_type: "workflow",
      integrations: workflow.steps?.map((s) => s.category) || [],
      categories: ["featured"],
      published_id: workflow.id,
      creator: workflow.creator,
    };

    return generateUseCaseMetadata(workflowAsUseCase);
  } catch {
    return {
      title: "Use Case Not Found",
      description: "The requested use case could not be found.",
    };
  }
}

export default async function UseCaseDetailPage({ params }: PageProps) {
  const { slug } = await params;

  let communityWorkflow: Workflow | null = null;

  try {
    const response = await workflowApi.getPublicWorkflow(slug);
    communityWorkflow = response.workflow;
  } catch (error) {
    console.error("Error fetching workflow:", error);
    notFound();
  }

  if (!communityWorkflow) {
    notFound();
  }

  const structuredData = generateUseCaseStructuredData({
    title: communityWorkflow.title,
    description: communityWorkflow.description || "",
    slug,
    action_type: "workflow",
    integrations: communityWorkflow.steps?.map((s) => s.category) || [],
    categories: ["featured"],
    published_id: communityWorkflow.id,
    creator: communityWorkflow.creator,
    steps: communityWorkflow.steps,
  });

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
    {
      name: communityWorkflow.title,
      url: `${siteConfig.url}/use-cases/${slug}`,
    },
  ]);

  return (
    <>
      <JsonLd data={[structuredData, breadcrumbSchema]} />
      <UseCaseDetailClient
        useCase={null}
        communityWorkflow={communityWorkflow}
        slug={slug}
      />
    </>
  );
}

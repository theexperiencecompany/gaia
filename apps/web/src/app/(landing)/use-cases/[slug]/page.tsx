import type { Metadata } from "next";
import { notFound } from "next/navigation";
import UseCaseDetailClient from "@/app/(landing)/use-cases/[slug]/client";
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
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  try {
    const isDev = process.env.NODE_ENV === "development";

    if (isDev) {
      const resp = await workflowApi.getExploreWorkflows(50, 0);
      console.log(
        `[SSG Use Cases] Generating ${resp.workflows.length} pages (dev mode)`,
      );
      return resp.workflows.map((w) => ({ slug: w.id }));
    }

    const exploreLimit = 1000;
    const exploreResp = await workflowApi.getExploreWorkflows(exploreLimit, 0);
    const exploreParams = exploreResp.workflows.map((w) => ({ slug: w.id }));

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
    const communityParams = communityWorkflows.map((w) => ({ slug: w.id }));

    const allParams = [...exploreParams, ...communityParams];
    console.log(
      `[SSG Use Cases] Generating ${allParams.length} pages (${exploreParams.length} explore + ${communityParams.length} community)`,
    );

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

  // First, attempt to find the use-case in explore workflows (API)
  try {
    const resp = await workflowApi.getExploreWorkflows(200, 0);
    const found = resp.workflows.find((w) => w.id === slug);
    if (found) {
      const workflowAsUseCase: UseCase = {
        title: found.title,
        description: found.description || "",
        detailed_description: found.description,
        slug: found.id,
        action_type: "workflow",
        integrations: found.steps?.map((s) => s.category) || [],
        categories: found.categories || ["featured"],
        published_id: found.id,
        creator: found.creator,
      };

      return generateUseCaseMetadata(workflowAsUseCase);
    }
  } catch (err) {
    console.error("Error fetching explore workflows for metadata:", err);
  }

  // If not found in static data, try API as community workflow
  try {
    const response = await workflowApi.getPublicWorkflow(slug);
    const workflow = response.workflow;

    // Convert workflow to use case format for metadata generation
    const workflowAsUseCase: UseCase = {
      title: workflow.title,
      description: workflow.description || "",
      detailed_description: workflow.description,
      slug: workflow.id,
      action_type: "workflow",
      integrations: workflow.steps?.map((s) => s.category) || [],
      categories: ["Community"],
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

/**
 * Use Case Detail Page
 *
 * This page handles both static use cases and dynamic community workflows:
 * 1. First attempts to find the slug in static useCasesData
 * 2. If not found, attempts to fetch from API as a community workflow
 * 3. Displays appropriate content based on the data source
 */
export default async function UseCaseDetailPage({ params }: PageProps) {
  const { slug } = await params;

  let useCase: UseCase | null = null;
  let communityWorkflow: Workflow | null = null;

  // First, try to find the use-case in explore workflows
  try {
    const resp = await workflowApi.getExploreWorkflows(200, 0);
    const found = resp.workflows.find((w) => w.id === slug);
    if (found) {
      useCase = {
        title: found.title,
        description: found.description || "",
        action_type: "workflow",
        integrations: found.steps?.map((s) => s.category) || [],
        categories: found.categories || ["featured"],
        published_id: found.id,
        slug: found.id,
        steps: found.steps,
        creator: found.creator,
      } as UseCase;
    }
  } catch (err) {
    console.error("Error fetching explore workflows for page data:", err);
  }

  if (!useCase) {
    // If not found in static data, try API as community workflow
    try {
      const response = await workflowApi.getPublicWorkflow(slug);
      const workflow = response.workflow;

      // If it's a public workflow, try to get it from community endpoint to get creator info
      if (workflow.is_public) {
        try {
          const communityResponse = await workflowApi.getCommunityWorkflows(
            100,
            0,
          );
          const foundCommunityWorkflow = communityResponse.workflows.find(
            (w) => w.id === workflow.id,
          );

          if (foundCommunityWorkflow) {
            // Merge the community workflow data (which has creator) with the full workflow data
            communityWorkflow = {
              ...workflow,
              creator: foundCommunityWorkflow.creator,
            };
          } else {
            communityWorkflow = workflow;
          }
        } catch (error) {
          console.error("Error fetching community workflow details:", error);
          communityWorkflow = workflow;
        }
      } else {
        communityWorkflow = workflow;
      }
    } catch (error) {
      console.error("Error fetching workflow:", error);
      notFound();
    }
  }

  const data = useCase || communityWorkflow;
  if (!data) {
    notFound();
  }

  const structuredData = useCase
    ? generateUseCaseStructuredData(useCase)
    : communityWorkflow
      ? generateUseCaseStructuredData({
          title: communityWorkflow.title,
          description: communityWorkflow.description || "",
          slug: communityWorkflow.id,
          action_type: "workflow",
          integrations: communityWorkflow.steps?.map((s) => s.category) || [],
          categories: ["Community"],
          published_id: communityWorkflow.id,
          creator: communityWorkflow.creator,
          steps: communityWorkflow.steps,
        })
      : null;

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
    {
      name: useCase?.title || communityWorkflow?.title || "",
      url: `${siteConfig.url}/use-cases/${slug}`,
    },
  ]);

  return (
    <>
      {structuredData && <JsonLd data={[structuredData, breadcrumbSchema]} />}
      {!structuredData && <JsonLd data={breadcrumbSchema} />}
      <UseCaseDetailClient
        useCase={useCase}
        communityWorkflow={communityWorkflow}
        slug={slug}
      />
    </>
  );
}

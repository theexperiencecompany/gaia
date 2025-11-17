import type { Metadata } from "next";
import { notFound } from "next/navigation";

import UseCaseDetailClient from "@/app/(landing)/use-cases/[slug]/client";
import JsonLd from "@/components/seo/JsonLd";
import type { UseCase } from "@/features/use-cases/types";
import { Workflow, workflowApi } from "@/features/workflows/api/workflowApi";
import {
  generateUseCaseMetadata,
  generateUseCaseStructuredData,
} from "@/utils/seoUtils";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  // Generate params from explore workflows API
  try {
    const resp = await workflowApi.getExploreWorkflows(200, 0);
    return resp.workflows.map((w) => ({ slug: w.id }));
  } catch (error) {
    console.error("Error generating static params for use-cases:", error);
    return [];
  }
}

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
        integrations:
          found.steps?.filter((s) => s.tool_name).map((s) => s.tool_name!) ||
          [],
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
      integrations:
        workflow.steps?.filter((s) => s.tool_name).map((s) => s.tool_name!) ||
        [],
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
        integrations: found.steps?.map((s) => s.tool_name || "") || [],
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

  // Generate structured data
  const structuredData = useCase
    ? generateUseCaseStructuredData(useCase)
    : null;

  return (
    <>
      {structuredData && <JsonLd data={structuredData} />}
      <UseCaseDetailClient
        useCase={useCase}
        communityWorkflow={communityWorkflow}
        slug={slug}
      />
    </>
  );
}

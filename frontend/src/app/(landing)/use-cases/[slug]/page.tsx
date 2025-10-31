import type { Metadata } from "next";
import { notFound } from "next/navigation";

import JsonLd from "@/components/seo/JsonLd";
import UseCaseDetailClient from "@/app/(landing)/use-cases/[slug]/client";
import {
  type UseCase,
  useCasesData,
} from "@/features/use-cases/constants/dummy-data";
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
  // Generate params for all static use cases
  return useCasesData.map((useCase) => ({
    slug: useCase.slug,
  }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  // First, check static data
  const staticUseCase = useCasesData.find((uc) => uc.slug === slug);

  if (staticUseCase) {
    return generateUseCaseMetadata(staticUseCase);
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

  // First, check static data
  const staticUseCase = useCasesData.find((uc) => uc.slug === slug);

  if (staticUseCase) {
    useCase = staticUseCase;
  } else {
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

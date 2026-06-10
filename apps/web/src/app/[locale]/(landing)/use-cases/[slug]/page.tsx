import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import UseCaseDetailClient from "@/app/[locale]/(landing)/use-cases/[slug]/client";
import JsonLd from "@/components/seo/JsonLd";
import {
  type Workflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";
import { generateBreadcrumbSchema, siteConfig } from "@/lib/seo";
import type { UseCase } from "@/types/features/workflowTypes";
import {
  generateUseCaseMetadata,
  generateUseCaseStructuredData,
} from "@/utils/seoUtils";

/**
 * Cached explore workflows fetch for per-request deduplication.
 * Called by both generateMetadata and the page component — without
 * React.cache() the axios-based fetch would run twice per request.
 */
const getExploreWorkflowsCached = cache((limit: number, offset: number) =>
  workflowApi.getExploreWorkflows(limit, offset),
);

interface PageProps {
  params: Promise<{ readonly slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  try {
    const isDev = process.env.NODE_ENV === "development";

    if (isDev) {
      const resp = await workflowApi.getExploreWorkflows(50, 0);
      return resp.workflows.flatMap((w) => (w.slug ? [{ slug: w.slug }] : []));
    }

    const exploreResp = await workflowApi.getExploreWorkflows(1000, 0);

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

    return [...exploreResp.workflows, ...communityWorkflows].flatMap((w) =>
      w.slug ? [{ slug: w.slug }] : [],
    );
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
    const resp = await getExploreWorkflowsCached(200, 0);
    const found = resp.workflows.find((w) => w.id === slug || w.slug === slug);
    if (found) {
      const workflowAsUseCase: UseCase = {
        title: found.title,
        description: found.description || "",
        detailed_description: found.description,
        slug: found.slug,
        action_type: "workflow",
        integrations: found.steps?.map((s) => s.category) || [],
        categories: found.categories || ["featured"],
        published_id: found.id,
        creator: found.creator,
      };

      const meta = generateUseCaseMetadata(workflowAsUseCase);
      return meta;
    }
  } catch (err) {
    console.error("Error fetching explore workflows for metadata:", err);
  }

  // If not found in static data, try API as community workflow
  try {
    const response = await workflowApi.getPublicWorkflow(slug);
    const workflow = response.workflow;

    if (!workflow.slug) {
      return {
        title: "Use Case Not Found",
        description: "The requested use case could not be found.",
      };
    }

    const workflowAsUseCase: UseCase = {
      title: workflow.title,
      description: workflow.description || "",
      detailed_description: workflow.description,
      slug: workflow.slug,
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

  let useCase: UseCase | null = null;
  let communityWorkflow: Workflow | null = null;

  try {
    const resp = await getExploreWorkflowsCached(200, 0);
    const found = resp.workflows.find((w) => w.id === slug || w.slug === slug);
    if (found) {
      // If the URL uses the old ID but the workflow has a real slug, redirect
      if (slug.startsWith("wf_") && found.slug && found.slug !== slug) {
        redirect(`/use-cases/${found.slug}`);
      }
      useCase = {
        title: found.title,
        description: found.description || "",
        action_type: "workflow",
        integrations: found.steps?.map((s) => s.category) || [],
        categories: found.categories || ["featured"],
        published_id: found.id,
        slug: found.slug,
        steps: found.steps,
        creator: found.creator,
      } as UseCase;
    }
  } catch (err) {
    console.error("Error fetching explore workflows for page data:", err);
  }

  if (!useCase) {
    try {
      const response = await workflowApi.getPublicWorkflow(slug);
      const workflow = response.workflow;

      // If the URL uses the old ID but the workflow has a real slug, redirect
      if (slug.startsWith("wf_") && workflow.slug && workflow.slug !== slug) {
        redirect(`/use-cases/${workflow.slug}`);
      }

      communityWorkflow = workflow;
    } catch (error) {
      console.error("Error fetching workflow:", error);
      notFound();
    }
  }

  const data = useCase || communityWorkflow;
  if (!data) {
    notFound();
  }

  const displayTitle = useCase?.title ?? communityWorkflow?.title ?? "";
  const displayDescription =
    useCase?.description ?? communityWorkflow?.description ?? "";
  const displayIntegrations =
    useCase?.integrations ??
    communityWorkflow?.steps?.map((s) => s.category) ??
    [];
  const displayCategories = useCase?.categories ?? ["featured"];
  const displayPublishedId =
    useCase?.published_id ?? communityWorkflow?.id ?? "";
  const displayCreator = useCase?.creator ?? communityWorkflow?.creator;
  const displaySteps = useCase?.steps ?? communityWorkflow?.steps;

  const structuredData = generateUseCaseStructuredData({
    title: displayTitle,
    description: displayDescription,
    slug,
    action_type: "workflow",
    integrations: displayIntegrations,
    categories: displayCategories,
    published_id: displayPublishedId,
    creator: displayCreator,
    steps: displaySteps,
  });

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
    {
      name: displayTitle,
      url: `${siteConfig.url}/use-cases/${slug}`,
    },
  ]);

  return (
    <>
      <JsonLd data={[structuredData, breadcrumbSchema]} />
      <UseCaseDetailClient
        useCase={useCase}
        communityWorkflow={communityWorkflow}
        slug={slug}
      />
    </>
  );
}

import { ApiError } from "@shared/api";
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

const HTTP_NOT_FOUND = 404;

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
  const { useCase, communityWorkflow } = await resolveUseCase(slug);
  if (!useCase && !communityWorkflow) return {};
  const display = displayFromResolved(useCase, communityWorkflow);
  return generateUseCaseMetadata({
    title: display.title,
    description: display.description,
    detailed_description: display.description,
    slug: useCase?.slug ?? communityWorkflow?.slug ?? slug,
    action_type: "workflow",
    integrations: display.integrations,
    categories: display.categories,
    published_id: display.published_id,
    creator: display.creator,
  });
}

interface ResolvedUseCase {
  useCase: UseCase | null;
  communityWorkflow: Workflow | null;
  redirectTo: string | null;
  missing: boolean;
}

/**
 * Resolve a use-case slug to either a curated explore use-case or a community
 * workflow. Redirect targets are returned (not thrown) so the caller can invoke
 * redirect() outside of try/catch — redirect() throws a NEXT_REDIRECT control
 * flow error, which a surrounding catch would otherwise swallow or convert.
 */
const resolveUseCase = cache(async (slug: string): Promise<ResolvedUseCase> => {
  const isLegacyId = (canonicalSlug?: string | null) =>
    slug.startsWith("wf_") && !!canonicalSlug && canonicalSlug !== slug;

  {
    const resp = await getExploreWorkflowsCached(200, 0);
    const found = resp.workflows.find((w) => w.id === slug || w.slug === slug);
    if (found) {
      if (isLegacyId(found.slug)) {
        return {
          useCase: null,
          communityWorkflow: null,
          redirectTo: `/use-cases/${found.slug}`,
          missing: false,
        };
      }
      return {
        useCase: {
          title: found.title,
          description: found.description || "",
          action_type: "workflow",
          icon: found.icon,
          icon_color: found.icon_color,
          system_workflow_key: found.system_workflow_key,
          source_integration: found.source_integration,
          trigger_config: found.trigger_config,
          prompt: found.prompt,
          integrations: found.steps?.map((s) => s.category) || [],
          categories: found.categories || ["featured"],
          published_id: found.id,
          slug: found.slug,
          steps: found.steps,
          creator: found.creator,
          total_executions: found.total_executions,
        } as UseCase,
        communityWorkflow: null,
        redirectTo: null,
        missing: false,
      };
    }
  }

  try {
    const response = await workflowApi.getPublicWorkflow(slug);
    const workflow = response.workflow;
    // A workflow without a canonical slug has no valid use-case URL — treat
    // it as missing so this matches generateMetadata's "Not Found" for this
    // case, avoiding a page whose canonical/breadcrumb resolves to an empty slug.
    if (!workflow.slug) {
      return {
        useCase: null,
        communityWorkflow: null,
        redirectTo: null,
        missing: true,
      };
    }
    if (isLegacyId(workflow.slug)) {
      return {
        useCase: null,
        communityWorkflow: null,
        redirectTo: `/use-cases/${workflow.slug}`,
        missing: false,
      };
    }
    return {
      useCase: null,
      communityWorkflow: workflow,
      redirectTo: null,
      missing: false,
    };
  } catch (error) {
    // Only a real 404 is a missing use case. Anything else throws, so ISR keeps
    // serving the last good page instead of caching a not-found one as a 200.
    if (error instanceof ApiError && error.status === HTTP_NOT_FOUND) {
      return {
        useCase: null,
        communityWorkflow: null,
        redirectTo: null,
        missing: true,
      };
    }
    throw error;
  }
});

type Resolved = Awaited<ReturnType<typeof resolveUseCase>>;

/** The page's SEO facts, from whichever source resolved. */
function displayFromResolved(
  useCase: Resolved["useCase"],
  communityWorkflow: Resolved["communityWorkflow"],
) {
  return {
    title: useCase?.title ?? communityWorkflow?.title ?? "",
    description: useCase?.description ?? communityWorkflow?.description ?? "",
    action_type: "workflow" as const,
    integrations:
      useCase?.integrations ??
      communityWorkflow?.steps?.map((s) => s.category) ??
      [],
    categories: useCase?.categories ?? ["featured"],
    published_id: useCase?.published_id ?? communityWorkflow?.id ?? "",
    creator: (useCase?.creator ?? communityWorkflow?.creator) || undefined,
    steps: useCase?.steps ?? communityWorkflow?.steps,
  };
}

export default async function UseCaseDetailPage({ params }: PageProps) {
  const { slug } = await params;

  const { useCase, communityWorkflow, redirectTo, missing } =
    await resolveUseCase(slug);

  if (redirectTo) {
    redirect(redirectTo);
  }

  if (missing) {
    notFound();
  }

  const data = useCase || communityWorkflow;
  if (!data) {
    notFound();
  }

  const display = displayFromResolved(useCase, communityWorkflow);
  const structuredData = generateUseCaseStructuredData({ ...display, slug });

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Use Cases", url: `${siteConfig.url}/use-cases` },
    {
      name: display.title,
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

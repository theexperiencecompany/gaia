import type {
  CommunityWorkflow,
  UseCase,
} from "@/types/features/workflowTypes";

/**
 * Convert a community/explore workflow into the UseCase card shape.
 * Shared between the server-rendered /use-cases hub (SSR'd links for
 * crawlers) and the client-side explore store consumers.
 */
export function convertWorkflowToUseCase(workflow: CommunityWorkflow): UseCase {
  return {
    title: workflow.title,
    description: workflow.description,
    action_type: "workflow" as const,
    integrations:
      workflow.steps
        ?.map((s) => s.category)
        .filter((v, i, a) => a.indexOf(v) === i) || [],
    categories: workflow.categories || ["featured"],
    published_id: workflow.id,
    slug: workflow.slug ?? undefined,
    steps: workflow.steps,
    creator: workflow.creator,
    total_executions: workflow.total_executions || 0,
  };
}

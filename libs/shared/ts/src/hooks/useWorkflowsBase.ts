import type {
  Workflow,
  CommunityWorkflow,
} from "../types/workflow";

export const WorkflowQueryKeys = {
  all: ["workflows"] as const,
  list: (params?: Record<string, unknown>) =>
    params
      ? ([...WorkflowQueryKeys.all, "list", params] as const)
      : ([...WorkflowQueryKeys.all, "list"] as const),
  detail: (id: string) =>
    [...WorkflowQueryKeys.all, "detail", id] as const,
  executions: (workflowId: string) =>
    [...WorkflowQueryKeys.all, "executions", workflowId] as const,
  community: (params?: Record<string, unknown>) =>
    params
      ? ([...WorkflowQueryKeys.all, "community", params] as const)
      : ([...WorkflowQueryKeys.all, "community"] as const),
};

export interface WorkflowFilterState {
  search?: string;
  activated?: boolean;
  category?: string;
  tags?: string[];
  isPublic?: boolean;
  sourceIntegration?: string;
  isSystemWorkflow?: boolean;
}

export function filterWorkflows(
  workflows: Workflow[],
  filter: WorkflowFilterState,
): Workflow[] {
  return workflows.filter((workflow) => {
    if (filter.search) {
      const query = filter.search.toLowerCase();
      const matchesTitle = workflow.title.toLowerCase().includes(query);
      const matchesDescription = workflow.description
        .toLowerCase()
        .includes(query);
      if (!matchesTitle && !matchesDescription) {
        return false;
      }
    }

    if (filter.activated !== undefined && workflow.activated !== filter.activated) {
      return false;
    }

    if (filter.category && workflow.metadata.category !== filter.category) {
      return false;
    }

    if (filter.tags && filter.tags.length > 0) {
      const hasAllTags = filter.tags.every((tag) =>
        workflow.metadata.tags.includes(tag),
      );
      if (!hasAllTags) {
        return false;
      }
    }

    if (filter.isPublic !== undefined && workflow.is_public !== filter.isPublic) {
      return false;
    }

    if (
      filter.sourceIntegration !== undefined &&
      workflow.source_integration !== filter.sourceIntegration
    ) {
      return false;
    }

    if (
      filter.isSystemWorkflow !== undefined &&
      workflow.is_system_workflow !== filter.isSystemWorkflow
    ) {
      return false;
    }

    return true;
  });
}

export function sortWorkflows(workflows: Workflow[], sortBy: string): Workflow[] {
  const sorted = [...workflows];

  switch (sortBy) {
    case "title_asc":
      return sorted.sort((a, b) => a.title.localeCompare(b.title));
    case "title_desc":
      return sorted.sort((a, b) => b.title.localeCompare(a.title));
    case "created_at_asc":
      return sorted.sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      );
    case "created_at_desc":
      return sorted.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    case "updated_at_desc":
      return sorted.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
    case "executions_desc":
      return sorted.sort(
        (a, b) => b.total_executions - a.total_executions,
      );
    case "last_executed_desc":
      return sorted.sort((a, b) => {
        const aTime = a.last_executed_at
          ? new Date(a.last_executed_at).getTime()
          : 0;
        const bTime = b.last_executed_at
          ? new Date(b.last_executed_at).getTime()
          : 0;
        return bTime - aTime;
      });
    default:
      return sorted;
  }
}

export function getWorkflowStatus(workflow: Workflow): string {
  if (!workflow.activated) {
    return "inactive";
  }

  if (workflow.error_message) {
    return "error";
  }

  const trigger = workflow.trigger_config;
  if (!trigger.enabled) {
    return "paused";
  }

  if (trigger.type === "schedule" && trigger.next_run) {
    return "scheduled";
  }

  return "active";
}


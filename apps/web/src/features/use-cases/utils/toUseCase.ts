import type {
  CommunityWorkflow,
  UseCase,
} from "@/types/features/workflowTypes";

const uniqueStepCategories = (steps: CommunityWorkflow["steps"]): string[] =>
  Array.from(new Set(steps.map((step) => step.category)));

/** A marketplace card as the use-case grid renders it. */
export const toUseCase = (w: CommunityWorkflow): UseCase => ({
  title: w.title,
  description: w.description,
  action_type: "workflow",
  icon: w.icon,
  icon_color: w.icon_color,
  system_workflow_key: w.system_workflow_key,
  source_integration: w.source_integration,
  trigger_config: w.trigger_config ?? undefined,
  integrations: uniqueStepCategories(w.steps),
  categories: w.categories || ["featured"],
  published_id: w.id,
  slug: w.slug,
  steps: w.steps,
  creator: w.creator,
  total_executions: w.total_executions || 0,
});

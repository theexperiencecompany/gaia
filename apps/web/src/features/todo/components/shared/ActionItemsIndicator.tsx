import WorkflowIcons from "@/features/workflows/components/shared/WorkflowIcons";

interface ActionItemsIndicatorProps {
  steps: Array<{ category: string }>;
  iconSize?: number;
}

/**
 * Displays rotated tool category icons for workflow action items.
 * Uses the shared WorkflowIcons component.
 */
export function ActionItemsIndicator({
  steps,
  iconSize = 16,
}: ActionItemsIndicatorProps) {
  if (!steps || steps.length === 0) return null;

  return <WorkflowIcons steps={steps} iconSize={iconSize} maxIcons={3} />;
}

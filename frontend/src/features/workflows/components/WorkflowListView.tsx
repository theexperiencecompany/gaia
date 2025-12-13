"use client";

import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";

import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { WorkflowSquare05Icon } from "@/icons";
import type { Workflow } from "@/types/features/workflowTypes";

// Get unique tool categories from workflow steps (max 4)
const getWorkflowIcons = (workflow: Workflow): string[] => {
  return Array.from(
    new Set(workflow.steps.map((step) => step.tool_category)),
  ).slice(0, 4);
};

// Memoized workflow row component
const WorkflowRow = memo(
  ({
    workflow,
    onClick,
  }: {
    workflow: Workflow;
    onClick: (id: string) => void;
  }) => {
    const iconCategories = useMemo(
      () => getWorkflowIcons(workflow),
      [workflow],
    );

    const handleClick = useCallback(() => {
      onClick(workflow.id);
    }, [onClick, workflow.id]);

    return (
      <div
        className="flex cursor-pointer items-center gap-3 rounded-2xl bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-700/50"
        onClick={handleClick}
      >
        {/* Stacked Icons matching workflow cards */}
        <div className="relative flex h-10 flex-shrink-0 items-center justify-center">
          {iconCategories.length === 1 ? (
            // Single icon - centered
            getToolCategoryIcon(iconCategories[0], {
              width: 24,
              height: 24,
              showBackground: true,
            })
          ) : (
            // Multiple icons - stacked in a row with rotation
            <div className="flex -space-x-1.5">
              {iconCategories.map((category, index) => (
                <div
                  key={category}
                  className="relative"
                  style={{
                    rotate: index % 2 === 0 ? "8deg" : "-8deg",
                    zIndex: iconCategories.length - index,
                  }}
                >
                  {getToolCategoryIcon(category, {
                    width: 24,
                    height: 24,
                    showBackground: true,
                  })}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Workflow Title */}
        <div className="min-w-0 flex-1">
          <h4 className="font-medium text-white line-clamp-1">
            {workflow.title}
          </h4>
          {workflow.description && (
            <p className="mt-0.5 text-xs text-zinc-400 line-clamp-1">
              {workflow.description}
            </p>
          )}
        </div>
      </div>
    );
  },
);

WorkflowRow.displayName = "WorkflowRow";

interface WorkflowListViewProps {
  workflows?: Workflow[];
}

const WorkflowListView = memo(({ workflows = [] }: WorkflowListViewProps) => {
  const router = useRouter();

  const handleWorkflowClick = useCallback(
    (workflowId: string) => {
      router.push(`/workflows?id=${workflowId}`);
    },
    [router],
  );

  // Memoize first 5 workflows
  const displayWorkflows = useMemo(() => workflows.slice(0, 5), [workflows]);

  const isEmpty = workflows.length === 0;

  return (
    <BaseCardView
      title="Workflows"
      icon={<WorkflowSquare05Icon className="h-6 w-6 text-zinc-500" />}
      isEmpty={isEmpty}
      emptyMessage="No workflows created yet"
      errorMessage="Failed to load workflows"
      path="/workflows"
    >
      <div className="space-y-2 p-4">
        {displayWorkflows.map((workflow) => (
          <WorkflowRow
            key={workflow.id}
            workflow={workflow}
            onClick={handleWorkflowClick}
          />
        ))}
      </div>
    </BaseCardView>
  );
});

WorkflowListView.displayName = "WorkflowListView";

export default WorkflowListView;

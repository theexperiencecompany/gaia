"use client";

import {
  AlertCircleIcon,
  InformationCircleIcon,
  MagicWand01Icon,
  WorkflowSquare05Icon,
  ZapIcon,
} from "@icons";
import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";
import type { CardAction } from "@/features/chat/components/interface/BaseCardView";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { useAppendToInput } from "@/stores/composerStore";
import type { Workflow } from "@/types/features/workflowTypes";
import WorkflowIcons from "./shared/WorkflowIcons";

// Memoized workflow row component
const WorkflowRow = memo(
  ({
    workflow,
    onClick,
  }: {
    workflow: Workflow;
    onClick: (id: string) => void;
  }) => {
    const handleClick = useCallback(() => {
      onClick(workflow.id);
    }, [onClick, workflow.id]);

    return (
      <div
        className="flex cursor-pointer items-center gap-3 rounded-2xl bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-700/50"
        onClick={handleClick}
      >
        {/* Stacked Icons matching workflow cards */}
        <div className="relative flex h-10 shrink-0 items-center justify-center">
          <WorkflowIcons steps={workflow.steps} iconSize={24} maxIcons={4} />
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
  const appendToInput = useAppendToInput();

  const handleWorkflowClick = useCallback(
    (workflowId: string) => {
      router.push(`/workflows?id=${workflowId}`);
    },
    [router],
  );

  // Show first 5 workflows
  const displayWorkflows = workflows.slice(0, 5);

  const isEmpty = workflows.length === 0;

  const actions: CardAction[] = useMemo(
    () => [
      {
        key: "suggest-workflows",
        icon: <MagicWand01Icon className="size-4 text-zinc-400" />,
        label: "Suggest new workflows",
        description:
          "Analyse my email and calendar patterns and propose automations",
        onPress: () =>
          appendToInput(
            "Based on my email, calendar, and todo patterns, suggest 5 high-impact workflows I should set up in GAIA. For each one, explain what it would automate and how much time it would save me.",
          ),
      },
      {
        key: "audit-health",
        icon: <AlertCircleIcon className="size-4 text-zinc-400" />,
        label: "Audit workflow health",
        description:
          "Check which workflows haven't triggered recently and flag broken ones",
        onPress: () =>
          appendToInput(
            "Review my active workflows and check their recent activity. Identify any that haven't triggered in a while, seem broken, or may need updating. Give me a health report.",
          ),
      },
      {
        key: "explain-workflows",
        icon: <InformationCircleIcon className="size-4 text-zinc-400" />,
        label: "Explain my workflows",
        description: "Get a plain-English summary of what each workflow does",
        onPress: () =>
          appendToInput(
            "Give me a plain-English summary of each of my active workflows — what triggers them, what they do, and what problem they're solving for me.",
          ),
      },
      {
        key: "optimise",
        icon: <ZapIcon className="size-4 text-zinc-400" />,
        label: "Optimise a workflow",
        description:
          "Review a specific workflow and suggest improvements to its steps",
        onPress: () =>
          appendToInput(
            "Pick the workflow that seems most complex or most frequently triggered and suggest specific improvements to its steps, triggers, or logic to make it more reliable or efficient.",
          ),
      },
    ],
    [appendToInput],
  );

  return (
    <BaseCardView
      title="Workflows"
      icon={<WorkflowSquare05Icon className="h-6 w-6 text-zinc-500" />}
      isEmpty={isEmpty}
      emptyMessage="No workflows created yet"
      errorMessage="Failed to load workflows"
      path="/workflows"
      actions={actions}
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

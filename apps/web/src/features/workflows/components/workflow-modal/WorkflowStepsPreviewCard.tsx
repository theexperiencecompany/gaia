"use client";

import WorkflowSteps from "../shared/WorkflowSteps";

// Shared surface for every "steps" card (the tabbed Steps/History panel and the
// read-only previews) so they never drift in background or radius. `lg:h-full`
// (not `h-full`) so that when the layout stacks vertically the card grows to its
// content and the page scrolls, instead of being trapped at a fixed height.
export const STEPS_CARD_SURFACE =
  "flex min-h-0 w-full flex-col overflow-hidden rounded-2xl bg-zinc-800/50 p-4 lg:h-full";

interface WorkflowStepData {
  id: string;
  title: string;
  description: string;
  category: string;
}

interface WorkflowStepsPreviewCardProps {
  steps: WorkflowStepData[];
  emptyMessage?: string;
}

export default function WorkflowStepsPreviewCard({
  steps,
  emptyMessage = "Steps will be generated when this workflow runs.",
}: Readonly<WorkflowStepsPreviewCardProps>) {
  return (
    <div className={STEPS_CARD_SURFACE}>
      <div className="mb-1 flex items-center gap-2 px-2 pt-1">
        <span className="text-sm font-medium text-zinc-200">Steps</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {steps.length ? (
          <WorkflowSteps steps={steps} />
        ) : (
          <div className="py-6 text-center text-sm text-zinc-500">
            {emptyMessage}
          </div>
        )}
      </div>
    </div>
  );
}

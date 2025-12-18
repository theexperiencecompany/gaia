"use client";

import WorkflowStep from "./WorkflowStep";

interface WorkflowStepsProps {
  steps: Array<{
    id: string;
    title: string;
    description: string;
    tool_name: string;
    tool_category: string;
  }>;
  size?: "small" | "large";
}

export default function WorkflowSteps({
  steps,
  size = "small",
}: WorkflowStepsProps) {
  const timelineLeftPosition = size === "large" ? "left-[15px]" : "left-[13px]";
  const timelineTopPosition = size === "large" ? "top-5" : "top-4";

  return (
    <div className="relative">
      <div
        className={`absolute ${timelineTopPosition} bottom-8 ${timelineLeftPosition} w-[1px] bg-gradient-to-b from-primary via-primary/80 to-transparent`}
      />

      <div className="space-y-8">
        {steps.map((step, index) => (
          <WorkflowStep key={step.id} step={step} index={index} size={size} />
        ))}
      </div>
    </div>
  );
}

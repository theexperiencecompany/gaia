"use client";

import { m } from "motion/react";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

interface OnboardingWorkflowCardsProps {
  workflows: Array<{
    id?: string;
    title: string;
    description?: string;
    categories?: string[];
  }>;
}

export function OnboardingWorkflowCards({
  workflows,
}: OnboardingWorkflowCardsProps) {
  return (
    <m.div
      className="flex flex-col gap-2 ml-10.75"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="grid grid-cols-3 gap-3">
        {workflows.map((workflow, index) => (
          <m.div
            key={workflow.id ?? `workflow-${index}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: index * 0.08,
              duration: 0.35,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            <UnifiedWorkflowCard
              title={workflow.title}
              description={workflow.description}
              steps={
                workflow.categories?.map((c) => ({
                  category: c,
                  title: c,
                  description: "",
                })) ?? []
              }
              primaryAction="none"
              showTrigger={false}
              showExecutions={false}
              showActivationStatus={false}
            />
          </m.div>
        ))}
      </div>
      <p className="text-xs text-zinc-500">
        These run automatically. Customize them anytime in Workflows.
      </p>
    </m.div>
  );
}

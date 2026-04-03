"use client";

import { ZapIcon } from "@icons";
import { m } from "motion/react";

interface OnboardingWorkflowCardsProps {
  workflows: Array<{ id?: string; title: string; description?: string }>;
}

export function OnboardingWorkflowCards({
  workflows,
}: OnboardingWorkflowCardsProps) {
  return (
    <m.div
      className="flex flex-col gap-2"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex flex-row gap-3 overflow-x-auto">
        {workflows.map((workflow, index) => (
          <m.div
            key={workflow.id ?? `workflow-${index}`}
            className="flex w-[200px] shrink-0 flex-col gap-1.5 rounded-2xl border border-zinc-700/50 bg-zinc-800/60 p-3"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: index * 0.08,
              duration: 0.35,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            <div className="flex items-center gap-2">
              <ZapIcon className="size-3.5 shrink-0 text-zinc-400" />
              <p className="truncate text-sm font-bold text-zinc-200">
                {workflow.title}
              </p>
            </div>
            {workflow.description && (
              <p className="line-clamp-2 text-xs text-zinc-400">
                {workflow.description}
              </p>
            )}
          </m.div>
        ))}
      </div>
      <p className="text-xs text-zinc-500">
        These run automatically. Customize them anytime in Workflows.
      </p>
    </m.div>
  );
}

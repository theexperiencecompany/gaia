"use client";

import { ZapIcon } from "@icons";
import { m } from "motion/react";
import type { WorkflowResults } from "../../types/websocket";

type WorkflowsRevealCardProps = WorkflowResults;

const MAX_DISPLAY_ITEMS = 5;

export function WorkflowsRevealCard({ workflows }: WorkflowsRevealCardProps) {
  const displayedWorkflows = workflows.slice(0, MAX_DISPLAY_ITEMS);
  const remainingCount = workflows.length - displayedWorkflows.length;

  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        Created{" "}
        <span className="font-medium text-zinc-300">{workflows.length}</span>{" "}
        {workflows.length === 1 ? "workflow" : "workflows"}
      </p>
      {displayedWorkflows.length > 0 && (
        <div className="flex flex-col gap-2">
          {displayedWorkflows.map((workflow, index) => (
            <div
              key={workflow.id ?? `workflow-${index}`}
              className="flex items-start gap-2"
            >
              <ZapIcon className="mt-0.5 size-3.5 shrink-0 text-zinc-500" />
              <div>
                <p className="text-sm text-zinc-300">{workflow.title}</p>
                {workflow.description && (
                  <p className="text-xs text-zinc-500">
                    {workflow.description}
                  </p>
                )}
              </div>
            </div>
          ))}
          {remainingCount > 0 && (
            <p className="text-xs text-zinc-500">+ {remainingCount} more</p>
          )}
        </div>
      )}
    </m.div>
  );
}

"use client";

import { ZapIcon } from "@icons";
import * as m from "motion/react-m";
import type { WorkflowResults } from "../../types/websocket";

type WorkflowsRevealCardProps = WorkflowResults;

const MAX_DISPLAY_ITEMS = 5;

export function WorkflowsRevealCard({ workflows }: WorkflowsRevealCardProps) {
  const displayedWorkflows = workflows.slice(0, MAX_DISPLAY_ITEMS);
  const remainingCount = workflows.length - displayedWorkflows.length;

  return (
    <m.div
      className="ml-10.75 overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        Created{" "}
        <span className="font-medium text-zinc-300">{workflows.length}</span>{" "}
        {workflows.length === 1 ? "workflow" : "workflows"}
      </p>
      {displayedWorkflows.length > 0 && (
        <div className="flex flex-col gap-2">
          {displayedWorkflows.map((workflow, index) => (
            <m.div
              key={workflow.id ?? `workflow-${index}`}
              className="flex items-start gap-2"
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                delay: index * 0.06,
                duration: 0.25,
                ease: [0.19, 1, 0.22, 1],
              }}
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
            </m.div>
          ))}
          {remainingCount > 0 && (
            <p className="text-xs text-zinc-500">+ {remainingCount} more</p>
          )}
        </div>
      )}
    </m.div>
  );
}

"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { FlowIcon, PencilEdit01Icon } from "@icons";
import { useState } from "react";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

import {
  getWorkflowTriggerDisplay,
  WorkflowTriggerChip,
} from "./shared/WorkflowCardComponents";
import WorkflowModal from "./WorkflowModal";

interface WorkflowDraftCardProps {
  draft: WorkflowDraftData;
}

export default function WorkflowDraftCard({ draft }: WorkflowDraftCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);

  const trigger = getWorkflowTriggerDisplay({
    type: draft.trigger_type,
    cronExpression: draft.cron_expression,
    triggerName: draft.trigger_slug,
  });

  return (
    <>
      <div
        className="group relative z-1 flex w-full max-w-md cursor-pointer flex-col gap-3 rounded-3xl border border-dashed border-warning/40 bg-zinc-800/40 p-4 backdrop-blur-lg transition-all hover:bg-zinc-700/50"
        onClick={() => setIsModalOpen(true)}
      >
        <Chip
          size="sm"
          variant="flat"
          color="warning"
          classNames={{
            base: "absolute -top-2 -right-2 bg-warning/20",
            content: "text-xs font-semibold text-warning",
          }}
        >
          Draft
        </Chip>

        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/15">
              <FlowIcon className="size-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <span className="line-clamp-2 text-base font-medium leading-tight">
                {draft.suggested_title}
              </span>
              <span className="text-xs text-warning/80">
                Review to create workflow
              </span>
            </div>
          </div>
          <WorkflowTriggerChip trigger={trigger} />
        </div>

        <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
          {draft.suggested_description}
        </p>

        {draft.trigger_type === "integration" && (
          <p className="text-xs text-zinc-500">
            Configure trigger settings to complete setup
          </p>
        )}

        <Button
          size="sm"
          color="primary"
          variant="flat"
          startContent={<PencilEdit01Icon className="size-3.5" />}
          onPress={() => setIsModalOpen(true)}
          className="mt-1 w-full rounded-xl font-medium"
        >
          Review & Create
        </Button>
      </div>

      {isModalOpen && (
        <WorkflowModal
          isOpen={isModalOpen}
          onOpenChange={setIsModalOpen}
          mode="create"
          draftData={draft}
        />
      )}
    </>
  );
}

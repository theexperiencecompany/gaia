"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { useState } from "react";
import {
  CreateWorkflowModal,
  WorkflowModal,
} from "@/features/workflows/components";
import WorkflowIcons from "@/features/workflows/components/shared/WorkflowIcons";
import { useWorkflows } from "@/features/workflows/hooks";
import { ZapIcon } from "@/icons";
import type { Workflow } from "@/types/features/workflowTypes";

export default function WorkflowsSidebar() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { workflows, isLoading } = useWorkflows();

  // State for editing a specific workflow
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(
    null,
  );
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  const handleWorkflowClick = (workflow: Workflow) => {
    setSelectedWorkflow(workflow);
    setIsEditModalOpen(true);
  };

  return (
    <>
      <div className="flex flex-col gap-3">
        <Tooltip
          content={
            <span className="flex items-center gap-2">
              New Workflow
              <Kbd className="text-[10px]">C</Kbd>
            </span>
          }
          placement="right"
        >
          <Button
            color="primary"
            size="sm"
            fullWidth
            className="mb-2 flex justify-start text-sm font-medium text-primary"
            variant="flat"
            onPress={onOpen}
            data-keyboard-shortcut="create-workflow"
          >
            <ZapIcon width={18} height={18} />
            New Workflow
          </Button>
        </Tooltip>

        {/* Workflows List */}
        <div className="flex flex-col overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-4">
              <Spinner size="sm" />
            </div>
          ) : workflows.length === 0 ? (
            <p className="text-xs text-zinc-500 px-2 py-2">No workflows yet</p>
          ) : (
            workflows.map((workflow) => (
              <button
                key={workflow.id}
                type="button"
                onClick={() => handleWorkflowClick(workflow)}
                className="flex items-center justify-between gap-2 rounded-xl px-2 pl-3 py-0.5 text-left transition-colors hover:bg-zinc-800/60 cursor-pointer"
              >
                <span className="truncate text-sm text-zinc-300">
                  {workflow.title}
                </span>
                <WorkflowIcons
                  steps={workflow.steps || []}
                  iconSize={20}
                  maxIcons={3}
                  className="-space-x-2.5!"
                />
              </button>
            ))
          )}
        </div>
      </div>

      <CreateWorkflowModal isOpen={isOpen} onOpenChange={onOpenChange} />

      {/* Edit Workflow Modal */}
      {selectedWorkflow && (
        <WorkflowModal
          isOpen={isEditModalOpen}
          onOpenChange={(open) => {
            setIsEditModalOpen(open);
            if (!open) {
              setSelectedWorkflow(null);
            }
          }}
          existingWorkflow={selectedWorkflow}
          mode="edit"
        />
      )}
    </>
  );
}

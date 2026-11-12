"use client";

import { Kbd, Spinner, Tooltip, useOverlayState } from "@heroui/react";
import { ZapIcon } from "@icons";
import { useRef, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import CreateWorkflowModal from "@/features/workflows/components/CreateWorkflowModal";
import WorkflowIcons from "@/features/workflows/components/shared/WorkflowIcons";
import WorkflowModal from "@/features/workflows/components/WorkflowModal";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import type { Workflow } from "@/types/features/workflowTypes";

export default function WorkflowsSidebar() {
  const { isOpen, open, setOpen } = useOverlayState();
  const { workflows, isLoading } = useWorkflows();

  // State for editing a specific workflow
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(
    null,
  );
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const clearTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleWorkflowClick = (workflow: Workflow) => {
    setSelectedWorkflow(workflow);
    setIsEditModalOpen(true);
  };

  return (
    <>
      <div className="flex flex-col gap-3">
        <Tooltip>
          <GaiaButton
            variant="accent-soft"
            size="sm"
            fullWidth
            className="mb-2 flex justify-start text-sm font-medium text-primary"
            onPress={open}
            data-keyboard-shortcut="create-workflow"
          >
            <ZapIcon width={18} height={18} />
            New Workflow
          </GaiaButton>
          <Tooltip.Content placement="right">
            <span className="flex items-center gap-2">
              New Workflow
              <Kbd className="text-[10px]">C</Kbd>
            </span>
          </Tooltip.Content>
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
                  icon={workflow.icon}
                  iconColor={workflow.icon_color}
                  iconSize={17}
                  maxIcons={3}
                  spacing="-space-x-3.5!"
                  showBackground={true}
                />
              </button>
            ))
          )}
        </div>
      </div>

      <CreateWorkflowModal isOpen={isOpen} onOpenChange={setOpen} />

      {/* Edit Workflow Modal */}
      <WorkflowModal
        isOpen={isEditModalOpen}
        onOpenChange={(open) => {
          setIsEditModalOpen(open);
          if (!open) {
            if (clearTimeoutRef.current) clearTimeout(clearTimeoutRef.current);
            clearTimeoutRef.current = setTimeout(
              () => setSelectedWorkflow(null),
              300,
            );
          }
        }}
        existingWorkflow={selectedWorkflow}
        mode="edit"
      />
    </>
  );
}

"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { Tooltip } from "@heroui/tooltip";
import { CreateWorkflowModal } from "@/features/workflows/components";
import { useWorkflows } from "@/features/workflows/hooks";
import { ZapIcon } from "@/icons";

export default function WorkflowsSidebar() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { refetch } = useWorkflows(false);

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
            className="mb-4 flex justify-start text-sm font-medium text-primary"
            variant="flat"
            onPress={onOpen}
            data-keyboard-shortcut="create-workflow"
          >
            <ZapIcon width={18} height={18} />
            New Workflow
          </Button>
        </Tooltip>
      </div>

      <CreateWorkflowModal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        onWorkflowCreated={refetch}
        onWorkflowListRefresh={refetch}
      />
    </>
  );
}

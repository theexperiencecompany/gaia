"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";

import { ZapIcon } from "@/icons";

interface WorkflowsSidebarProps {
  onCreateWorkflow?: () => void;
}

export default function WorkflowsSidebar({
  onCreateWorkflow,
}: WorkflowsSidebarProps) {
  const handleCreate = () => {
    if (onCreateWorkflow) {
      onCreateWorkflow();
    } else {
      // Fallback: click the header button which has the modal
      const headerButton = document.querySelector(
        '[data-keyboard-shortcut="create-workflow"]',
      ) as HTMLButtonElement;
      headerButton?.click();
    }
  };

  return (
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
          onPress={handleCreate}
        >
          <ZapIcon width={18} height={18} />
          New Workflow
        </Button>
      </Tooltip>
    </div>
  );
}

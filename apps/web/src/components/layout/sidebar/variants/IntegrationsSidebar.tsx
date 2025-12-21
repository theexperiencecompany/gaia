"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { Tooltip } from "@heroui/tooltip";

import { MCPIntegrationModal } from "@/features/integrations/components/MCPIntegrationModal";
import { PlusSignIcon } from "@/icons";

export default function IntegrationsSidebar() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();

  return (
    <>
      <div className="flex flex-col space-y-3">
        <Tooltip
          content={
            <span className="flex items-center gap-2">
              Create Custom Integration
              <Kbd className="text-[10px]">C</Kbd>
            </span>
          }
          placement="right"
        >
          <Button
            className="w-full justify-start text-sm text-primary"
            color="primary"
            size="sm"
            variant="flat"
            startContent={<PlusSignIcon className="h-4 w-4 outline-0" />}
            onPress={onOpen}
            data-keyboard-shortcut="create-integration"
          >
            Create Custom Integration
          </Button>
        </Tooltip>
      </div>

      <MCPIntegrationModal isOpen={isOpen} onClose={() => onOpenChange()} />
    </>
  );
}

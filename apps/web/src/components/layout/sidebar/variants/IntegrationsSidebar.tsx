"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { useCallback } from "react";

import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { MCPIntegrationModal } from "@/features/integrations/components/MCPIntegrationModal";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { PlusSignIcon } from "@/icons";
import { cn } from "@/lib";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { accordionItemStyles } from "../constants";

export default function IntegrationsSidebar() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { integrations, connectIntegration, disconnectIntegration } =
    useIntegrations();

  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const closeRightSidebar = useRightSidebar((state) => state.close);

  const handleIntegrationClick = useCallback(
    (integration: Integration) => {
      const handleDisconnect = async (id: string) => {
        await disconnectIntegration(id);
        setTimeout(() => closeRightSidebar(), 500);
      };

      setRightSidebarContent(
        <IntegrationSidebar
          integration={integration}
          onConnect={connectIntegration}
          onDisconnect={handleDisconnect}
          category={integration.name}
        />,
      );
      openRightSidebar("sidebar");
    },
    [
      setRightSidebarContent,
      openRightSidebar,
      connectIntegration,
      disconnectIntegration,
      closeRightSidebar,
    ],
  );

  const renderIntegrationItem = (integration: Integration) => {
    const isConnected = integration.status === "connected";

    return (
      <Button
        key={integration.id}
        fullWidth
        onPress={() => handleIntegrationClick(integration)}
        className="justify-start px-2 text-start text-sm text-zinc-500 hover:text-zinc-300"
        variant="light"
        radius="sm"
        size="sm"
        startContent={
          <div className="relative">
            {getToolCategoryIcon(
              integration.id,
              {
                size: 18,
                width: 18,
                height: 18,
                showBackground: false,
              },
              integration.iconUrl,
            )}
          </div>
        }
      >
        <div className="flex items-center justify-between w-full">
          <span className="truncate">{integration.name}</span>

          {isConnected && (
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
          )}
        </div>
      </Button>
    );
  };

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

        {integrations.length > 0 && (
          <div className="space-y-1">
            <ScrollShadow className="max-h-[calc(100vh-27rem)]" hideScrollBar>
              <div className="space-y-0.5">
                {integrations.map(renderIntegrationItem)}
              </div>
            </ScrollShadow>
          </div>
        )}
      </div>

      <MCPIntegrationModal isOpen={isOpen} onClose={() => onOpenChange()} />
    </>
  );
}

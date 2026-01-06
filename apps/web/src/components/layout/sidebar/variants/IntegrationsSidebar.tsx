"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { useCallback, useMemo } from "react";

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

  const connectedIntegrations = useMemo(
    () => integrations.filter((i) => i.status === "connected"),
    [integrations],
  );

  const notConnectedIntegrations = useMemo(
    () => integrations.filter((i) => i.status !== "connected"),
    [integrations],
  );

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

  const renderIntegrationItem = (integration: Integration) => (
    <Button
      key={integration.id}
      fullWidth
      onPress={() => handleIntegrationClick(integration)}
      className={`justify-start px-2 text-start text-sm text-zinc-500 hover:text-zinc-300
      `}
      variant="light"
      radius="sm"
      size="sm"
      startContent={getToolCategoryIcon(
        integration.id,
        {
          size: 18,
          width: 18,
          height: 18,
          showBackground: false,
        },
        integration.iconUrl,
      )}
    >
      <span className="truncate">{integration.name}</span>
    </Button>
  );

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

        {connectedIntegrations.length > 0 && (
          <div className="space-y-1">
            <span className={cn(accordionItemStyles.trigger)}>
              Connected ({connectedIntegrations.length})
            </span>
            <ScrollShadow className="max-h-62">
              <div className="space-y-0.5">
                {connectedIntegrations.map(renderIntegrationItem)}
              </div>
            </ScrollShadow>
          </div>
        )}

        {notConnectedIntegrations.length > 0 && (
          <div className="space-y-1">
            <span className={cn(accordionItemStyles.trigger)}>
              Available ({notConnectedIntegrations.length})
            </span>
            <ScrollShadow className="max-h-62">
              <div className="space-y-0.5">
                {notConnectedIntegrations.map(renderIntegrationItem)}
              </div>
            </ScrollShadow>
          </div>
        )}
      </div>

      <MCPIntegrationModal isOpen={isOpen} onClose={() => onOpenChange()} />
    </>
  );
}

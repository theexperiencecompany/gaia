"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useDisclosure } from "@heroui/modal";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { useCallback, useEffect, useRef, useState } from "react";

import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { MCPIntegrationModal } from "@/features/integrations/components/MCPIntegrationModal";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { CursorAddSelectionIcon, InternetIcon } from "@/icons";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsSidebar() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const {
    integrations,
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
  } = useIntegrations();

  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const isSidebarOpen = useRightSidebar((state) => state.isOpen);

  // Track which integration is currently shown in the right sidebar
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);

  // Store callbacks in refs to avoid triggering useEffect on every render
  // These callbacks from useIntegrations() are not memoized and change on every render
  const callbacksRef = useRef({
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
    closeRightSidebar,
    setRightSidebarContent,
  });

  // Keep refs up to date
  useEffect(() => {
    callbacksRef.current = {
      connectIntegration,
      disconnectIntegration,
      deleteCustomIntegration,
      publishIntegration,
      unpublishIntegration,
      closeRightSidebar,
      setRightSidebarContent,
    };
  });

  // Update sidebar content when integrations change (e.g., after publish/unpublish)
  useEffect(() => {
    if (!selectedIntegrationId || !isSidebarOpen) return;

    const selectedIntegration = integrations.find(
      (i) => i.id === selectedIntegrationId,
    );

    if (!selectedIntegration) return;

    const handleDisconnect = async (id: string) => {
      await callbacksRef.current.disconnectIntegration(id);
      setTimeout(() => callbacksRef.current.closeRightSidebar(), 500);
      setSelectedIntegrationId(null);
    };

    const handleDelete = async (id: string) => {
      await callbacksRef.current.deleteCustomIntegration(id);
      setTimeout(() => callbacksRef.current.closeRightSidebar(), 500);
      setSelectedIntegrationId(null);
    };

    const handlePublish = async (id: string) => {
      await callbacksRef.current.publishIntegration(id);
    };

    const handleUnpublish = async (id: string) => {
      await callbacksRef.current.unpublishIntegration(id);
    };

    const isCustomIntegration = selectedIntegration.source === "custom";

    callbacksRef.current.setRightSidebarContent(
      <IntegrationSidebar
        integration={selectedIntegration}
        onConnect={callbacksRef.current.connectIntegration}
        onDisconnect={handleDisconnect}
        onDelete={isCustomIntegration ? handleDelete : undefined}
        onPublish={isCustomIntegration ? handlePublish : undefined}
        onUnpublish={isCustomIntegration ? handleUnpublish : undefined}
        category={selectedIntegration.name}
      />,
    );
  }, [selectedIntegrationId, integrations, isSidebarOpen]);

  // Clear selected integration when sidebar closes
  useEffect(() => {
    return useRightSidebar.subscribe((state, prevState) => {
      if (prevState.isOpen && !state.isOpen && selectedIntegrationId) {
        setSelectedIntegrationId(null);
      }
    });
  }, [selectedIntegrationId]);

  const handleIntegrationClick = useCallback(
    (integration: Integration) => {
      setSelectedIntegrationId(integration.id);
      openRightSidebar("sidebar");
    },
    [openRightSidebar],
  );

  const renderIntegrationItem = (integration: Integration) => {
    const isConnected = integration.status === "connected";
    const isCreated = integration.status === "created";
    const isPublic = integration.isPublic === true;

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

          <div className="flex items-center gap-2">
            {isPublic && (
              <InternetIcon width={14} height={14} className="text-primary" />
            )}
            {isConnected && (
              <span className="h-1.5 w-1.5 rounded-full bg-success" />
            )}
            {isCreated && (
              <span className="h-1.5 w-1.5 rounded-full bg-warning" />
            )}
          </div>
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
            startContent={
              <CursorAddSelectionIcon className="h-4 w-4 outline-0" />
            }
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

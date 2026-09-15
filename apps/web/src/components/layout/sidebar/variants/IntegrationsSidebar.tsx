"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { InternetIcon, PuzzleIcon } from "@icons";
import { useCallback, useMemo, useState } from "react";
import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { useIntegrationModalActions } from "@/stores/uiStore";

export default function IntegrationsSidebar() {
  const { openIntegrationModal } = useIntegrationModalActions();
  const {
    integrations,
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
  } = useIntegrations();

  // Track which integration is currently shown in the right sidebar
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);

  const clearSelection = useCallback(() => setSelectedIntegrationId(null), []);

  const selectedIntegration = useMemo(
    () => integrations.find((i) => i.id === selectedIntegrationId) ?? null,
    [integrations, selectedIntegrationId],
  );

  const handleDisconnect = useCallback(
    async (id: string) => {
      await disconnectIntegration(id);
      setSelectedIntegrationId(null);
    },
    [disconnectIntegration],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteCustomIntegration(id);
      setSelectedIntegrationId(null);
    },
    [deleteCustomIntegration],
  );

  const handleIntegrationClick = useCallback((integration: Integration) => {
    setSelectedIntegrationId(integration.id);
  }, []);

  const renderIntegrationItem = useCallback(
    (integration: Integration) => {
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
              <IntegrationIcon
                integrationId={integration.id}
                iconUrl={integration.iconUrl}
                size={18}
              />
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
    },
    [handleIntegrationClick],
  );

  const isCustomIntegration = selectedIntegration?.source === "custom";

  return (
    <div className="flex flex-col space-y-3">
      {selectedIntegration && (
        <RightSidebarPanel mode="sidebar" onClose={clearSelection}>
          <IntegrationSidebar
            integration={selectedIntegration}
            onConnect={connectIntegration}
            onDisconnect={handleDisconnect}
            onDelete={isCustomIntegration ? handleDelete : undefined}
            onPublish={isCustomIntegration ? publishIntegration : undefined}
            onUnpublish={isCustomIntegration ? unpublishIntegration : undefined}
            category={selectedIntegration.name}
          />
        </RightSidebarPanel>
      )}
      <Tooltip
        content={
          <span className="flex items-center gap-2">
            Create Integration
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
          startContent={<PuzzleIcon className="h-4 w-4 outline-0" />}
          onPress={openIntegrationModal}
          data-keyboard-shortcut="create-integration"
        >
          Create Integration
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
  );
}

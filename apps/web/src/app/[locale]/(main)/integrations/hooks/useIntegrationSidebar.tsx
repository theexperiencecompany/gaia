"use client";

import { useCallback, useEffect, useMemo } from "react";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import type { Integration } from "@/features/integrations/types";
import { useRightSidebar } from "@/stores/rightSidebarStore";

interface UseIntegrationSidebarOptions {
  integrations: Integration[];
  selectedIntegrationId: string | null;
  settlingIntegrationId: string | null;
  connectIntegration: (
    id: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  disconnectIntegration: (id: string) => Promise<void>;
  deleteCustomIntegration: (id: string) => Promise<void>;
  publishIntegration: (id: string) => Promise<void>;
  unpublishIntegration: (id: string) => Promise<void>;
}

export function useIntegrationSidebar({
  integrations,
  selectedIntegrationId,
  settlingIntegrationId,
  connectIntegration,
  disconnectIntegration,
  deleteCustomIntegration,
  publishIntegration,
  unpublishIntegration,
}: UseIntegrationSidebarOptions) {
  const setRightSidebarContent = useRightSidebar((s) => s.setContent);
  const closeRightSidebar = useRightSidebar((s) => s.close);
  const isSidebarOpen = useRightSidebar((s) => s.isOpen);

  const selectedIntegration = useMemo(
    () => integrations.find((i) => i.id === selectedIntegrationId) ?? null,
    [integrations, selectedIntegrationId],
  );

  const handleDisconnect = useCallback(
    async (id: string) => {
      await disconnectIntegration(id);
      closeRightSidebar();
    },
    [disconnectIntegration, closeRightSidebar],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteCustomIntegration(id);
      closeRightSidebar();
    },
    [deleteCustomIntegration, closeRightSidebar],
  );

  const handlePublish = useCallback(
    (id: string) => publishIntegration(id),
    [publishIntegration],
  );

  const handleUnpublish = useCallback(
    (id: string) => unpublishIntegration(id),
    [unpublishIntegration],
  );

  const isSelectedSettling = selectedIntegration
    ? settlingIntegrationId === selectedIntegration.id
    : false;

  const sidebarElement = useMemo(() => {
    if (!selectedIntegration) return null;
    const isCustom = selectedIntegration.source === "custom";
    return (
      <IntegrationSidebar
        integration={selectedIntegration}
        onConnect={connectIntegration}
        onDisconnect={handleDisconnect}
        onDelete={isCustom ? handleDelete : undefined}
        onPublish={isCustom ? handlePublish : undefined}
        onUnpublish={isCustom ? handleUnpublish : undefined}
        category={selectedIntegration.name}
        isSettling={isSelectedSettling}
      />
    );
  }, [
    selectedIntegration,
    isSelectedSettling,
    connectIntegration,
    handleDisconnect,
    handleDelete,
    handlePublish,
    handleUnpublish,
  ]);

  useEffect(() => {
    if (!isSidebarOpen || !sidebarElement) return;
    setRightSidebarContent(sidebarElement);
  }, [isSidebarOpen, sidebarElement, setRightSidebarContent]);

  return { selectedIntegration, sidebarElement };
}

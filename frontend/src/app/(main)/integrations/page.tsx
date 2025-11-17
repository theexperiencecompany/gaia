"use client";

import { useCallback, useEffect, useState } from "react";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { ConnectIcon } from "@/components/shared/icons";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useHeader } from "@/hooks/layout/useHeader";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsPage() {
  const { integrations, connectIntegration } = useIntegrations();

  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const setRightSidebarVariant = useRightSidebar((state) => state.setVariant);
  const { setHeader } = useHeader();

  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);

  // Set header
  useEffect(() => {
    setHeader(
      <HeaderTitle
        icon={<ConnectIcon width={20} height={20} color={undefined} />}
        text="Integrations"
      />,
    );
    return () => setHeader(null);
  }, [setHeader]);

  // Set sidebar to sidebar mode (not sheet)
  useEffect(() => {
    setRightSidebarVariant("sidebar");
  }, [setRightSidebarVariant]);

  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      setSelectedIntegrationId(integrationId);
      const selectedIntegration = integrations.find(
        (i) => i.id === integrationId,
      );

      if (!selectedIntegration) return;

      setRightSidebarContent(
        <IntegrationSidebar
          integration={selectedIntegration}
          onConnect={connectIntegration}
          category={selectedIntegration.name}
        />,
      );
      openRightSidebar("sidebar");
    },
    [
      integrations,
      setRightSidebarContent,
      openRightSidebar,
      connectIntegration,
    ],
  );

  // Sync close action from right sidebar
  useEffect(() => {
    return useRightSidebar.subscribe((state, prevState) => {
      if (prevState.isOpen && !state.isOpen && selectedIntegrationId) {
        setSelectedIntegrationId(null);
      }
    });
  }, [selectedIntegrationId]);

  // Cleanup right sidebar on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  return (
    <div className="flex h-screen w-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="flex w-full justify-center px-5">
          <div className="w-full">
            <IntegrationsList onIntegrationClick={handleIntegrationClick} />
          </div>
        </div>
      </div>
    </div>
  );
}

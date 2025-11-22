"use client";

import { Button } from "@heroui/button";
import { useCallback, useEffect, useState } from "react";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { ConnectIcon, MessageFavourite02Icon } from "@/components/shared/icons";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsPage() {
  const { integrations, connectIntegration, disconnectIntegration } =
    useIntegrations();

  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const setRightSidebarVariant = useRightSidebar((state) => state.setVariant);
  const { setHeader } = useHeader();

  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);

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

      const handleDisconnect = async (id: string) => {
        await disconnectIntegration(id);
        // Close the sidebar after successful disconnect
        setTimeout(() => closeRightSidebar(), 500);
      };

      setRightSidebarContent(
        <IntegrationSidebar
          integration={selectedIntegration}
          onConnect={connectIntegration}
          onDisconnect={handleDisconnect}
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
      disconnectIntegration,
      closeRightSidebar,
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

  const handleRequestIntegration = () => {
    setIsSupportModalOpen(true);
  };

  return (
    <div className="flex h-screen w-full flex-col">
      <div className="absolute right-4 bottom-4">
        <Button
          color="primary"
          endContent={<MessageFavourite02Icon width={17} height={17} />}
          onPress={handleRequestIntegration}
        >
          Request an Integration
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="flex w-full justify-center px-5">
          <div className="w-full">
            <IntegrationsList onIntegrationClick={handleIntegrationClick} />
          </div>
        </div>
      </div>

      <ContactSupportModal
        isOpen={isSupportModalOpen}
        onOpenChange={() => setIsSupportModalOpen(!isSupportModalOpen)}
        initialValues={{
          type: "feature",
          title: "Integration Request",
          description:
            "I would like to request a new integration for:\n\n[Please describe the integration you need and how you plan to use it]",
        }}
      />
    </div>
  );
}

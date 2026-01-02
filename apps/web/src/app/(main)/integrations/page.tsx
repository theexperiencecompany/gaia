"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { toast } from "sonner";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { ConnectIcon, MessageFavourite02Icon } from "@/icons";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const {
    integrations,
    connectIntegration,
    disconnectIntegration,
    refreshStatus,
  } = useIntegrations();

  const searchParams = useSearchParams();
  const router = useRouter();
  const { isMac } = usePlatform();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const setRightSidebarVariant = useRightSidebar((state) => state.setVariant);
  const { setHeader } = useHeader();

  // Integrations store for search
  const searchQuery = useIntegrationsStore((state) => state.searchQuery);
  const setSearchQuery = useIntegrationsStore((state) => state.setSearchQuery);
  const clearSearch = useIntegrationsStore((state) => state.clearSearch);

  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);

  // Bearer token modal state
  const [bearerModalOpen, setBearerModalOpen] = useState(false);
  const [bearerIntegrationId, setBearerIntegrationId] = useState<string>("");
  const [bearerIntegrationName, setBearerIntegrationName] =
    useState<string>("");

  // Handle query params from backend redirects
  useEffect(() => {
    const status = searchParams.get("status");
    const integrationId = searchParams.get("id");

    if (status && integrationId) {
      // Clear query params
      router.replace("/integrations", { scroll: false });

      if (status === "connected") {
        const integration = integrations.find((i) => i.id === integrationId);
        toast.success(`Connected to ${integration?.name || integrationId}`);
        // Refresh both integration status AND tools cache to show new MCP tools
        refreshStatus();
        // Force refetch tools - don't just invalidate, actually refetch
        queryClient.refetchQueries({ queryKey: ["tools", "available"] });
      } else if (status === "bearer_required") {
        const integration = integrations.find((i) => i.id === integrationId);
        setBearerIntegrationId(integrationId);
        setBearerIntegrationName(integration?.name || integrationId);
        setBearerModalOpen(true);
      } else if (status === "failed") {
        const error = searchParams.get("error");
        toast.error(`Connection failed: ${error || "Unknown error"}`);
      }
    }
  }, [searchParams, integrations, router, refreshStatus, queryClient]);

  const handleBearerSubmit = async (id: string, token: string) => {
    await connectIntegration(id, token);
    toast.success(`Connected to ${bearerIntegrationName}`);
    refreshStatus();
  };

  // Keyboard shortcut to focus search input (Cmd+F on Mac, Ctrl+F on Windows)
  useHotkeys(
    "mod+f",
    (e) => {
      e.preventDefault();
      searchInputRef.current?.focus();
    },
    {
      enableOnFormTags: true,
    },
  );

  // Set header with search input
  useEffect(() => {
    setHeader(
      <div className="py-2 flex items-center justify-between w-full gap-4">
        <HeaderTitle
          icon={<ConnectIcon width={20} height={20} />}
          text="Integrations"
        />
        <IntegrationsSearchInput
          ref={searchInputRef}
          value={searchQuery}
          onChange={setSearchQuery}
          onClear={clearSearch}
          endContent={
            <div className="flex items-center gap-1.5">
              <Kbd keys={[isMac ? "command" : "ctrl"]}>F</Kbd>
            </div>
          }
        />
      </div>,
    );
    return () => setHeader(null);
  }, [searchQuery, setSearchQuery, clearSearch, setHeader, isMac]);

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

      <div className="flex-1 overflow-y-auto pb-20">
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

      <BearerTokenModal
        isOpen={bearerModalOpen}
        onClose={() => setBearerModalOpen(false)}
        integrationId={bearerIntegrationId}
        integrationName={bearerIntegrationName}
        onSubmit={handleBearerSubmit}
      />
    </div>
  );
}

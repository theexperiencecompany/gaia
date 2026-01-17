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
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
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
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
    refetch,
  } = useIntegrations();

  // Pre-fetch tools on page load
  const { tools: _prefetchedTools } = useToolsWithIntegrations();

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

  // Get filtered integrations for Enter key handler
  const { filteredIntegrations } = useIntegrationSearch(integrations);

  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);

  // Track if sidebar is open to know when to update content
  const isSidebarOpen = useRightSidebar((state) => state.isOpen);

  // Update sidebar content when selected integration status changes
  useEffect(() => {
    if (!selectedIntegrationId || !isSidebarOpen) return;

    const selectedIntegration = integrations.find(
      (i) => i.id === selectedIntegrationId,
    );

    if (!selectedIntegration) return;

    const handleDisconnect = async (id: string) => {
      await disconnectIntegration(id);
      setTimeout(() => closeRightSidebar(), 500);
    };

    const handleDelete = async (id: string) => {
      await deleteCustomIntegration(id);
      setTimeout(() => closeRightSidebar(), 500);
    };

    const handlePublish = async (id: string) => {
      await publishIntegration(id);
    };

    const handleUnpublish = async (id: string) => {
      await unpublishIntegration(id);
    };

    setRightSidebarContent(
      <IntegrationSidebar
        integration={selectedIntegration}
        onConnect={connectIntegration}
        onDisconnect={handleDisconnect}
        onDelete={
          selectedIntegration.source === "custom" ? handleDelete : undefined
        }
        onPublish={
          selectedIntegration.source === "custom" ? handlePublish : undefined
        }
        onUnpublish={
          selectedIntegration.source === "custom" ? handleUnpublish : undefined
        }
        category={selectedIntegration.name}
      />,
    );
  }, [
    selectedIntegrationId,
    integrations,
    isSidebarOpen,
    setRightSidebarContent,
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
    closeRightSidebar,
  ]);

  // Bearer token modal state
  const [bearerModalOpen, setBearerModalOpen] = useState(false);
  const [bearerIntegrationId, setBearerIntegrationId] = useState<string>("");
  const [bearerIntegrationName, setBearerIntegrationName] =
    useState<string>("");

  // Handle query params from backend redirects (status, oauth_success, etc.)
  useEffect(() => {
    const status = searchParams.get("status");
    const integrationId = searchParams.get("id");
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthIntegration = searchParams.get("integration");

    // Handle OAuth success callback
    if (oauthSuccess === "true") {
      router.replace("/integrations", { scroll: false });
      const integration = oauthIntegration
        ? integrations.find(
            (i) => i.id.toLowerCase() === oauthIntegration.toLowerCase(),
          )
        : null;
      const integrationName =
        integration?.name || oauthIntegration || "Integration";

      toast.success(`Connected to ${integrationName}`);
      refetch();
      queryClient.refetchQueries({ queryKey: ["tools", "available"] });
      return;
    }

    if (status && integrationId) {
      router.replace("/integrations", { scroll: false });

      if (status === "connected") {
        const integration = integrations.find((i) => i.id === integrationId);
        toast.success(`Connected to ${integration?.name || integrationId}`);
        refetch();
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
  }, [searchParams, integrations, router, refetch, queryClient]);

  const handleBearerSubmit = async (id: string, _token: string) => {
    // Note: Bearer token handling is done via the BearerTokenModal component directly
    await connectIntegration(id);
    toast.success(`Connected to ${bearerIntegrationName}`);
    refetch();
  };

  // Keyboard shortcut to focus search input
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

  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      setSelectedIntegrationId(integrationId);
      openRightSidebar("sidebar");
    },
    [openRightSidebar],
  );

  // Handle standalone id param (from slash command dropdown navigation)
  // Separated from the main useEffect to avoid using handleIntegrationClick before declaration
  useEffect(() => {
    const status = searchParams.get("status");
    const integrationId = searchParams.get("id");
    const oauthSuccess = searchParams.get("oauth_success");

    // Only process if we have an id and no status/oauth params (to avoid double-processing)
    if (integrationId && !status && !oauthSuccess) {
      // Clear the URL param first to prevent re-triggering
      router.replace("/integrations", { scroll: false });
      // Open the sidebar for this integration
      handleIntegrationClick(integrationId);
    }
  }, [searchParams, router, handleIntegrationClick]);

  // Handler for pressing Enter in search input
  const handleEnterSearch = useCallback(() => {
    if (filteredIntegrations.length > 0) {
      handleIntegrationClick(filteredIntegrations[0].id);
    }
  }, [filteredIntegrations, handleIntegrationClick]);

  // Set header with search input
  useEffect(() => {
    setHeader(
      <div className="py-1 flex items-center justify-between w-full gap-4">
        <HeaderTitle
          icon={<ConnectIcon width={20} height={20} />}
          text="Integrations"
        />
        <IntegrationsSearchInput
          ref={searchInputRef}
          value={searchQuery}
          onChange={setSearchQuery}
          onClear={clearSearch}
          onEnter={handleEnterSearch}
          endContent={
            <div className="flex items-center gap-1.5">
              <Kbd keys={[isMac ? "command" : "ctrl"]}>F</Kbd>
            </div>
          }
        />
      </div>,
    );
    return () => setHeader(null);
  }, [
    searchQuery,
    setSearchQuery,
    clearSearch,
    setHeader,
    isMac,
    handleEnterSearch,
  ]);

  // Set sidebar to sidebar mode
  useEffect(() => {
    setRightSidebarVariant("sidebar");
  }, [setRightSidebarVariant]);

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

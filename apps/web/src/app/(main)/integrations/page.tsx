"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { ConnectIcon, MessageFavourite02Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { toast } from "sonner";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { isMac } = usePlatform();
  const { setHeader } = useHeader();

  // Refs
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Integrations data and actions
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

  // Right sidebar store
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const setRightSidebarVariant = useRightSidebar((state) => state.setVariant);
  const isSidebarOpen = useRightSidebar((state) => state.isOpen);

  // Integrations store for search
  const searchQuery = useIntegrationsStore((state) => state.searchQuery);
  const setSearchQuery = useIntegrationsStore((state) => state.setSearchQuery);
  const clearSearch = useIntegrationsStore((state) => state.clearSearch);
  const { filteredIntegrations } = useIntegrationSearch(integrations);

  // Local state
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [pendingIntegrationId, setPendingIntegrationId] = useState<
    string | null
  >(null);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);
  const [bearerModalOpen, setBearerModalOpen] = useState(false);
  const [bearerIntegrationId, setBearerIntegrationId] = useState("");
  const [bearerIntegrationName, setBearerIntegrationName] = useState("");

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

    // For custom integrations, always pass the handlers
    // The sidebar component will determine when to show the buttons
    const isCustomIntegration = selectedIntegration.source === "custom";

    setRightSidebarContent(
      <IntegrationSidebar
        integration={selectedIntegration}
        onConnect={connectIntegration}
        onDisconnect={handleDisconnect}
        onDelete={isCustomIntegration ? handleDelete : undefined}
        onPublish={isCustomIntegration ? handlePublish : undefined}
        onUnpublish={isCustomIntegration ? handleUnpublish : undefined}
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

  // Handle query params from backend redirects (status, oauth_success, etc.)
  useEffect(() => {
    const status = searchParams.get("status");
    const integrationId = searchParams.get("id");
    const oauthSuccess = searchParams.get("oauth_success");
    const oauthIntegration = searchParams.get("integration");

    // Handle OAuth success callback - toast is handled globally by useOAuthSuccessToast
    // Here we just handle opening the sidebar for the connected integration
    if (oauthSuccess === "true") {
      // Set pending integration to open sidebar after data refresh
      // Use integrationId (from redirect_path) or oauthIntegration as fallback
      const targetIntegrationId = integrationId || oauthIntegration;
      if (targetIntegrationId) {
        setPendingIntegrationId(targetIntegrationId);
      }
      return;
    }

    if (status && integrationId) {
      router.replace("/integrations", { scroll: false });

      if (status === "connected") {
        const integration = integrations.find((i) => i.id === integrationId);
        const nameParam = searchParams.get("name");
        const displayName = integration?.name || nameParam || integrationId;
        toast.success(`Connected to ${displayName}`);
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

  const handleBearerSubmit = async (id: string, token: string) => {
    const toastId = toast.loading(`Connecting to ${bearerIntegrationName}...`);
    try {
      const result = await integrationsApi.addIntegration(id, token);
      if (result.status === "connected") {
        toast.success(`Connected to ${bearerIntegrationName}`, { id: toastId });
        refetch();
        queryClient.refetchQueries({ queryKey: ["tools", "available"] });
      } else if (result.status === "error") {
        toast.error(result.message || "Connection failed", { id: toastId });
      } else {
        toast.dismiss(toastId);
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Connection failed",
        { id: toastId },
      );
      throw error;
    }
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
    const needsRefresh = searchParams.get("refresh") === "true";

    // Only process if we have an id and no status/oauth params (to avoid double-processing)
    if (integrationId && !status && !oauthSuccess) {
      // Clear the URL param first to prevent re-triggering
      router.replace("/integrations", { scroll: false });

      // If refresh param is set (coming from marketplace add), invalidate cache and wait for fresh data
      if (needsRefresh) {
        // Set pending integration and trigger refetch
        setPendingIntegrationId(integrationId);
        queryClient.invalidateQueries({ queryKey: ["integrations"] });
        queryClient.invalidateQueries({ queryKey: ["tools", "available"] });
      } else {
        // Normal navigation - open sidebar immediately
        handleIntegrationClick(integrationId);
      }
    }
  }, [searchParams, router, handleIntegrationClick, queryClient]);

  // Open sidebar once pending integration data is available after refresh
  useEffect(() => {
    if (!pendingIntegrationId) return;

    const integration = integrations.find((i) => i.id === pendingIntegrationId);
    if (integration) {
      handleIntegrationClick(pendingIntegrationId);
      setPendingIntegrationId(null);
    }
  }, [pendingIntegrationId, integrations, handleIntegrationClick]);

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
      <div className="absolute right-4 bottom-4 z-1">
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

"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { ConnectIcon, MessageFavourite02Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import {
  POST_CONNECT_POLL_INTERVAL_MS,
  POST_CONNECT_POLL_MAX_ATTEMPTS,
} from "@/features/integrations/constants/connect";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { toast } from "@/lib/toast";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

// Query params appended by MCP connect redirects (oauth_* params are owned and
// cleared by the global useOAuthSuccessToast hook instead).
const CONNECTION_CALLBACK_PARAMS = [
  "status",
  "id",
  "name",
  "error",
  "refresh",
] as const;

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
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

  // Pre-fetch tools on page load; also used to detect when a just-connected
  // integration's tools have finished discovering in the background.
  const { tools: toolsWithIntegrations } = useToolsWithIntegrations();

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
  // Integration whose tools are still being discovered after a successful
  // connect — drives bounded polling and the sidebar's "Setting up tools" state.
  const [settlingIntegrationId, setSettlingIntegrationId] = useState<
    string | null
  >(null);
  // Incremented on each poll so the effect re-runs every interval even when the
  // refetched data is byte-identical (react-query structural sharing keeps the
  // same `integrations` reference until tools actually land).
  const [settleTick, setSettleTick] = useState(0);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);
  const [bearerModalOpen, setBearerModalOpen] = useState(false);
  const [bearerIntegrationId, setBearerIntegrationId] = useState("");
  const [bearerIntegrationName, setBearerIntegrationName] = useState("");

  // Strip MCP connect-callback params from the URL (locale-safe, preserves any
  // unrelated params). No-op when none are present so it's cheap to call often.
  const clearConnectionParams = useCallback(() => {
    const url = new URL(window.location.href);
    let changed = false;
    for (const param of CONNECTION_CALLBACK_PARAMS) {
      if (url.searchParams.has(param)) {
        url.searchParams.delete(param);
        changed = true;
      }
    }
    if (changed) {
      router.replace(url.pathname + url.search, { scroll: false });
    }
  }, [router]);

  // Update sidebar content when selected integration status changes
  useEffect(() => {
    if (!selectedIntegrationId || !isSidebarOpen) return;

    const selectedIntegration = integrations.find(
      (i) => i.id === selectedIntegrationId,
    );

    if (!selectedIntegration) return;

    const handleDisconnect = async (id: string) => {
      await disconnectIntegration(id);
      closeRightSidebar();
    };

    const handleDelete = async (id: string) => {
      await deleteCustomIntegration(id);
      closeRightSidebar();
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
        isSettling={settlingIntegrationId === selectedIntegration.id}
      />,
    );
  }, [
    selectedIntegrationId,
    integrations,
    isSidebarOpen,
    settlingIntegrationId,
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
    const params = new URLSearchParams(window.location.search);
    const status = params.get("status");
    const integrationId = params.get("id");
    const oauthSuccess = params.get("oauth_success");
    const oauthIntegration = params.get("integration");

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
      clearConnectionParams();

      if (status === "connected") {
        const nameParam = params.get("name");
        if (nameParam) {
          toast.success(`Connected to ${nameParam}`);
        }
        refetch();
        queryClient.refetchQueries({ queryKey: ["tools", "available"] });
        // Open the sidebar for the freshly-connected integration and poll until
        // its tools finish discovering in the background (see the poller below).
        setPendingIntegrationId(integrationId);
        setSettleTick(0);
        setSettlingIntegrationId(integrationId);
      } else if (status === "bearer_required") {
        // name should be in URL when redirected here
        const nameParam = params.get("name");
        if (nameParam) {
          setBearerIntegrationId(integrationId);
          setBearerIntegrationName(nameParam);
          setBearerModalOpen(true);
        }
      } else if (status === "failed") {
        const error = params.get("error");
        toast.error(`Connection failed: ${error || "Unknown error"}`);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleBearerSubmit = async (id: string, token: string) => {
    const toastId = toast.loading(`Connecting...`);
    try {
      const result = await integrationsApi.addIntegration(id, token);
      if (result.status === "connected") {
        toast.success(`Connected to ${result.name}`, { id: toastId });
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
    const params = new URLSearchParams(window.location.search);
    const status = params.get("status");
    const integrationId = params.get("id");
    const oauthSuccess = params.get("oauth_success");
    const needsRefresh = params.get("refresh") === "true";

    // Only process if we have an id and no status/oauth params (to avoid double-processing)
    if (integrationId && !status && !oauthSuccess) {
      // Clear the URL param first to prevent re-triggering
      clearConnectionParams();

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Open sidebar once pending integration data is available after refresh
  useEffect(() => {
    if (!pendingIntegrationId) return;

    const integration = integrations.find((i) => i.id === pendingIntegrationId);
    if (integration) {
      handleIntegrationClick(pendingIntegrationId);
      setPendingIntegrationId(null);
    }
  }, [pendingIntegrationId, integrations, handleIntegrationClick]);

  // The OAuth callback redirects as soon as tokens are stored; the MCP handshake
  // and tools/list run in the background, so a connected integration's tools land
  // a few seconds later. Poll until they appear (or give up) instead of forcing a
  // page reload. Re-runs whenever a refetch updates `integrations`/tools data.
  useEffect(() => {
    if (!settlingIntegrationId) return;

    const integration = integrations.find(
      (i) => i.id === settlingIntegrationId,
    );
    const hasEndpointTools = toolsWithIntegrations.some(
      (t) => t.category.toLowerCase() === settlingIntegrationId.toLowerCase(),
    );
    const hasTools = hasEndpointTools || (integration?.tools?.length ?? 0) > 0;

    // Stop once the tools land, or after the attempt ceiling (covers a failed
    // background connect). Note: keep polling even while the integration isn't
    // in the list yet — the post-connect refetch may still be in flight.
    if (hasTools || settleTick >= POST_CONNECT_POLL_MAX_ATTEMPTS) {
      setSettlingIntegrationId(null);
      return;
    }

    const timer = setTimeout(() => {
      refetch();
      queryClient.refetchQueries({ queryKey: ["tools", "available"] });
      setSettleTick((tick) => tick + 1);
    }, POST_CONNECT_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [
    settlingIntegrationId,
    settleTick,
    integrations,
    toolsWithIntegrations,
    refetch,
    queryClient,
  ]);

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
        // Clear any lingering connect-callback params so reopening the page
        // later doesn't re-trigger the success toast from a stale URL.
        clearConnectionParams();
      }
    });
  }, [selectedIntegrationId, clearConnectionParams]);

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
        onOpenChange={() => setIsSupportModalOpen((prev) => !prev)}
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

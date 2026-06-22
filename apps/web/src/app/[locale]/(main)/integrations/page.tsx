"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { ConnectIcon, MessageFavourite02Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import {
  POST_CONNECT_POLL_INTERVAL_MS,
  POST_CONNECT_POLL_MAX_ATTEMPTS,
} from "@/features/integrations/constants/connect";
import { useBearerTokenModal } from "@/features/integrations/hooks/useBearerTokenModal";
import { useIntegrationDeepLink } from "@/features/integrations/hooks/useIntegrationDeepLink";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { toast } from "@/lib/toast";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
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

  // Bearer-token connect modal (MCP `status=bearer_required` flow).
  const bearer = useBearerTokenModal({
    connect: (id, token) => integrationsApi.addIntegration(id, token),
    onConnected: (_id, result) => {
      toast.success(`Connected to ${result.name}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
    },
  });

  const selectedIntegration = useMemo(
    () => integrations.find((i) => i.id === selectedIntegrationId) ?? null,
    [integrations, selectedIntegrationId],
  );

  // Stable handlers — they only depend on the (memoized) hook actions, so the
  // sidebar content isn't rebuilt just because they were recreated.
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

  // Build the sidebar element once per relevant change. React Query's structural
  // sharing keeps `selectedIntegration`'s identity stable across no-op refetches
  // (e.g. the post-connect poll), so this only rebuilds when the selected
  // integration's data or its settling state actually changes — not on every
  // poll tick.
  const sidebarElement = useMemo(() => {
    if (!selectedIntegration) return null;
    const isCustomIntegration = selectedIntegration.source === "custom";
    return (
      <IntegrationSidebar
        integration={selectedIntegration}
        onConnect={connectIntegration}
        onDisconnect={handleDisconnect}
        onDelete={isCustomIntegration ? handleDelete : undefined}
        onPublish={isCustomIntegration ? handlePublish : undefined}
        onUnpublish={isCustomIntegration ? handleUnpublish : undefined}
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

  // Push the memoized element into the right sidebar while it's open.
  useEffect(() => {
    if (!isSidebarOpen || !sidebarElement) return;
    setRightSidebarContent(sidebarElement);
  }, [isSidebarOpen, sidebarElement, setRightSidebarContent]);

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

  // All backend connect-callback query params flow through one reactive hook.
  useIntegrationDeepLink({
    onConnected: (integrationId, name) => {
      if (name) toast.success(`Connected to ${name}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
      // Open the sidebar for the freshly-connected integration and poll until
      // its tools finish discovering in the background (see the poller below).
      setPendingIntegrationId(integrationId);
      setSettleTick(0);
      setSettlingIntegrationId(integrationId);
    },
    onBearerRequired: (integrationId, name) => bearer.open(integrationId, name),
    onFailed: (error) =>
      toast.error(`Connection failed: ${error || "Unknown error"}`),
    onOpen: (integrationId, { refresh }) => {
      if (refresh) {
        // Marketplace add / custom create — may not be in the cached list yet.
        setPendingIntegrationId(integrationId);
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
      } else {
        handleIntegrationClick(integrationId);
      }
    },
  });

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
  // a few seconds later. Poll the personalized /integrations/me catalog until the
  // integration reports connected with discovered tools (or give up) instead of
  // forcing a page reload. Re-runs whenever a refetch updates `integrations`.
  useEffect(() => {
    if (!settlingIntegrationId) return;

    const integration = integrations.find(
      (i) => i.id === settlingIntegrationId,
    );
    const hasSettled =
      integration?.status === "connected" && (integration?.toolCount ?? 0) > 0;

    // Stop once the integration connects with tools, or after the attempt
    // ceiling (covers a failed background connect). Keep polling while the
    // integration isn't in the list yet — the post-connect refetch may still
    // be in flight.
    if (hasSettled || settleTick >= POST_CONNECT_POLL_MAX_ATTEMPTS) {
      setSettlingIntegrationId(null);
      return;
    }

    const timer = setTimeout(() => {
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
      setSettleTick((tick) => tick + 1);
    }, POST_CONNECT_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [settlingIntegrationId, settleTick, integrations, refetch, queryClient]);

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
        onOpenChange={() => setIsSupportModalOpen((prev) => !prev)}
        initialValues={{
          type: "feature",
          title: "Integration Request",
          description:
            "I would like to request a new integration for:\n\n[Please describe the integration you need and how you plan to use it]",
        }}
      />

      <BearerTokenModal
        isOpen={bearer.isOpen}
        onClose={bearer.close}
        integrationId={bearer.integrationId}
        integrationName={bearer.integrationName}
        onSubmit={bearer.submit}
      />
    </div>
  );
}

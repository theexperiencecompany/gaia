"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { ConnectIcon, MessageFavourite02Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import { IntegrationSidebar } from "@/components/layout/sidebar/right-variants/IntegrationSidebar";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";
import { IntegrationsSearchInput } from "@/features/integrations/components/IntegrationsSearchInput";
import { ALL_CATEGORIES } from "@/features/integrations/constants/categories";
import {
  POST_CONNECT_POLL_INTERVAL_MS,
  POST_CONNECT_POLL_MAX_ATTEMPTS,
} from "@/features/integrations/constants/connect";
import { useBearerTokenModal } from "@/features/integrations/hooks/useBearerTokenModal";
import { useIntegrationDeepLink } from "@/features/integrations/hooks/useIntegrationDeepLink";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
import { useIntegrationStatusWebSocket } from "@/features/integrations/hooks/useIntegrationStatusWebSocket";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { usePendingDeepLink } from "@/features/integrations/hooks/usePendingDeepLink";
import type { Integration } from "@/features/integrations/types";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { useHeader } from "@/hooks/layout/useHeader";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { toast } from "@/lib/toast";

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

  // An integration can die while this page is open (Composio revokes the grant,
  // or a tool call hits a dead account) — flip it to Reconnect without a refresh.
  useIntegrationStatusWebSocket();

  // Search + category filter — page-owned, so they reset when you leave.
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState(ALL_CATEGORIES);
  const clearSearch = useCallback(() => setSearchQuery(""), []);
  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setSelectedCategory(ALL_CATEGORIES);
  }, []);
  const { filteredIntegrations } = useIntegrationSearch(
    integrations,
    searchQuery,
    selectedCategory,
  );

  // Local state
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const clearSelection = useCallback(() => setSelectedIntegrationId(null), []);
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

  // Stable handlers — clearing the selection unmounts the panel, which closes
  // the sidebar.
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
  const handlePublish = useCallback(
    (id: string) => publishIntegration(id),
    [publishIntegration],
  );
  const handleUnpublish = useCallback(
    (id: string) => unpublishIntegration(id),
    [unpublishIntegration],
  );

  const handleIntegrationClick = useCallback((integrationId: string) => {
    setSelectedIntegrationId(integrationId);
  }, []);

  const { markPending } = usePendingDeepLink(
    integrations,
    handleIntegrationClick,
  );
  // Poll until a freshly-connected integration's tools finish discovering.
  const { beginSettling, settlingIntegrationId } = usePostConnectSettlePolling(
    integrations,
    refetch,
  );

  const isSelectedSettling = selectedIntegration
    ? settlingIntegrationId === selectedIntegration.id
    : false;

  const isCustomIntegration = selectedIntegration?.source === "custom";

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

  // All backend connect-callback query params flow through one reactive hook.
  useIntegrationDeepLink({
    onConnected: (integrationId, name) => {
      if (name) toast.success(`Connected to ${name}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
      // Open the sidebar for the freshly-connected integration and poll until
      // its tools finish discovering in the background (see the poller below).
      markPending(integrationId);
      beginSettling(integrationId);
    },
    onBearerRequired: (integrationId, name) => bearer.open(integrationId, name),
    onFailed: (error) =>
      toast.error(`Connection failed: ${error || "Unknown error"}`),
    onOpen: (integrationId, { refresh }) => {
      if (refresh) {
        // Marketplace add / custom create — may not be in the cached list yet.
        markPending(integrationId);
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
      } else {
        handleIntegrationClick(integrationId);
      }
    },
    onConnectRequested: (integrationId) => {
      void connectIntegration(integrationId);
    },
  });

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

  const handleRequestIntegration = () => {
    setIsSupportModalOpen(true);
  };

  return (
    <div className="flex h-screen w-full flex-col">
      {selectedIntegration && (
        <RightSidebarPanel mode="sidebar" onClose={clearSelection}>
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
        </RightSidebarPanel>
      )}
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
            <IntegrationsList
              onIntegrationClick={handleIntegrationClick}
              searchQuery={searchQuery}
              selectedCategory={selectedCategory}
              setSelectedCategory={setSelectedCategory}
              clearFilters={clearFilters}
            />
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

/**
 * The OAuth callback redirects as soon as tokens are stored; the MCP handshake
 * and tools/list run in the background, so a connected integration's tools land
 * a few seconds later. Poll the personalized /integrations/me catalog until the
 * integration reports connected with discovered tools (or give up) instead of
 * forcing a page reload. Re-runs whenever a refetch updates `integrations`.
 */
function usePostConnectSettlePolling(
  integrations: Integration[],
  refetch: () => Promise<void>,
) {
  const queryClient = useQueryClient();
  // Integration whose tools are still being discovered after a successful
  // connect — drives bounded polling and the sidebar's "Setting up tools" state.
  const [settlingIntegrationId, setSettlingIntegrationId] = useState<
    string | null
  >(null);
  // Incremented on each poll so the effect re-runs every interval even when the
  // refetched data is byte-identical (react-query structural sharing keeps the
  // same `integrations` reference until tools actually land).
  const [settleTick, setSettleTick] = useState(0);

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

  const beginSettling = useCallback((integrationId: string) => {
    setSettlingIntegrationId(integrationId);
    setSettleTick(0);
  }, []);

  return { beginSettling, settlingIntegrationId };
}

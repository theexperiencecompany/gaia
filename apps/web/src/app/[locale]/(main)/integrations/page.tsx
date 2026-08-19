"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
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
import { IntegrationsHeader } from "./components/IntegrationsHeader";
import { IntegrationsPageBody } from "./components/IntegrationsPageBody";
import { useIntegrationSidebar } from "./hooks/useIntegrationSidebar";
import { useSettlingPoller } from "./hooks/useSettlingPoller";

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const { isMac } = usePlatform();
  const { setHeader } = useHeader();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const {
    integrations,
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
    refetch,
  } = useIntegrations();

  const setRightSidebarVariant = useRightSidebar((s) => s.setVariant);
  const closeRightSidebar = useRightSidebar((s) => s.close);
  const openRightSidebar = useRightSidebar((s) => s.open);

  const searchQuery = useIntegrationsStore((s) => s.searchQuery);
  const setSearchQuery = useIntegrationsStore((s) => s.setSearchQuery);
  const clearSearch = useIntegrationsStore((s) => s.clearSearch);
  const { filteredIntegrations } = useIntegrationSearch(integrations);

  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [pendingIntegrationId, setPendingIntegrationId] = useState<
    string | null
  >(null);
  const [settlingIntegrationId, setSettlingIntegrationId] = useState<
    string | null
  >(null);
  const [settleTick, setSettleTick] = useState(0);
  const [isSupportModalOpen, setIsSupportModalOpen] = useState(false);

  const bearer = useBearerTokenModal({
    connect: (id, token) => integrationsApi.addIntegration(id, token),
    onConnected: (_id, result) => {
      toast.success(`Connected to ${result.name}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
    },
  });

  useIntegrationSidebar({
    integrations,
    selectedIntegrationId,
    settlingIntegrationId,
    connectIntegration,
    disconnectIntegration,
    deleteCustomIntegration,
    publishIntegration,
    unpublishIntegration,
  });

  useHotkeys(
    "mod+f",
    (e) => {
      e.preventDefault();
      searchInputRef.current?.focus();
    },
    { enableOnFormTags: true },
  );

  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      setSelectedIntegrationId(integrationId);
      openRightSidebar("sidebar");
    },
    [openRightSidebar],
  );

  useIntegrationDeepLink({
    onConnected: (integrationId, name) => {
      if (name) toast.success(`Connected to ${name}`);
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
      setPendingIntegrationId(integrationId);
      setSettleTick(0);
      setSettlingIntegrationId(integrationId);
    },
    onBearerRequired: (integrationId, name) => bearer.open(integrationId, name),
    onFailed: (error) =>
      toast.error(`Connection failed: ${error || "Unknown error"}`),
    onOpen: (integrationId, { refresh }) => {
      if (refresh) {
        setPendingIntegrationId(integrationId);
        queryClient.invalidateQueries({ queryKey: integrationKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
      } else {
        handleIntegrationClick(integrationId);
      }
    },
  });

  useEffect(() => {
    if (!pendingIntegrationId) return;
    const integration = integrations.find((i) => i.id === pendingIntegrationId);
    if (integration) {
      handleIntegrationClick(pendingIntegrationId);
      setPendingIntegrationId(null);
    }
  }, [pendingIntegrationId, integrations, handleIntegrationClick]);

  useSettlingPoller({
    settlingIntegrationId,
    settleTick,
    integrations,
    refetch,
    queryClient,
    onSettleDone: () => setSettlingIntegrationId(null),
    onTick: () => setSettleTick((t) => t + 1),
  });

  const handleEnterSearch = useCallback(() => {
    if (filteredIntegrations.length > 0) {
      handleIntegrationClick(filteredIntegrations[0].id);
    }
  }, [filteredIntegrations, handleIntegrationClick]);

  useEffect(() => {
    setHeader(
      <IntegrationsHeader
        searchQuery={searchQuery}
        isMac={isMac}
        inputRef={searchInputRef}
        onChange={setSearchQuery}
        onClear={clearSearch}
        onEnter={handleEnterSearch}
      />,
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

  useEffect(() => {
    setRightSidebarVariant("sidebar");
  }, [setRightSidebarVariant]);

  useEffect(() => {
    return useRightSidebar.subscribe((state, prevState) => {
      if (prevState.isOpen && !state.isOpen && selectedIntegrationId) {
        setSelectedIntegrationId(null);
      }
    });
  }, [selectedIntegrationId]);

  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  return (
    <div className="flex h-screen w-full flex-col">
      <IntegrationsPageBody
        onIntegrationClick={handleIntegrationClick}
        onRequestIntegration={() => setIsSupportModalOpen(true)}
      />

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

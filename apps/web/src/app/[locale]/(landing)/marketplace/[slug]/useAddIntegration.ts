import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { integrationKeys } from "@/features/integrations/api/queryKeys";
import { useBearerTokenModal } from "@/features/integrations/hooks/useBearerTokenModal";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { toast } from "@/lib/toast";

export function useAddIntegration(integration: PublicIntegrationResponse) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isAdding, setIsAdding] = useState(false);
  const [isAdded, setIsAdded] = useState(false);
  const { isAuthenticated, openLoginModal } = useAuth();
  const { integrations: myIntegrations } = useIntegrations();

  const isNative = integration.source === "platform";

  const goToIntegration = () => {
    setTimeout(() => {
      router.push(`/integrations?id=${integration.integrationId}&refresh=true`);
    }, 1000);
  };

  const bearer = useBearerTokenModal({
    connect: (id, token) => integrationsApi.addIntegration(id, token),
    onConnected: () => {
      toast.success(`Successfully added ${integration.name}!`);
      setIsAdded(true);
      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      goToIntegration();
    },
  });

  // The personalized catalog lists every integration; the user "has" one once
  // its status is anything other than not_connected.
  const alreadyHasIntegration = useMemo(() => {
    return myIntegrations.some(
      (item) =>
        item.id === integration.integrationId &&
        item.status !== "not_connected",
    );
  }, [myIntegrations, integration.integrationId]);

  const handleAdd = async () => {
    if (isAdded) return;

    if (!isAuthenticated) {
      openLoginModal();
      return;
    }

    if (alreadyHasIntegration) {
      toast.info("You already have this integration in your GAIA");
      return;
    }

    setIsAdding(true);
    const loadingToast = toast.loading("Adding integration...");

    try {
      // Native integrations use /connect; community ones use /public/{id}/add.
      const result = isNative
        ? await integrationsApi.connectIntegration(integration.integrationId)
        : await integrationsApi.addIntegration(integration.integrationId);

      if (result.status === "redirecting") {
        toast.loading("Redirecting to authorize...", { id: loadingToast });
        return;
      }

      if (result.status === "bearer_required") {
        toast.dismiss(loadingToast);
        bearer.open(integration.integrationId, integration.name);
        setIsAdding(false);
        return;
      }

      toast.dismiss(loadingToast);
      toast.success(`Successfully added ${result.name}!`);
      setIsAdded(true);
      goToIntegration();
    } catch {
      toast.dismiss(loadingToast);
      toast.error("Failed to add integration.");
      setIsAdding(false);
    }
  };

  const viewIntegration = () =>
    router.push(`/integrations?id=${integration.integrationId}`);

  return {
    bearer,
    isNative,
    isAdding,
    isAdded,
    alreadyHasIntegration,
    handleAdd,
    viewIntegration,
  };
}

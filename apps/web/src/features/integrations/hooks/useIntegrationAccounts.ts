import type {
  IntegrationAccountsResponse,
  UpdateIntegrationAccountRequest,
} from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/lib/toast";

import { integrationsApi } from "../api/integrationsApi";
import { integrationKeys, toolKeys } from "../api/queryKeys";

interface AccountUpdate {
  accountId: string;
  body: UpdateIntegrationAccountRequest;
}

/**
 * The accounts a user connected to one integration, and the actions on them.
 *
 * Every change can move the primary or end the integration, so it refreshes the
 * whole integrations cache (status, catalog, tools) along with the list.
 */
export const useIntegrationAccounts = (integrationId: string) => {
  const queryClient = useQueryClient();
  const queryKey = integrationKeys.accounts(integrationId);

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () => integrationsApi.getIntegrationAccounts(integrationId),
    staleTime: 0,
  });

  const applyResult = (result: IntegrationAccountsResponse) => {
    queryClient.setQueryData(queryKey, result);
    queryClient.invalidateQueries({ queryKey: integrationKeys.all });
    queryClient.invalidateQueries({ queryKey: toolKeys.all });
  };

  const update = useMutation({
    mutationFn: ({ accountId, body }: AccountUpdate) =>
      integrationsApi.updateIntegrationAccount(integrationId, accountId, body),
    onSuccess: applyResult,
  });

  const remove = useMutation({
    mutationFn: (accountId: string) =>
      integrationsApi.removeIntegrationAccount(integrationId, accountId),
    onSuccess: (result) => {
      applyResult(result);
      toast.success("Account disconnected");
    },
  });

  return {
    accounts: data?.accounts ?? [],
    maxAccounts: data?.maxAccounts ?? 0,
    isLoading,
    pendingAccountId:
      (update.isPending && update.variables?.accountId) ||
      (remove.isPending && remove.variables) ||
      null,
    makePrimary: (accountId: string) =>
      update.mutateAsync({ accountId, body: { isPrimary: true } }),
    rename: (accountId: string, nickname: string) =>
      update.mutateAsync({ accountId, body: { nickname } }),
    remove: (accountId: string) => remove.mutateAsync(accountId),
  };
};

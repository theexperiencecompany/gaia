import { useIntegrationAccounts } from "./useIntegrationAccounts";

/** The name of the account an integration acts as: its primary account, else its first. */
export function usePrimaryAccountName(integrationId: string) {
  const { accounts, isLoading } = useIntegrationAccounts(integrationId);
  const account = accounts.find((a) => a.isPrimary) ?? accounts[0];
  return { name: account?.displayName ?? null, isLoading };
}

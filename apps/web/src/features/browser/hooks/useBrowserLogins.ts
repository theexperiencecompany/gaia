import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "../api/browserApi";
import type { SavedBrowserLogin } from "../types";

const browserLoginsKey = ["browser-logins"] as const;

export function useBrowserLogins() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: browserLoginsKey,
    queryFn: () => browserApi.listLogins(),
  });

  const forget = useMutation({
    mutationFn: (domain: string) => browserApi.forgetLogin(domain),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: browserLoginsKey }),
  });

  const clearAll = useMutation({
    mutationFn: () => browserApi.clearLogins(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: browserLoginsKey }),
  });

  return {
    logins: (query.data ?? []) as SavedBrowserLogin[],
    isLoading: query.isLoading,
    error: query.error as Error | null,
    refetch: query.refetch,
    // mutate (not mutateAsync) so a failed forget is handled by React Query and
    // doesn't surface as an unhandled promise rejection at the call site.
    forgetLogin: forget.mutate,
    // The specific domain being forgotten, so only its row shows a loading state.
    forgettingDomain: forget.isPending ? forget.variables : null,
    // mutateAsync here since the caller awaits it after a double confirmation.
    clearAllLogins: clearAll.mutateAsync,
    isClearingAll: clearAll.isPending,
  };
}

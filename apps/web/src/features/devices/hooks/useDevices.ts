import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { devicesApi } from "../api/devicesApi";
import type { Device } from "../types";

const devicesKey = ["devices"] as const;

export function useDevices() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: devicesKey,
    queryFn: async () => (await devicesApi.list()).devices,
    // Presence flips when a daemon connects/disconnects; keep it reasonably fresh.
    refetchInterval: 15_000,
  });

  const revoke = useMutation({
    mutationFn: (deviceId: string) => devicesApi.revoke(deviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: devicesKey }),
  });

  return {
    devices: (query.data ?? []) as Device[],
    isLoading: query.isLoading,
    error: query.error as Error | null,
    refetch: query.refetch,
    // mutate (not mutateAsync) so a failed revoke is handled by React Query and
    // doesn't surface as an unhandled promise rejection at the call site.
    revokeDevice: revoke.mutate,
    // The specific device being revoked, so only its row shows a loading state.
    revokingId: revoke.isPending ? revoke.variables : null,
  };
}

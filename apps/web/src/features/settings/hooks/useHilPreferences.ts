import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approvalsApi,
  type HilPreferences,
} from "@/features/settings/api/approvalsApi";

const HIL_PREFS_KEY = ["hil", "preferences"] as const;

/**
 * Shared HIL preferences: the global enable toggle plus per-tool overrides.
 * Backed by one react-query cache so the settings page and the integration
 * tool list stay in sync.
 */
export function useHilPreferences() {
  const qc = useQueryClient();

  const { data: prefs, isLoading } = useQuery({
    queryKey: HIL_PREFS_KEY,
    queryFn: approvalsApi.getHilPreferences,
  });

  const enabledMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      approvalsApi.putHilPreferences({ enabled }),
    onSuccess: (data) => qc.setQueryData(HIL_PREFS_KEY, data),
  });

  const overrideMutation = useMutation({
    mutationFn: ({ name, ask }: { name: string; ask: boolean | null }) =>
      approvalsApi.setToolOverride(name, ask),
    onSuccess: (data) => qc.setQueryData(HIL_PREFS_KEY, data),
  });

  return {
    prefs,
    isLoading,
    isSavingEnabled: enabledMutation.isPending,
    setEnabled: (enabled: boolean) => enabledMutation.mutateAsync(enabled),
    /** Set a tool's approval, storing only diffs from its default. */
    setToolApproval: (name: string, ask: boolean, destructive: boolean) =>
      overrideMutation.mutate({ name, ask: ask === destructive ? null : ask }),
    /** Drop a tool's override so it reverts to its default. */
    resetTool: (name: string) => overrideMutation.mutate({ name, ask: null }),
  };
}

/** Effective "ask before running" state for a tool. */
export function toolAsks(
  prefs: HilPreferences | undefined,
  name: string,
  destructive: boolean,
): boolean {
  return prefs?.tool_overrides?.[name] ?? destructive;
}

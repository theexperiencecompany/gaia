import {
  DEFAULT_HIL_MODE,
  type HilMode,
  toolOverrideValue,
} from "@shared/chat";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approvalsApi } from "@/features/settings/api/approvalsApi";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

const HIL_PREFS_KEY = ["hil", "preferences"] as const;

/**
 * Shared HIL preferences: the global approval mode plus per-tool overrides.
 * Backed by one react-query cache so the settings page and the integration
 * tool list stay in sync.
 */
export function useHilPreferences() {
  const qc = useQueryClient();

  const { data: prefs, isLoading } = useQuery({
    queryKey: HIL_PREFS_KEY,
    queryFn: approvalsApi.getHilPreferences,
  });

  const modeMutation = useMutation({
    mutationFn: (mode: HilMode) => approvalsApi.putHilPreferences({ mode }),
    onSuccess: (data, mode) => {
      trackEvent(ANALYTICS_EVENTS.SETTINGS_PREFERENCES_CHANGED, {
        setting: "hil_approvals",
        mode,
      });
      qc.setQueryData(HIL_PREFS_KEY, data);
    },
  });

  const overrideMutation = useMutation({
    mutationFn: ({ name, ask }: { name: string; ask: boolean | null }) =>
      approvalsApi.setToolOverride(name, ask),
    onSuccess: (data, { name, ask }) => {
      trackEvent(ANALYTICS_EVENTS.SETTINGS_PREFERENCES_CHANGED, {
        setting: "tool_approval",
        tool_name: name,
        require_approval: ask === true,
      });
      qc.setQueryData(HIL_PREFS_KEY, data);
    },
    // The mutation is fire-and-forget from every call site (`.mutate()`), so
    // this is the single place a failed per-tool save can surface to the user.
    onError: () => toast.error("Failed to update tool approval"),
  });

  return {
    prefs,
    isLoading,
    mode: prefs?.mode ?? DEFAULT_HIL_MODE,
    isSavingMode: modeMutation.isPending,
    setMode: (mode: HilMode) => modeMutation.mutateAsync(mode),
    /** Set whether a tool needs approval, storing only diffs from its default. */
    setToolApproval: (name: string, ask: boolean, destructive: boolean) =>
      overrideMutation.mutate({
        name,
        ask: toolOverrideValue(ask, destructive),
      }),
  };
}

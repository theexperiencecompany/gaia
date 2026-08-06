import type { HilMode, HilPreferences } from "@gaia/shared/chat";
import { DEFAULT_HIL_MODE, toolOverrideValue } from "@gaia/shared/chat";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert } from "react-native";
import { settingsApi } from "@/features/settings/api/settings-api";

const HIL_PREFS_KEY = ["hil", "preferences"] as const;
const EMPTY: HilPreferences = { mode: DEFAULT_HIL_MODE, tool_overrides: {} };

/**
 * Shared HIL preferences: the global approval mode plus per-tool overrides.
 * One react-query cache (mirroring the web hook) so the preferences screen
 * and every integration tool list stay in sync; writes are optimistic with
 * rollback so controls respond instantly.
 */
export function useHilPreferences() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: HIL_PREFS_KEY,
    queryFn: settingsApi.getHilPreferences,
  });

  const modeMutation = useMutation({
    mutationFn: (mode: HilMode) => settingsApi.updateHilPreferences({ mode }),
    onMutate: async (mode) => {
      const previous = qc.getQueryData<HilPreferences>(HIL_PREFS_KEY);
      qc.setQueryData<HilPreferences>(HIL_PREFS_KEY, (p = EMPTY) => ({
        ...p,
        mode,
      }));
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) qc.setQueryData(HIL_PREFS_KEY, context.previous);
    },
    onSuccess: (prefs) => qc.setQueryData(HIL_PREFS_KEY, prefs),
  });

  const overrideMutation = useMutation({
    mutationFn: ({ name, ask }: { name: string; ask: boolean | null }) =>
      settingsApi.setToolOverride(name, ask),
    onMutate: async ({ name, ask }) => {
      const previous = qc.getQueryData<HilPreferences>(HIL_PREFS_KEY);
      qc.setQueryData<HilPreferences>(HIL_PREFS_KEY, (p = EMPTY) => {
        const overrides = { ...p.tool_overrides };
        if (ask === null) delete overrides[name];
        else overrides[name] = ask;
        return { ...p, tool_overrides: overrides };
      });
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) qc.setQueryData(HIL_PREFS_KEY, context.previous);
    },
    onSuccess: (prefs) => qc.setQueryData(HIL_PREFS_KEY, prefs),
  });

  const prefs = data ?? EMPTY;

  return {
    prefs,
    isLoading,
    /** Resolves to whether the save stuck — callers gate follow-up UI on it. */
    setMode: async (mode: HilMode): Promise<boolean> => {
      try {
        await modeMutation.mutateAsync(mode);
        return true;
      } catch {
        return false;
      }
    },
    /** Set whether a tool needs approval, storing only diffs from its default. */
    setToolApproval: async (
      name: string,
      ask: boolean,
      destructive: boolean,
    ) => {
      try {
        await overrideMutation.mutateAsync({
          name,
          ask: toolOverrideValue(ask, destructive),
        });
      } catch {
        // Optimistic update already rolled back — but the switch snapping back
        // with no explanation reads as a glitch. Say what happened.
        Alert.alert(
          "Couldn't save",
          "Your tool approval change didn't save — try again.",
        );
      }
    },
  };
}

import {
  DEFAULT_HIL_MODE,
  type HilMode,
  toolOverrideValue,
} from "@shared/chat";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approvalsApi } from "@/features/settings/api/approvalsApi";
import { toast } from "@/lib/toast";

const HIL_PREFS_KEY = ["hil", "preferences"] as const;

/** One tool's desired approval setting, alongside the default it deviates from. */
export interface ToolApprovalUpdate {
  name: string;
  ask: boolean;
  destructive: boolean;
}

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
    onSuccess: (data) => {
      qc.setQueryData(HIL_PREFS_KEY, data);
    },
  });

  const overrideMutation = useMutation({
    mutationFn: ({ name, ask }: { name: string; ask: boolean | null }) =>
      approvalsApi.setToolOverride(name, ask),
    onSuccess: (data) => {
      qc.setQueryData(HIL_PREFS_KEY, data);
    },
    // The mutation is fire-and-forget from every call site (`.mutate()`), so
    // this is the single place a failed per-tool save can surface to the user.
    onError: () => toast.error("Failed to update tool approval"),
  });

  // The per-tool endpoint takes one tool at a time and answers with the whole
  // preferences document, so the writes are serialised: fired in parallel, the
  // last response to land would overwrite the cache with a snapshot taken
  // before its siblings were applied.
  const bulkMutation = useMutation({
    mutationFn: async ([first, ...rest]: ToolApprovalUpdate[]) => {
      const save = (update: ToolApprovalUpdate) =>
        approvalsApi.setToolOverride(
          update.name,
          toolOverrideValue(update.ask, update.destructive),
        );
      let latest = await save(first);
      for (const update of rest) latest = await save(update);
      return latest;
    },
    onSuccess: (data) => qc.setQueryData(HIL_PREFS_KEY, data),
    onError: () => toast.error("Failed to update tool approvals"),
  });

  return {
    prefs,
    isLoading,
    mode: prefs?.mode ?? DEFAULT_HIL_MODE,
    isSavingMode: modeMutation.isPending,
    isSavingTools: bulkMutation.isPending,
    setMode: (mode: HilMode) => modeMutation.mutateAsync(mode),
    /** Apply several tools' approval settings in one go; ignores an empty list. */
    setToolApprovals: (updates: ToolApprovalUpdate[]) => {
      if (updates.length > 0) bulkMutation.mutate(updates);
    },
    /** Set whether a tool needs approval, storing only diffs from its default. */
    setToolApproval: (name: string, ask: boolean, destructive: boolean) =>
      overrideMutation.mutate({
        name,
        ask: toolOverrideValue(ask, destructive),
      }),
  };
}

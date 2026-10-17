import type { QuietHours } from "@gaia/shared/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert } from "react-native";
import { inAppNotificationsApi } from "../api/inapp-notifications-api";
import { resolveQuietHoursCommit } from "../utils/quiet-hours";

const QUIET_HOURS_QUERY_KEY = ["notification-quiet-hours"] as const;

export type QuietHoursEdge = keyof QuietHours;

interface OptimisticQuietHoursContext {
  previous: QuietHours | undefined;
}

export interface QuietHoursEditor {
  /** The window to display: the unsaved draft while editing, else the stored one. */
  quietHours: QuietHours | undefined;
  loadFailed: boolean;
  retry: () => void;
  isSaving: boolean;
  editingEdge: QuietHoursEdge | null;
  edit: (edge: QuietHoursEdge) => void;
  pickHour: (hour: number) => void;
  /** Saves the draft; an invalid draft stays open for correction. */
  done: () => void;
  /** Saves the draft as the sheet closes; an invalid draft is discarded. */
  dismiss: () => void;
}

/**
 * The user's quiet hours as an edit session: picking hours only changes a
 * local draft, and the draft is saved once, on Done or when the sheet closes.
 */
export function useQuietHoursEditor(enabled: boolean): QuietHoursEditor {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<QuietHours | null>(null);
  const [editingEdge, setEditingEdge] = useState<QuietHoursEdge | null>(null);

  const query = useQuery<QuietHours, Error>({
    queryKey: QUIET_HOURS_QUERY_KEY,
    enabled,
    queryFn: () => inAppNotificationsApi.getQuietHours(),
  });

  const mutation = useMutation<
    QuietHours,
    Error,
    QuietHours,
    OptimisticQuietHoursContext
  >({
    mutationFn: (next) => inAppNotificationsApi.updateQuietHours(next),
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey: QUIET_HOURS_QUERY_KEY });
      const previous = queryClient.getQueryData<QuietHours>(
        QUIET_HOURS_QUERY_KEY,
      );
      queryClient.setQueryData(QUIET_HOURS_QUERY_KEY, next);
      return { previous };
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(QUIET_HOURS_QUERY_KEY, saved);
    },
    onError: (_err, _next, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(QUIET_HOURS_QUERY_KEY, ctx.previous);
      }
      Alert.alert("Error", "Failed to update quiet hours.");
    },
  });

  const saved = query.data;

  const closeEditor = () => {
    setDraft(null);
    setEditingEdge(null);
  };

  /** Saves the draft and closes the editor; false (editor left open) when its edges match. */
  const commit = (): boolean => {
    if (!draft || !saved) {
      closeEditor();
      return true;
    }
    const result = resolveQuietHoursCommit(saved, draft);
    if (result.kind === "same-edges") return false;
    if (result.kind === "save") mutation.mutate(result.next);
    closeEditor();
    return true;
  };

  return {
    quietHours: draft ?? saved,
    loadFailed: query.isError,
    retry: () => {
      void query.refetch();
    },
    isSaving: mutation.isPending,
    editingEdge,
    edit: setEditingEdge,
    pickHour: (hour) => {
      if (!editingEdge) return;
      const base = draft ?? saved;
      if (!base) return;
      setDraft({ ...base, [editingEdge]: hour });
    },
    done: () => {
      if (commit()) return;
      Alert.alert("Quiet hours", "Start and end must be different hours.");
    },
    dismiss: () => {
      if (commit()) return;
      Alert.alert(
        "Quiet hours not saved",
        "Start and end must be different hours.",
      );
      closeEditor();
    },
  };
}

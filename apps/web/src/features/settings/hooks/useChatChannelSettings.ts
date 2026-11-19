"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { NotificationPlatform } from "@/features/notification/constants";
import {
  chatChannelPriorityQuery,
  preferencesApi,
} from "@/features/settings/api/preferencesApi";
import { preferenceKeys } from "@/features/settings/api/queryKeys";
import {
  linkedInPriorityOrder,
  withChannelFirst,
} from "@/features/settings/utils/chatChannelOrder";
import { toast } from "@/lib/toast";

interface UseChatChannelSettings {
  /** The linked platforms in priority order; the first is where GAIA texts first. Null until the stored order loads. */
  linkedOrder: NotificationPlatform[] | null;
  /** The stored order could not be read. */
  loadFailed: boolean;
  refetch: () => void;
  /** True while a save is in flight, so two choices can't race each other. */
  saving: boolean;
  putFirst: (platform: NotificationPlatform) => void;
}

/**
 * Owns which linked platform GAIA texts first: the stored priority order,
 * persisted immediately and rolled back on failure.
 */
export function useChatChannelSettings(
  linkedPlatforms: NotificationPlatform[],
): UseChatChannelSettings {
  const qc = useQueryClient();
  const { data, isError, refetch } = useQuery(chatChannelPriorityQuery());
  const order = data?.priority ?? null;

  const mutation = useMutation({
    mutationFn: preferencesApi.updateChatChannelPriority,
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: preferenceKeys.chatChannelPriority });
      const previous = qc.getQueryData(preferenceKeys.chatChannelPriority);
      qc.setQueryData(preferenceKeys.chatChannelPriority, { priority: next });
      return { previous };
    },
    onError: (_error, _next, context) => {
      qc.setQueryData(preferenceKeys.chatChannelPriority, context?.previous);
      toast.error("Couldn't save where GAIA texts you first.");
    },
    onSuccess: (saved) =>
      qc.setQueryData(preferenceKeys.chatChannelPriority, saved),
  });

  const linkedOrder = order && linkedInPriorityOrder(order, linkedPlatforms);

  return {
    linkedOrder,
    loadFailed: isError,
    refetch: () => void refetch(),
    saving: mutation.isPending,
    putFirst: (platform) => {
      if (!order || linkedOrder?.[0] === platform) return;
      mutation.mutate(withChannelFirst(order, linkedPlatforms, platform));
    },
  };
}

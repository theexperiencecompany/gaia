"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  type BriefingPreferences,
  briefingApi,
} from "@/features/briefing/api/briefingApi";
import {
  NOTIFICATION_PLATFORMS,
  type NotificationPlatform,
} from "@/features/notification/constants";
import { toast } from "@/lib/toast";

const BRIEFING_PREFERENCES_QUERY_KEY = ["briefing-preferences"];

/**
 * Coerce a server-provided order into a full, de-duplicated permutation of the
 * four known platforms — the UI always renders every platform, so drift or a
 * partial list can't drop one.
 */
function normalizeOrder(raw?: NotificationPlatform[]): NotificationPlatform[] {
  const known = new Set<NotificationPlatform>(NOTIFICATION_PLATFORMS);
  const seen = new Set<NotificationPlatform>();
  const result: NotificationPlatform[] = [];
  for (const platform of raw ?? []) {
    if (known.has(platform) && !seen.has(platform)) {
      result.push(platform);
      seen.add(platform);
    }
  }
  for (const platform of NOTIFICATION_PLATFORMS) {
    if (!seen.has(platform)) result.push(platform);
  }
  return result;
}

interface UseChannelPriorityResult {
  isLoading: boolean;
  /** Linked platforms, in priority order — the draggable rows. */
  linkedOrder: NotificationPlatform[];
  /** Unlinked platforms, pinned below and non-draggable. */
  unlinkedOrder: NotificationPlatform[];
  /** Apply a reordered linked list (fired continuously during a drag). */
  reorderLinked: (next: NotificationPlatform[]) => void;
  /** Persist the current order (fired on drop); reverts + toasts on failure. */
  persist: () => void;
}

/**
 * Owns the briefing channel-priority order: fetches it, tracks the live
 * (optimistic) order during a drag, and persists on drop with revert-on-error.
 * `linkedMap` marks which platforms have a connected account.
 */
export function useChannelPriority(
  linkedMap: Record<NotificationPlatform, boolean>,
): UseChannelPriorityResult {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: BRIEFING_PREFERENCES_QUERY_KEY,
    queryFn: briefingApi.fetchChannelPriority,
    staleTime: 5 * 60 * 1000,
  });

  const serverOrder = useMemo(
    () => normalizeOrder(data?.chat_channel_priority),
    [data],
  );

  const [order, setOrder] = useState<NotificationPlatform[]>(serverOrder);
  useEffect(() => {
    setOrder(serverOrder);
  }, [serverOrder]);

  const linkedOrder = order.filter((platform) => linkedMap[platform]);
  const unlinkedOrder = order.filter((platform) => !linkedMap[platform]);

  const save = useMutation({
    mutationFn: (next: NotificationPlatform[]) =>
      briefingApi.updateChannelPriority(next),
    onSuccess: (_data, next) => {
      queryClient.setQueryData<BriefingPreferences>(
        BRIEFING_PREFERENCES_QUERY_KEY,
        { chat_channel_priority: next },
      );
    },
    onError: () => {
      setOrder(serverOrder);
      toast.error("Couldn't save your briefing channel order.");
    },
  });

  // Reordering only moves the linked rows among themselves; unlinked platforms
  // keep their relative order at the tail so the stored list stays a full
  // permutation.
  const reorderLinked = (next: NotificationPlatform[]) => {
    setOrder([...next, ...unlinkedOrder]);
  };

  const persist = () => {
    save.mutate([...linkedOrder, ...unlinkedOrder]);
  };

  return { isLoading, linkedOrder, unlinkedOrder, reorderLinked, persist };
}

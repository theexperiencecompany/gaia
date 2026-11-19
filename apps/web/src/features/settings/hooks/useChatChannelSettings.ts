"use client";

import { useEffect, useState } from "react";
import type { NotificationPlatform } from "@/features/notification/constants";
import { chatChannelApi } from "@/features/settings/api/chatChannelApi";
import {
  linkedInPriorityOrder,
  withChannelFirst,
} from "@/features/settings/utils/chatChannelOrder";
import { toast } from "@/lib/toast";

interface UseChatChannelSettings {
  /** The linked platforms in priority order; the first is where GAIA texts first. */
  linkedOrder: NotificationPlatform[];
  /** True while a save is in flight, so two choices can't race each other. */
  saving: boolean;
  putFirst: (platform: NotificationPlatform) => Promise<void>;
}

/**
 * Owns which linked platform GAIA texts first: the stored priority order,
 * persisted immediately and rolled back on failure.
 */
export function useChatChannelSettings(
  linkedPlatforms: NotificationPlatform[],
): UseChatChannelSettings {
  const [order, setOrder] = useState<NotificationPlatform[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    chatChannelApi.fetchPriority().then((priority) => {
      setOrder(priority.priority);
    });
  }, []);

  const linkedOrder = linkedInPriorityOrder(order, linkedPlatforms);

  const putFirst = async (platform: NotificationPlatform) => {
    if (linkedOrder[0] === platform) return;
    const next = withChannelFirst(order, linkedPlatforms, platform);
    const previous = order;
    setOrder(next);
    setSaving(true);
    try {
      const saved = await chatChannelApi.updatePriority(next);
      setOrder(saved.priority);
    } catch {
      setOrder(previous);
      toast.error("Couldn't save where GAIA texts you first.");
    } finally {
      setSaving(false);
    }
  };

  return { linkedOrder, saving, putFirst };
}

"use client";

import { useEffect, useState } from "react";
import type { NotificationPlatform } from "@/features/notification/constants";
import { chatChannelApi } from "@/features/settings/api/chatChannelApi";
import {
  linkedInPriorityOrder,
  moveChannel,
} from "@/features/settings/utils/chatChannelOrder";
import { toast } from "@/lib/toast";

interface UseChatChannelSettings {
  /** The linked platforms in priority order — the rows the section renders. */
  linkedOrder: NotificationPlatform[];
  /** True while a reorder is in flight, so the arrows can't race each other. */
  saving: boolean;
  move: (index: number, direction: "up" | "down") => Promise<void>;
}

/**
 * Owns "where GAIA texts you": the stored priority order, persisted
 * immediately and rolled back on failure.
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

  const move = async (index: number, direction: "up" | "down") => {
    const nextLinked = moveChannel(linkedOrder, index, direction);
    if (nextLinked === linkedOrder) return;
    // Unlinked platforms stay at the tail, so relinking one later restores the
    // position the user chose for it rather than dropping it to the default.
    const linked = new Set(linkedPlatforms);
    const unlinked = order.filter((platform) => !linked.has(platform));
    const previous = order;
    setOrder([...nextLinked, ...unlinked]);
    setSaving(true);
    try {
      const saved = await chatChannelApi.updatePriority([
        ...nextLinked,
        ...unlinked,
      ]);
      setOrder(saved.priority);
    } catch {
      setOrder(previous);
      toast.error("Couldn't save where GAIA texts you.");
    } finally {
      setSaving(false);
    }
  };

  return {
    linkedOrder,
    saving,
    move,
  };
}

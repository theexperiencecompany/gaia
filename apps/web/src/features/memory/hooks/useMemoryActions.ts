"use client";

import { useCallback, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry } from "@/features/memory/api/types";
import { useConfirmation } from "@/hooks/useConfirmation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

/**
 * Edit + forget actions shared by every memory list surface (tree, all-tab).
 * Render the returned state with <EditMemoryModal> and <ConfirmationDialog>.
 */
export function useMemoryActions(onChanged: () => void) {
  const [editingMemory, setEditingMemory] = useState<MemoryEntry | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const { confirm, confirmationProps } = useConfirmation();

  const forgetMemory = useCallback(
    async (memory: MemoryEntry) => {
      if (!memory.id) return;

      const confirmed = await confirm({
        title: "Forget memory",
        message: `GAIA will stop recalling "${memory.content}". Forget it?`,
        confirmText: "Forget",
        cancelText: "Cancel",
        variant: "destructive",
      });
      if (!confirmed) return;

      setDeletingId(memory.id);
      try {
        const response = await memoryApi.deleteMemory(memory.id);
        if (response.success) {
          toast.success("Memory forgotten");
          trackEvent(ANALYTICS_EVENTS.MEMORY_ITEM_DELETED, {
            memory_id: memory.id,
          });
          onChanged();
        } else {
          toast.error(response.message || "Failed to forget memory");
        }
      } catch {
        toast.error("Failed to forget memory");
      } finally {
        setDeletingId(null);
      }
    },
    [confirm, onChanged],
  );

  return {
    editingMemory,
    setEditingMemory,
    deletingId,
    forgetMemory,
    confirmationProps,
  };
}

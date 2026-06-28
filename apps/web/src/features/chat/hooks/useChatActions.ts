"use client";

import { useCallback } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useDeleteConversation } from "@/hooks/useDeleteConversation";
import { db } from "@/lib/db/chatDb";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/stores/chatStore";

/**
 * Single source of truth for chat mutations (API + IndexedDB + store + toast).
 * Reusable across surfaces — the command palette, the sidebar dropdown, etc.
 * Navigation and confirmation are left to the caller (they're surface-specific).
 */
export function useChatActions() {
  const deleteConversation = useDeleteConversation();

  const rename = useCallback(async (id: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await chatApi.renameConversation(id, trimmed);
      await db.updateConversationFields(id, {
        title: trimmed,
        description: trimmed,
      });
      toast.success("Chat renamed");
    } catch (error) {
      toast.error("Failed to rename chat");
      throw error;
    }
  }, []);

  const toggleStar = useCallback(async (id: string, starred: boolean) => {
    const next = !starred;
    try {
      await chatApi.toggleStarConversation(id, next);
      await db.updateConversationFields(id, { starred: next });
      toast.success(next ? "Chat starred" : "Star removed");
    } catch (error) {
      toast.error("Failed to update star");
      throw error;
    }
  }, []);

  const toggleRead = useCallback(async (id: string, unread: boolean) => {
    const next = !unread;
    useChatStore.getState().updateConversation(id, { isUnread: next });
    await db.updateConversationFields(id, { isUnread: next });
    if (next) chatApi.markAsUnread(id).catch(console.error);
    else chatApi.markAsRead(id).catch(console.error);
  }, []);

  const remove = useCallback(
    (id: string) => deleteConversation(id),
    [deleteConversation],
  );

  return { rename, toggleStar, toggleRead, remove };
}

export type ChatActions = ReturnType<typeof useChatActions>;

import { useCallback, useEffect } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import type { IMessage } from "@/lib/db/chatDb";
import { db } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

/**
 * WebSocket payload for background executor notifications.
 * Delivered when an executor (live or queued) completes and generates
 * a notification as a NEW bot message.
 */
interface BgMessageEvent {
  type: "conversation.new_message";
  conversation_id: string;
  message: {
    type: "bot";
    response: string;
    message_id: string;
    date: string;
    task_id?: string;
    tool_data?: ToolDataEntry[];
    replyToMessage?: {
      id: string;
      content: string;
      role: "user" | "assistant";
    };
  };
}

/**
 * Subscribe to `conversation.new_message` WebSocket events.
 *
 * When an executor finishes (live or queued), the backend saves a NEW bot
 * message to MongoDB and pushes it here via WebSocket. This hook inserts
 * the message into IndexedDB and the Zustand store so the chat view
 * updates immediately — no page reload needed.
 *
 * Conversation-scoped: only updates the active chat view. Messages for
 * other conversations are persisted to IndexedDB (visible on navigation).
 */
export function useBgMessageWebSocket() {
  const handleBgMessage = useCallback(async (raw: unknown) => {
    const event = raw as BgMessageEvent;
    const { conversation_id, message } = event;

    if (!conversation_id || !message?.message_id) {
      return;
    }

    // Remove streaming placeholder (id === task_id) if one exists in the store.
    // The placeholder was created by useExecutorStream for live tool progress;
    // now the final message is here, so the placeholder is no longer needed.
    if (message.task_id) {
      const state = useChatStore.getState();
      const msgs = state.messagesByConversation[conversation_id] ?? [];
      const hasPlaceholder = msgs.some((m) => m.id === message.task_id);
      if (hasPlaceholder) {
        useChatStore.getState().removeMessage(message.task_id, conversation_id);
      }
    }

    // Build IMessage for IndexedDB
    const iMessage: IMessage = {
      id: message.message_id,
      conversationId: conversation_id,
      content: message.response,
      role: "assistant",
      status: "sent",
      createdAt: new Date(message.date),
      updatedAt: new Date(message.date),
      messageId: message.message_id,
      tool_data: message.tool_data ?? null,
      replyToMessageData: message.replyToMessage ?? null,
    };

    // Persist to IndexedDB (dbEventEmitter syncs to store automatically)
    try {
      await db.putMessage(iMessage);
    } catch (err) {
      console.error("[useBgMessageWebSocket] Failed to persist message:", err);
    }

    // Also update store directly for immediate render if viewing this conversation
    const activeConvoId = useChatStore.getState().activeConversationId;
    if (conversation_id === activeConvoId) {
      useChatStore.getState().addOrUpdateMessage(iMessage);
    }
  }, []);

  useEffect(() => {
    wsManager.on("conversation.new_message", handleBgMessage);
    return () => {
      wsManager.off("conversation.new_message", handleBgMessage);
    };
  }, [handleBgMessage]);
}

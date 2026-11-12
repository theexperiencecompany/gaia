import type { MessageReaction, TodoRunWake } from "@shared/api/generated";
import { useCallback, useEffect } from "react";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import {
  isViewingConversation,
  markConversationUnread,
} from "@/features/chat/stream/unread";
import { applyMessageReaction } from "@/features/chat/utils/reactionUtils";
import type { IMessage } from "@/lib/db/chatDb";
import { db } from "@/lib/db/chatDb";
import { streamLog } from "@/lib/streamLogger";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

/**
 * WebSocket payload for a message saved outside the open turn: a background
 * executor's NEW bot message, or the user-side wake that leads a tracked todo's run.
 */
interface BgMessageEvent {
  type: "conversation.new_message";
  conversation_id: string;
  message: {
    type: "bot" | "user";
    response: string;
    message_id: string;
    /** The message's place in the conversation's order. */
    seq: number;
    date: string;
    task_id?: string;
    /** Why a run that produced no reply failed — rendered instead of an empty bubble. */
    error?: string;
    tool_data?: TypedToolDataEntry[];
    follow_up_actions?: string[];
    todo_run_wake?: TodoRunWake;
    replyToMessage?: {
      id: string;
      content: string;
      role: "user" | "assistant";
    };
  };
}

/** A background result's reaction on the user message that asked for it. */
interface BgReactionEvent {
  type: typeof REACTION_EVENT;
  conversation_id: string;
  reaction: MessageReaction & { message_id: string };
}

const REACTION_EVENT = "conversation.message_reaction";

/**
 * Subscribe to `conversation.new_message` (and its reaction twin) and insert the
 * message into IndexedDB and the Zustand store.
 *
 * Conversation-scoped: only the active chat view updates immediately; other
 * conversations are persisted to IndexedDB and appear on navigation.
 */
export function useBgMessageWebSocket() {
  const handleBgMessage = useCallback(async (raw: unknown) => {
    const event = raw as BgMessageEvent;
    const { conversation_id, message } = event;

    if (!conversation_id || !message?.message_id) {
      return;
    }
    const isBotReply = message.type === "bot";

    // Remove streaming placeholder (id === task_id) if one exists in the store.
    // The placeholder was created by useExecutorStream for live tool progress;
    // now the final message is here, so the placeholder is no longer needed.
    if (isBotReply && message.task_id) {
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
      role: isBotReply ? "assistant" : "user",
      status: "sent",
      createdAt: new Date(message.date),
      updatedAt: new Date(message.date),
      messageId: message.message_id,
      seq: message.seq,
      tool_data: message.tool_data ?? null,
      error: message.error ?? null,
      follow_up_actions: message.follow_up_actions ?? null,
      replyToMessageData: message.replyToMessage ?? null,
      todoRunWake: message.todo_run_wake ?? null,
    };

    // Persist to IndexedDB (dbEventEmitter syncs to store automatically). When
    // this matches a queued executor placeholder (keyed by task_id, from
    // useExecutorStream), replace it atomically so no duplicate is left behind.
    try {
      if (isBotReply && message.task_id) {
        await db.replaceMessage(message.task_id, iMessage);
      } else {
        await db.putMessage(iMessage);
      }
    } catch (err) {
      console.error("[useBgMessageWebSocket] Failed to persist message:", err);
    }

    // Also update store directly for immediate render if viewing this conversation
    if (isViewingConversation(conversation_id)) {
      useChatStore.getState().addOrUpdateMessage(iMessage);
    } else if (isBotReply) {
      // A background result landing in a conversation the user isn't viewing
      // surfaces as unread in the sidebar (cleared by ChatPage's mark-as-read).
      markConversationUnread(conversation_id);
    }

    // End the awaiting-executor session AFTER the result message is in the
    // store, so loading hands off to the rendered result in the same frame — no
    // flash of "loading gone" before the result appears.
    const stream = useStreamStore.getState();
    if (
      isBotReply &&
      stream.sessions[conversation_id]?.phase === "awaiting_executor"
    ) {
      stream.endSession(conversation_id);
    }
    streamLog("ws", "conversation.new_message", {
      conversationId: conversation_id,
      detail: { task_id: message.task_id },
    });
  }, []);

  const handleBgReaction = useCallback(async (raw: unknown) => {
    const { conversation_id, reaction } = raw as BgReactionEvent;
    if (!conversation_id || !reaction?.message_id) return;
    await applyMessageReaction(conversation_id, reaction.message_id, {
      emoji: reaction.emoji,
      by: reaction.by,
    });
    // The reaction is the result's whole answer, so the run it ends is over.
    const stream = useStreamStore.getState();
    if (stream.sessions[conversation_id]?.phase === "awaiting_executor") {
      stream.endSession(conversation_id);
    }
    streamLog("ws", REACTION_EVENT, { conversationId: conversation_id });
  }, []);

  useEffect(() => {
    wsManager.on("conversation.new_message", handleBgMessage);
    wsManager.on(REACTION_EVENT, handleBgReaction);
    return () => {
      wsManager.off("conversation.new_message", handleBgMessage);
      wsManager.off(REACTION_EVENT, handleBgReaction);
    };
  }, [handleBgMessage, handleBgReaction]);
}

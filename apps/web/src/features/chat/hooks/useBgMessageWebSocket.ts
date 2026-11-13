import type { ReportSettledOutcome, TodoRunWake } from "@shared/api/generated";
import { useCallback, useEffect } from "react";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import {
  isViewingConversation,
  markConversationUnread,
} from "@/features/chat/stream/unread";
import type { IMessage } from "@/lib/db/chatDb";
import { db } from "@/lib/db/chatDb";
import { streamLog } from "@/lib/streamLogger";
import {
  OUTBOX_MESSAGE_EVENT,
  OutboxMessageKind,
} from "@/lib/websocket/outboxEvents";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

/**
 * WebSocket payload for a message saved outside the open turn: a background
 * executor's NEW bot message, or the user-side wake that leads a tracked todo's run.
 */
interface BgMessageEvent {
  type: typeof OUTBOX_MESSAGE_EVENT;
  kind: OutboxMessageKind;
  conversation_id: string;
  message: {
    type: "bot" | "user";
    response: string;
    message_id: string;
    date: string;
    kind?: string;
    reacts_to_message_id?: string;
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

/** WebSocket payload for how one run behind an accepted turn's status chip ended. */
interface ReportSettledEvent {
  type: typeof OUTBOX_MESSAGE_EVENT;
  kind: typeof OutboxMessageKind.ReportSettled;
  conversation_id: string;
  message_id: string;
  report_id: string;
  outcome: ReportSettledOutcome;
}

/** Record the run's outcome on the accepted turn, so its chip settles (the server keeps the same record for other devices and reloads). */
async function settleWorkChip(event: ReportSettledEvent): Promise<void> {
  const updated = await db.addWorkOutcome(event.message_id, {
    report_id: event.report_id,
    outcome: event.outcome,
  });
  if (!updated) {
    console.error(
      "[useBgMessageWebSocket] Settled run names a turn this device never saved:",
      event.message_id,
    );
  }
}

/** Remove the streaming placeholder (id === task_id) useExecutorStream queued for live tool progress; the final message replaces it. */
function removeExecutorPlaceholder(
  conversationId: string,
  taskId: string,
): void {
  const { messagesByConversation, removeMessage } = useChatStore.getState();
  const messages = messagesByConversation[conversationId] ?? [];
  if (messages.some((m) => m.id === taskId)) {
    removeMessage(taskId, conversationId);
  }
}

function toIMessage(
  conversationId: string,
  message: BgMessageEvent["message"],
): IMessage {
  return {
    id: message.message_id,
    conversationId,
    content: message.response,
    role: message.type === "bot" ? "assistant" : "user",
    status: "sent",
    createdAt: new Date(message.date),
    updatedAt: new Date(message.date),
    messageId: message.message_id,
    kind: message.kind ?? null,
    reacts_to_message_id: message.reacts_to_message_id ?? null,
    tool_data: message.tool_data ?? null,
    error: message.error ?? null,
    follow_up_actions: message.follow_up_actions ?? null,
    replyToMessageData: message.replyToMessage ?? null,
    todoRunWake: message.todo_run_wake ?? null,
  };
}

/** Persist to IndexedDB (dbEventEmitter syncs to the store); a message answering a queued executor placeholder replaces it atomically so no duplicate is left behind. */
async function persistMessage(
  message: IMessage,
  replacesTaskId: string | undefined,
): Promise<void> {
  try {
    if (replacesTaskId) {
      await db.replaceMessage(replacesTaskId, message);
    } else {
      await db.putMessage(message);
    }
  } catch (err) {
    console.error("[useBgMessageWebSocket] Failed to persist message:", err);
  }
}

/** Render now when the conversation is open; a bot result landing elsewhere surfaces as unread in the sidebar (cleared by ChatPage's mark-as-read). */
function surfaceMessage(message: IMessage, isBotReply: boolean): void {
  if (isViewingConversation(message.conversationId)) {
    useChatStore.getState().addOrUpdateMessage(message);
  } else if (isBotReply) {
    markConversationUnread(message.conversationId);
  }
}

/** End the awaiting-executor session after the result is in the store, so loading hands off to it in the same frame. */
function endAwaitingExecutor(conversationId: string): void {
  const stream = useStreamStore.getState();
  if (stream.sessions[conversationId]?.phase === "awaiting_executor") {
    stream.endSession(conversationId);
  }
}

async function handleConversationMessage(event: BgMessageEvent): Promise<void> {
  const { conversation_id, message } = event;
  if (!conversation_id || !message?.message_id) {
    return;
  }
  const isBotReply = message.type === "bot";
  const replacesTaskId = isBotReply ? message.task_id : undefined;

  if (replacesTaskId) {
    removeExecutorPlaceholder(conversation_id, replacesTaskId);
  }
  const iMessage = toIMessage(conversation_id, message);
  await persistMessage(iMessage, replacesTaskId);
  surfaceMessage(iMessage, isBotReply);
  if (isBotReply) {
    endAwaitingExecutor(conversation_id);
  }
  streamLog("ws", OUTBOX_MESSAGE_EVENT, {
    conversationId: conversation_id,
    detail: { task_id: message.task_id },
  });
}

/**
 * Subscribe to `outbox.message` WebSocket events of kind
 * `conversation_message` and insert the message into IndexedDB and the Zustand store,
 * and of kind `report_settled` and settle the status chip of the turn it names.
 *
 * Conversation-scoped: only the active chat view updates immediately; other
 * conversations are persisted to IndexedDB and appear on navigation.
 */
export function useBgMessageWebSocket() {
  const handleOutboxEvent = useCallback(async (raw: unknown) => {
    const event = raw as BgMessageEvent | ReportSettledEvent;
    if (event.kind === OutboxMessageKind.ReportSettled) {
      await settleWorkChip(event);
    } else if (event.kind === OutboxMessageKind.ConversationMessage) {
      await handleConversationMessage(event);
    }
  }, []);

  useEffect(() => {
    wsManager.on(OUTBOX_MESSAGE_EVENT, handleOutboxEvent);
    return () => {
      wsManager.off(OUTBOX_MESSAGE_EVENT, handleOutboxEvent);
    };
  }, [handleOutboxEvent]);
}

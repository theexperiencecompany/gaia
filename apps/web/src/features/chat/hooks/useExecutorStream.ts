import {
  mergeToolOutputIntoToolData,
  parseChatStreamEvent,
} from "@shared/chat";
import { useCallback, useEffect } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { chatApi } from "@/features/chat/api/chatApi";
import { db, type IMessage } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

interface ExecutorStreamStartedEvent {
  type: "executor.stream_started";
  stream_id: string;
  conversation_id: string;
  task_id: string;
}

/**
 * Subscribe to `executor.stream_started` WebSocket events.
 *
 * When a queued executor task starts, the backend emits this event with a
 * fresh stream_id. This hook creates a temporary placeholder message in the
 * Zustand store and opens a new SSE connection to `GET /stream/{stream_id}`
 * to stream live tool events into the placeholder. The placeholder is removed
 * when `useBgMessageWebSocket` receives the final `conversation.new_message`.
 *
 * Only active for the currently-viewed conversation — if the user is elsewhere,
 * the final message arrives via the normal WS notification path.
 */
export function useExecutorStream() {
  const handleExecutorStreamStarted = useCallback(async (raw: unknown) => {
    const event = raw as ExecutorStreamStartedEvent;
    const { stream_id, conversation_id, task_id } = event;

    if (!stream_id || !conversation_id || !task_id) {
      return;
    }

    const activeConvoId = useChatStore.getState().activeConversationId;
    if (conversation_id !== activeConvoId) {
      // Not the active conversation — skip live streaming, final WS message handles it
      return;
    }

    // Create a placeholder message in the store for live tool progress.
    // id === task_id so useBgMessageWebSocket can find and remove it when the
    // final conversation.new_message arrives.
    const placeholder: IMessage = {
      id: task_id,
      conversationId: conversation_id,
      content: "",
      role: "assistant",
      status: "sending",
      createdAt: new Date(),
      updatedAt: new Date(),
      messageId: task_id,
      tool_data: null,
    };
    useChatStore.getState().addOrUpdateMessage(placeholder);
    // Persist the placeholder (keyed by task_id) so live tool cards survive a
    // refresh that happens before the final conversation.new_message arrives.
    // useBgMessageWebSocket replaces this entry by task_id when the final
    // message lands; an orphaned placeholder is only possible if the run is
    // never finalized, in which case keeping its cards is the desired outcome.
    await db.putMessage(placeholder);

    const controller = new AbortController();

    try {
      await chatApi.subscribeToExecutorStream(
        stream_id,
        (sseEvent) => {
          if (!sseEvent.data) return;
          const parsedEvents = parseChatStreamEvent(sseEvent.data);

          for (const parsed of parsedEvents) {
            if (parsed.type === "tool_data") {
              const state = useChatStore.getState();
              const msgs = state.messagesByConversation[conversation_id] ?? [];
              const current = msgs.find((m) => m.id === task_id);
              if (!current) return;
              const existing: ToolDataEntry[] =
                (current.tool_data as ToolDataEntry[]) ?? [];
              const updated: IMessage = {
                ...current,
                tool_data: [...existing, parsed.entry as ToolDataEntry],
                updatedAt: new Date(),
              };
              useChatStore.getState().addOrUpdateMessage(updated);
              void db.putMessage(updated);
            }

            if (parsed.type === "tool_output") {
              const state = useChatStore.getState();
              const msgs = state.messagesByConversation[conversation_id] ?? [];
              const current = msgs.find((m) => m.id === task_id);
              if (!current) return;
              const existing: ToolDataEntry[] =
                (current.tool_data as ToolDataEntry[]) ?? [];
              const mergedToolData = mergeToolOutputIntoToolData(
                existing,
                parsed.output,
              );
              const updated: IMessage = {
                ...current,
                tool_data: mergedToolData,
                updatedAt: new Date(),
              };
              useChatStore.getState().addOrUpdateMessage(updated);
              void db.putMessage(updated);
            }
          }
        },
        () => {
          // Stream closed — mark placeholder as sent so loading indicator clears.
          // The final conversation.new_message WS event will replace this shortly.
          const state = useChatStore.getState();
          const msgs = state.messagesByConversation[conversation_id] ?? [];
          const current = msgs.find((m) => m.id === task_id);
          if (current) {
            const finalized: IMessage = {
              ...current,
              status: "sent",
              updatedAt: new Date(),
            };
            useChatStore.getState().addOrUpdateMessage(finalized);
            void db.putMessage(finalized);
          }
        },
        (err) => {
          console.error("[useExecutorStream] SSE error:", err);
          controller.abort();
        },
        controller.signal,
      );
    } catch (err) {
      console.error(
        "[useExecutorStream] Failed to subscribe to executor stream:",
        err,
      );
    }
  }, []);

  useEffect(() => {
    wsManager.on("executor.stream_started", handleExecutorStreamStarted);
    return () => {
      wsManager.off("executor.stream_started", handleExecutorStreamStarted);
    };
  }, [handleExecutorStreamStarted]);
}

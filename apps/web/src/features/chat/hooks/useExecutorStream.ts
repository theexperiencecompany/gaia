import {
  mergeToolOutputIntoToolData,
  parseChatStreamEvent,
} from "@shared/chat";
import { useCallback, useEffect, useRef } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { chatApi } from "@/features/chat/api/chatApi";
import { relayDesktopToolRequest } from "@/features/chat/utils/desktopToolBridge";
import { db, type IMessage } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

// Coalesce IndexedDB writes during a live executor stream. The placeholder is
// re-persisted at most this often (plus a guaranteed final write on close), so a
// run emitting many tool events doesn't trigger one full-message write per chunk.
const DB_WRITE_THROTTLE_MS = 500;

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
  // Abort in-flight SSE subscriptions on unmount, and dedupe concurrent
  // subscriptions for the same stream_id — a re-emitted stream_started would
  // otherwise open a second reader that appends duplicate tool cards.
  const controllersRef = useRef<Set<AbortController>>(new Set());
  const activeStreamsRef = useRef<Set<string>>(new Set());

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

    if (activeStreamsRef.current.has(stream_id)) {
      // Already streaming this run — ignore a duplicate stream_started.
      return;
    }
    activeStreamsRef.current.add(stream_id);

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
    controllersRef.current.add(controller);

    // Coalesced IndexedDB persistence: the store update renders live, the
    // throttled DB write is only a refresh-survival snapshot.
    let writeTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingWrite: IMessage | null = null;
    const flushWrite = () => {
      writeTimer = null;
      if (pendingWrite) {
        void db.putMessage(pendingWrite);
        pendingWrite = null;
      }
    };
    const scheduleWrite = (msg: IMessage) => {
      pendingWrite = msg;
      if (writeTimer === null) {
        writeTimer = setTimeout(flushWrite, DB_WRITE_THROTTLE_MS);
      }
    };
    const applyUpdate = (updated: IMessage) => {
      useChatStore.getState().addOrUpdateMessage(updated);
      scheduleWrite(updated);
    };
    // Apply a tool_data transform onto the live placeholder. Returns silently if
    // the placeholder is momentarily absent so the rest of the SSE batch still
    // processes (a `return` here would drop every remaining event in the frame).
    const updateToolData = (
      transform: (existing: ToolDataEntry[]) => ToolDataEntry[],
    ) => {
      const state = useChatStore.getState();
      const msgs = state.messagesByConversation[conversation_id] ?? [];
      const current = msgs.find((m) => m.id === task_id);
      if (!current) return;
      const existing: ToolDataEntry[] =
        (current.tool_data as ToolDataEntry[]) ?? [];
      applyUpdate({
        ...current,
        tool_data: transform(existing),
        updatedAt: new Date(),
      });
    };
    // Mark the placeholder sent so the loading indicator clears. Runs on every
    // terminal outcome — normal close AND error/abort — otherwise an SSE error
    // leaves the placeholder status:'sending' and the card spins forever.
    const finalizePlaceholder = () => {
      if (writeTimer !== null) {
        clearTimeout(writeTimer);
        writeTimer = null;
      }
      pendingWrite = null;
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
    };

    try {
      await chatApi.subscribeToExecutorStream(
        stream_id,
        (sseEvent) => {
          if (!sseEvent.data) return;
          for (const parsed of parseChatStreamEvent(sseEvent.data)) {
            if (parsed.type === "desktop_tool_request") {
              // Queued executor runs ride this stream too — relay desktop
              // actions exactly like the live chat stream does.
              void relayDesktopToolRequest(parsed.request);
              continue;
            }

            if (parsed.type === "tool_data") {
              updateToolData((existing) => [
                ...existing,
                parsed.entry as ToolDataEntry,
              ]);
            } else if (parsed.type === "tool_output") {
              updateToolData((existing) =>
                mergeToolOutputIntoToolData(existing, parsed.output),
              );
            }
          }
        },
        () => {
          // Stream closed cleanly — finalize so the loading indicator clears.
          // The final conversation.new_message WS event replaces this shortly.
          finalizePlaceholder();
        },
        (err) => {
          console.error("[useExecutorStream] SSE error:", err);
          controller.abort();
        },
        controller.signal,
      );
    } catch (err) {
      // subscribeToExecutorStream re-throws on SSE error/abort. Finalize here so
      // the error path clears the spinner too (not only the clean-close path).
      console.error(
        "[useExecutorStream] Executor stream ended with error:",
        err,
      );
      finalizePlaceholder();
    } finally {
      controllersRef.current.delete(controller);
      activeStreamsRef.current.delete(stream_id);
    }
  }, []);

  useEffect(() => {
    const controllers = controllersRef.current;
    wsManager.on("executor.stream_started", handleExecutorStreamStarted);
    return () => {
      wsManager.off("executor.stream_started", handleExecutorStreamStarted);
      for (const controller of controllers) {
        controller.abort();
      }
      controllers.clear();
    };
  }, [handleExecutorStreamStarted]);
}

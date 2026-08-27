import {
  applyStreamEvent,
  createTurnAccumulator,
  parseChatStreamEvent,
  type TurnAccumulator,
} from "@shared/chat";
import { useEffect, useMemo, useRef } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { chatApi } from "@/features/chat/api/chatApi";
import { relayDesktopToolRequest } from "@/features/chat/utils/desktopToolBridge";
import { loadingLabelForEvent } from "@/features/chat/utils/loadingHints";
import { db, type IMessage } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { ImageData, MemoryData } from "@/types/features/toolDataTypes";

// Coalesce IndexedDB writes during a live executor stream. The placeholder is
// re-persisted at most this often (plus a guaranteed final write on close), so a
// run emitting many tool events doesn't trigger one full-message write per chunk.
const DB_WRITE_THROTTLE_MS = 500;

// Shown when a background executor's stream dies before it delivered a result.
const EXECUTOR_STREAM_FAILED =
  "This background task stopped before it finished.";

interface ExecutorStreamStartedEvent {
  type: "executor.stream_started";
  stream_id: string;
  conversation_id: string;
  task_id: string;
  /** Set for a HIL resume: the ORIGINAL turn's bot message, which this stream
   *  continues. Absent for a plain queued run, which gets its own placeholder. */
  bot_message_id?: string | null;
}

/** Project the shared accumulator onto the placeholder message record. */
const applyAccumulatorToMessage = (
  base: IMessage,
  acc: TurnAccumulator,
): IMessage => ({
  ...base,
  content: acc.responseText,
  tool_data: acc.toolData.length > 0 ? (acc.toolData as ToolDataEntry[]) : null,
  follow_up_actions: acc.followUpActions,
  image_data: (acc.imageData as ImageData | null) ?? null,
  memory_data: (acc.extras.memory_data as MemoryData | undefined) ?? null,
  todo_progress: (acc.todoProgress as TodoProgressData | null) ?? null,
  updatedAt: new Date(),
});

/**
 * Handle one `executor.stream_started` event: open the SSE connection and fold
 * it into a placeholder message. Takes its two live sets as arguments so the
 * whole run is exercisable without a React renderer.
 *
 * `controllers` holds in-flight subscriptions so the hook can abort them on
 * unmount; `activeStreams` dedupes by stream_id — a re-emitted stream_started
 * would otherwise open a second reader that appends duplicate tool cards.
 */
export const createExecutorStreamHandler =
  (controllers: Set<AbortController>, activeStreams: Set<string>) =>
  async (raw: unknown): Promise<void> => {
    const event = raw as ExecutorStreamStartedEvent;
    const { stream_id, conversation_id, task_id } = event;
    const resumedMessageId = event.bot_message_id ?? null;

    if (!stream_id || !conversation_id || !task_id) {
      return;
    }

    const activeConvoId = useChatStore.getState().activeConversationId;
    if (conversation_id !== activeConvoId) {
      // Not the active conversation — skip live streaming, final WS message handles it
      return;
    }

    if (activeStreams.has(stream_id)) {
      // Already streaming this run — ignore a duplicate stream_started.
      return;
    }
    activeStreams.add(stream_id);
    streamLog("lifecycle", "executor-stream:start", {
      conversationId: conversation_id,
      detail: { stream_id, task_id },
    });

    // A HIL resume continues the original turn's message: stream into THAT
    // record so the turn keeps one tool accordion. Only a run with no message
    // to continue (a plain queued task) opens its own placeholder.
    const existing = resumedMessageId
      ? (
          useChatStore.getState().messagesByConversation[conversation_id] ?? []
        ).find((m) => m.id === resumedMessageId)
      : undefined;
    const targetId = existing ? resumedMessageId! : task_id;

    if (!existing) {
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
    }

    const controller = new AbortController();
    controllers.add(controller);

    // The projection below REPLACES the record's fields, so a continued message
    // must seed the accumulator with what it already has or its earlier cards
    // and text would be wiped by the first resumed frame.
    let acc = createTurnAccumulator();
    if (existing) {
      acc = {
        ...createTurnAccumulator(existing.content ?? ""),
        toolData: [
          ...((existing.tool_data as TurnAccumulator["toolData"]) ?? []),
        ],
      };
    }

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

    const flushToStore = () => {
      const state = useChatStore.getState();
      const msgs = state.messagesByConversation[conversation_id] ?? [];
      const current = msgs.find((m) => m.id === targetId);
      // Target momentarily absent — skip this frame, keep the stream alive.
      if (!current) return;
      const updated = applyAccumulatorToMessage(current, acc);
      state.updateMessageInPlace(updated);
      scheduleWrite(updated);
    };

    // Mark the placeholder sent so the loading indicator clears. Runs on every
    // terminal outcome — normal close AND error/abort — otherwise an SSE error
    // leaves the placeholder status:'sending' and the card spins forever.
    const finalizePlaceholder = (error?: string) => {
      if (writeTimer !== null) {
        clearTimeout(writeTimer);
        writeTimer = null;
      }
      pendingWrite = null;
      const state = useChatStore.getState();
      const msgs = state.messagesByConversation[conversation_id] ?? [];
      const current = msgs.find((m) => m.id === targetId);
      if (current) {
        const finalized: IMessage = {
          ...applyAccumulatorToMessage(current, acc),
          status: error ? "failed" : "sent",
          error: error ?? null,
        };
        state.updateMessageInPlace(finalized);
        void db.putMessage(finalized);
      }
      streamLog("lifecycle", "executor-stream:end", {
        conversationId: conversation_id,
        detail: { stream_id, task_id },
      });
    };

    // A run that dies publishes an error frame and then closes — the close looks
    // exactly like a clean one, so without holding the reason here the failed run
    // finalizes as `sent` and renders as a finished answer.
    let terminalError: string | undefined;

    try {
      await chatApi.subscribeToExecutorStream(
        stream_id,
        (sseEvent) => {
          if (!sseEvent.data) return;
          for (const parsed of parseChatStreamEvent(sseEvent.data)) {
            streamLog("sse", `executor-event:${parsed.type}`, {
              conversationId: conversation_id,
            });
            if (parsed.type === "error") {
              terminalError = parsed.error;
              continue;
            }
            if (parsed.type === "desktop_tool_request") {
              // Queued executor runs ride this stream too — relay desktop
              // actions exactly like the live chat stream does.
              void relayDesktopToolRequest(parsed.request);
              continue;
            }
            if (parsed.type === "parse_error") {
              streamLogError("sse", "executor-malformed-frame", {
                conversationId: conversation_id,
                detail: parsed.raw,
              });
              continue;
            }
            // The loading indicator is driven by the turn session, which is no
            // longer reading anything — a resumed run streams here instead. Left
            // unlabelled, the indicator froze on whatever the pause set
            // ("Resuming") for the entire rest of the run.
            const label = loadingLabelForEvent(parsed);
            if (label) {
              useStreamStore
                .getState()
                .setSessionLoadingText(
                  conversation_id,
                  label.text,
                  label.toolInfo,
                );
            }
            acc = applyStreamEvent(acc, parsed);
          }
          flushToStore();
        },
        () => {
          // Stream closed — finalize so the loading indicator clears. A run that
          // errored gets its own reason; a clean one is replaced shortly by the
          // final conversation.new_message WS event.
          finalizePlaceholder(terminalError);
        },
        (err) => {
          console.error("[useExecutorStream] SSE error:", err);
          controller.abort();
        },
        controller.signal,
      );
    } catch (err) {
      // subscribeToExecutorStream re-throws on SSE error/abort. Finalize here so
      // the error path clears the spinner too (not only the clean-close path) —
      // and carry the reason, or a dead background run persists as a finished
      // one and renders as a complete answer.
      console.error(
        "[useExecutorStream] Executor stream ended with error:",
        err,
      );
      finalizePlaceholder(terminalError ?? EXECUTOR_STREAM_FAILED);
    } finally {
      controllers.delete(controller);
      activeStreams.delete(stream_id);
    }
  };

/**
 * Subscribe to `executor.stream_started` WebSocket events.
 *
 * When a queued executor task starts, the backend emits this event with a
 * fresh stream_id. This hook creates a temporary placeholder message in the
 * Zustand store and opens a new SSE connection to `GET /stream/{stream_id}`,
 * folding live events into the placeholder through the SAME shared accumulator
 * the live chat turn uses — reasoning, subagents, todo progress, and text all
 * render identically on both paths. The placeholder is removed when
 * `useBgMessageWebSocket` receives the final `conversation.new_message`.
 *
 * Only active for the currently-viewed conversation — if the user is elsewhere,
 * the final message arrives via the normal WS notification path.
 */
export function useExecutorStream() {
  const controllersRef = useRef<Set<AbortController>>(new Set());
  const activeStreamsRef = useRef<Set<string>>(new Set());

  const handleExecutorStreamStarted = useMemo(
    () =>
      createExecutorStreamHandler(
        controllersRef.current,
        activeStreamsRef.current,
      ),
    [],
  );

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

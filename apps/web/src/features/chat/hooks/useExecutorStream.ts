import {
  applyStreamEvent,
  createTurnAccumulator,
  parseChatStreamEvent,
} from "@shared/chat";
import { useEffect, useMemo, useRef } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { relayDesktopToolRequest } from "@/features/chat/utils/desktopToolBridge";
import {
  executorProjection,
  subagentProjection,
} from "@/features/chat/utils/executorStreamProjection";
import { loadingLabelForEvent } from "@/features/chat/utils/loadingHints";
import { db, type IMessage } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

// Coalesce IndexedDB writes during a live executor stream. The placeholder is
// re-persisted at most this often (plus a guaranteed final write on close), so a
// run emitting many tool events doesn't trigger one full-message write per chunk.
const DB_WRITE_THROTTLE_MS = 500;

// Upper bound for the background-run indicator. The stream close always clears
// it; this only guards a half-open connection that never closes.
const BACKGROUND_RUN_TIMEOUT_MS = 10 * 60 * 1000;

// Shown when a background executor's stream dies before it delivered a result.
const EXECUTOR_STREAM_FAILED =
  "This background task stopped before it finished.";

interface ExecutorStreamStartedEvent {
  type: "executor.stream_started";
  stream_id: string;
  conversation_id: string;
  task_id: string;
  /** The message this stream folds into: for an executor, a HIL resume's
   *  ORIGINAL turn (absent for a plain queued run, which gets its own
   *  placeholder); for a background subagent, the turn that dispatched it. */
  bot_message_id?: string | null;
  /** Mirrors the backend DetachedStreamKind. An executor run owns its message;
   *  a background subagent only adds its own cards to one another run may still
   *  be writing. Absent means executor. */
  kind?: "executor" | "subagent";
}

/**
 * Label the background "working" row from a frame. The turn session (no longer
 * reading) normally drives the loading indicator; a resumed executor streams
 * here instead, so leaving it unlabelled would freeze it on the pause's
 * "Resuming" text. A subagent's progress is its own row's, never the turn's.
 */
const labelBackgroundProgress = (
  conversationId: string,
  parsed: Parameters<typeof loadingLabelForEvent>[0],
  isSubagent: boolean,
) => {
  const label = loadingLabelForEvent(parsed);
  if (!label) return;
  const streams = useStreamStore.getState();
  if (!isSubagent) {
    streams.setSessionLoadingText(conversationId, label.text, label.toolInfo);
  }
  streams.setBackgroundLoading(conversationId, label.text, label.toolInfo);
};

/**
 * A placeholder for a run with no message to continue (a plain queued task).
 * id === task_id so useBgMessageWebSocket can find and replace it when the
 * final conversation.new_message arrives; persisted so tool cards survive a
 * refresh before then — an orphan only occurs if the run never finalizes.
 */
const openPlaceholder = async (conversationId: string, taskId: string) => {
  const placeholder: IMessage = {
    id: taskId,
    conversationId,
    content: "",
    role: "assistant",
    status: "sending",
    createdAt: new Date(),
    updatedAt: new Date(),
    messageId: taskId,
    tool_data: null,
  };
  useChatStore.getState().addOrUpdateMessage(placeholder);
  await db.putMessage(placeholder);
};

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
    const isSubagent = event.kind === "subagent";

    if (!stream_id || !conversation_id || !task_id) {
      return;
    }

    const activeConvoId = useChatStore.getState().activeConversationId;
    if (conversation_id !== activeConvoId) {
      // Not the active conversation — skip live streaming, final WS message handles it
      return;
    }

    // A HIL resume continues the original turn's message, and a background
    // subagent adds to the turn that dispatched it: both stream into THAT record
    // so the turn keeps one tool accordion.
    const existing = resumedMessageId
      ? (
          useChatStore.getState().messagesByConversation[conversation_id] ?? []
        ).find((m) => m.id === resumedMessageId)
      : undefined;
    if (isSubagent && !existing) {
      // With that turn not loaded, the subagent's frames are saved onto it
      // server-side and show on reload.
      streamLog("lifecycle", "executor-stream:subagent-target-missing", {
        conversationId: conversation_id,
        detail: { stream_id, task_id },
      });
      return;
    }
    const targetId = existing ? resumedMessageId! : task_id;

    if (activeStreams.has(stream_id)) {
      // Already streaming this run — ignore a duplicate stream_started.
      return;
    }
    activeStreams.add(stream_id);
    streamLog("lifecycle", "executor-stream:start", {
      conversationId: conversation_id,
      detail: { stream_id, task_id },
    });

    // A detached run has no turn session driving the loading indicator, so
    // track it separately for the "working" row; cleared on close/error/timeout.
    useStreamStore.getState().setBackgroundLoading(conversation_id, "");
    const backgroundTimeout = setTimeout(() => {
      useStreamStore.getState().clearBackgroundLoading(conversation_id);
    }, BACKGROUND_RUN_TIMEOUT_MS);

    if (!existing) {
      await openPlaceholder(conversation_id, task_id);
    }

    const controller = new AbortController();
    controllers.add(controller);

    // A subagent folds its own entries in, so it starts from an empty accumulator.
    const { projection, initial } = isSubagent
      ? { projection: subagentProjection(), initial: createTurnAccumulator() }
      : executorProjection(existing);
    let acc = initial;

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
      const updated = projection.project(current, acc);
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
      clearTimeout(backgroundTimeout);
      pendingWrite = null;
      useStreamStore.getState().clearBackgroundLoading(conversation_id);
      const state = useChatStore.getState();
      const msgs = state.messagesByConversation[conversation_id] ?? [];
      const current = msgs.find((m) => m.id === targetId);
      if (current) {
        const finalized = projection.finalize(current, acc, error);
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
            labelBackgroundProgress(conversation_id, parsed, isSubagent);
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
      // subscribeToExecutorStream re-throws on SSE error/abort; finalize here too
      // (not only on clean close) so the spinner clears, and carry the reason or a
      // dead background run persists as a finished, complete-looking answer.
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
 * Subscribe to `executor.stream_started` events: create a placeholder and open
 * an SSE connection to `GET /stream/{stream_id}`, folding events through the
 * same accumulator the live chat turn uses so both paths render identically.
 * Active only for the currently-viewed conversation; removed on the final
 * `conversation.new_message`.
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

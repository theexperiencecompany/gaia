import { useEffect, useRef } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { streamController } from "@/features/chat/utils/streamController";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { db } from "@/lib/db/chatDb";
import { streamState } from "@/lib/streamState";
import { toast } from "@/lib/toast";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import { useLoadingStore } from "@/stores/loadingStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";
import fetchDate from "@/utils/date/dateUtils";
import { useLoadingText } from "../useLoadingText";
import { createConversationInitHandlers } from "./conversationInit";
import { createIMessage, createMessageHelpers } from "./messageBuilder";
import { createPersistenceHelpers } from "./persistence";
import { createStreamHandlers } from "./streamHandlers";
import type { PendingStreamArgs, StreamContext } from "./types";

// Fallback for the rare case a background executor never delivers its result
// message — clears the "awaiting executor result" UI so it can't stick forever.
const EXECUTOR_RESULT_TIMEOUT_MS = 120_000;

export const useChatStream = () => {
  const { setIsLoading, setAbortController } = useLoading();
  const { convoMessages } = useConversation();
  const { setLoadingText, resetLoadingText } = useLoadingText();

  const streamInProgressRef = useRef(false);
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamCloseHandledRef = useRef(false);
  const pendingStreamArgsRef = useRef<PendingStreamArgs | null>(null);

  const refs = useRef({
    convoMessages,
    botMessage: null as MessageType | null,
    userMessage: null as MessageType | null,
    optimisticUserId: null as string | null,
    accumulatedResponse: "",
    userPrompt: "",
    currentStreamingMessages: [] as MessageType[],
    newConversation: {
      id: null as string | null,
      description: null as string | null,
    },
  });

  // Keep the ref's view of conversation history current so queued / subsequent
  // sends include the latest messages (fixes streaming race + missing UI msgs).
  useEffect(() => {
    refs.current.convoMessages = convoMessages;
  }, [convoMessages]);

  const ctx: StreamContext = {
    refs,
    persistTimerRef,
    pendingStreamArgsRef,
    streamInProgressRef,
    streamCloseHandledRef,
    setIsLoading,
    setAbortController,
    setLoadingText,
    resetLoadingText,
  };

  const { updateBotMessage, updateBotMessageInStore } =
    createMessageHelpers(ctx);

  const { schedulePersist, persistBotMessage, resolveConversationId } =
    createPersistenceHelpers(ctx, updateBotMessageInStore);

  const {
    handleConversationCreation: _handleConversationCreation,
    handleConversationDescriptionUpdate,
    handleNewConversation,
    handleExistingConversationMessages,
  } = createConversationInitHandlers(ctx, persistBotMessage);

  const { handleStreamEvent } = createStreamHandlers({
    ctx,
    updateBotMessage,
    updateBotMessageInStore,
    schedulePersist,
    resolveConversationId,
    handleNewConversation,
    handleExistingConversationMessages,
    handleConversationDescriptionUpdate,
  });

  const resetStreamState = () => {
    streamState.endStream();

    streamInProgressRef.current = false;
    refs.current.botMessage = null;
    refs.current.userMessage = null;
    refs.current.optimisticUserId = null;
    refs.current.accumulatedResponse = "";
    refs.current.userPrompt = "";
    refs.current.currentStreamingMessages = [];
    refs.current.newConversation = { id: null, description: null };
    setIsLoading(false);
    useLoadingStore.getState().setMainResponseStreaming(false);
    resetLoadingText();
    streamController.clear();
    setAbortController(null);

    useChatStore.getState().setStreamingConversationId(null);
    useChatStore.getState().setExecutorPendingConversationId(null);
    useChatStore.getState().clearOptimisticMessage();
  };

  const streamFunction = async (
    inputText: string,
    currentMessages: MessageType[],
    fileData: FileData[] = [],
    selectedTool: string | null = null,
    toolCategory: string | null = null,
    selectedWorkflow: WorkflowData | null = null,
    selectedCalendarEvent: SelectedCalendarEventData | null = null,
    optimisticUserId?: string,
    replyToMessage: {
      id: string;
      content: string;
      role: "user" | "assistant";
    } | null = null,
    conversationId: string | null = null,
    isOnboardingDemo: boolean = false,
  ) => {
    if (streamInProgressRef.current) {
      console.warn(
        "[useChatStream] stream already in progress, queuing for later",
      );
      pendingStreamArgsRef.current = [
        inputText,
        currentMessages,
        fileData,
        selectedTool,
        toolCategory,
        selectedWorkflow,
        selectedCalendarEvent,
        optimisticUserId,
        replyToMessage,
        conversationId,
        isOnboardingDemo,
      ];
      return;
    }
    console.log(
      "[useChatStream] starting stream, activeConversationId:",
      useChatStore.getState().activeConversationId,
    );

    streamInProgressRef.current = true;

    const effectiveConversationId =
      conversationId ??
      useChatStore.getState().activeConversationId ??
      refs.current.newConversation.id;
    streamState.startStream(effectiveConversationId);

    trackEvent(ANALYTICS_EVENTS.CHAT_STARTED, {
      conversation_id: effectiveConversationId,
      is_new_conversation: !useChatStore.getState().activeConversationId,
    });

    try {
      refs.current.accumulatedResponse = "";
      refs.current.userPrompt = inputText;
      streamCloseHandledRef.current = false;

      refs.current.currentStreamingMessages = [
        ...refs.current.convoMessages,
        ...currentMessages,
      ];

      refs.current.userMessage =
        currentMessages.find((m) => m.type === "user") || null;
      refs.current.optimisticUserId = optimisticUserId || null;

      resetLoadingText();

      refs.current.botMessage = {
        type: "bot",
        message_id: "",
        response: "",
        date: fetchDate(),
        loading: true,
        fileIds: fileData.map((f) => f.fileId),
        fileData,
        selectedTool,
        toolCategory,
        selectedWorkflow,
        selectedCalendarEvent,
      };

      const controller = new AbortController();
      setAbortController(controller);

      streamController.setSaveCallback(async () => {
        streamState.setPendingSave(true);

        try {
          if (refs.current.botMessage) {
            updateBotMessage({
              response: refs.current.accumulatedResponse,
              loading: false,
            });

            const activeConversationId =
              refs.current.newConversation.id ||
              useChatStore.getState().activeConversationId;

            if (activeConversationId && refs.current.botMessage.message_id) {
              updateBotMessageInStore(activeConversationId);

              const metadataUpdates = {
                tool_data: refs.current.botMessage.tool_data ?? null,
                follow_up_actions:
                  refs.current.botMessage.follow_up_actions ?? null,
                image_data: refs.current.botMessage.image_data ?? null,
                memory_data: refs.current.botMessage.memory_data ?? null,
                todo_progress: refs.current.botMessage.todo_progress ?? null,
              };

              await db.updateMessage(refs.current.botMessage.message_id, {
                content: refs.current.accumulatedResponse,
                status: "sent",
                ...metadataUpdates,
              });
            }
          }
        } catch (error) {
          console.error("Failed to persist message on abort:", error);
        } finally {
          streamState.setPendingSave(false);
        }
      });

      console.log(
        "[useChatStream] calling chatApi.fetchChatStream, inputText:",
        inputText,
        "msgs:",
        currentMessages.length,
        "workflow:",
        selectedWorkflow?.id,
      );
      await chatApi.fetchChatStream(
        inputText,
        [...refs.current.convoMessages, ...currentMessages],
        conversationId ?? undefined,
        handleStreamEvent,
        handleStreamClose,
        handleStreamError,
        fileData,
        selectedTool,
        toolCategory,
        controller,
        selectedWorkflow,
        selectedCalendarEvent,
        replyToMessage,
        isOnboardingDemo,
      );
    } catch (error) {
      console.error("[useChatStream] Error initiating chat stream:", error);
      if (!streamCloseHandledRef.current) {
        resetStreamState();
      }
    }
  };

  const dispatchPending = () => {
    const pending = pendingStreamArgsRef.current;
    if (pending) {
      pendingStreamArgsRef.current = null;
      setTimeout(() => streamFunction(...pending), 100);
    }
  };

  // Reset all stream refs/state when the SSE closes before any bot message id
  // was assigned — nothing to persist, so just unwind the in-progress turn.
  const handleStreamCloseWithoutMessage = () => {
    console.warn(
      "[handleStreamClose] No bot message ID - resetting state without persistence",
    );
    setIsLoading(false);
    resetLoadingText();
    streamController.clear();
    streamState.endStream();
    streamInProgressRef.current = false;
    refs.current.botMessage = null;
    refs.current.currentStreamingMessages = [];
    refs.current.newConversation = { id: null, description: null };
    useChatStore.getState().setStreamingConversationId(null);
    // Keep the composer locked if a message is queued (it streams next);
    // otherwise this turn is fully done.
    if (!pendingStreamArgsRef.current) {
      useLoadingStore.getState().setMainResponseStreaming(false);
    }
    console.log("[useChatStream] dispatching pending stream after early close");
    dispatchPending();
  };

  // Set the executor-pending bridge BEFORE clearing isLoading so the loading
  // indicator never drops between SSE close and the result message arriving.
  const markExecutorPending = (conversationId: string) => {
    useChatStore.getState().setExecutorPendingConversationId(conversationId);
    setTimeout(() => {
      const store = useChatStore.getState();
      if (store.executorPendingConversationId === conversationId) {
        store.setExecutorPendingConversationId(null);
      }
    }, EXECUTOR_RESULT_TIMEOUT_MS);
  };

  const handleStreamClose = async () => {
    console.log("[useChatStream] handleStreamClose called");
    if (streamCloseHandledRef.current) return;
    streamCloseHandledRef.current = true;

    try {
      if (!refs.current.botMessage?.message_id) {
        handleStreamCloseWithoutMessage();
        return;
      }

      updateBotMessage({ loading: false });

      // A turn that delegated to a background executor (tool_category "executor")
      // delivers its real answer later via a `conversation.new_message` event.
      // Keep the turn visually "in progress" until that arrives.
      const delegatedToExecutor =
        refs.current.botMessage?.tool_data?.some(
          (e) => (e as { tool_category?: string }).tool_category === "executor",
        ) ?? false;

      const conversationId = resolveConversationId();

      if (delegatedToExecutor && conversationId) {
        markExecutorPending(conversationId);
      }
      // NB: a later non-delegating turn must NOT clear executorPending here — an
      // earlier message's background executor may still be running. It is cleared
      // only when its result message arrives (useBgMessageWebSocket), on
      // abort/reset, or by the safety timeout above.

      if (persistTimerRef.current) {
        clearTimeout(persistTimerRef.current);
        persistTimerRef.current = null;
      }
      if (refs.current.botMessage?.message_id && conversationId) {
        updateBotMessageInStore(conversationId);
      }

      setIsLoading(false);
      // Keep the last tool context on screen while the executor result is pending.
      if (!delegatedToExecutor) resetLoadingText();
      streamController.clear();

      console.log("[handleStreamClose] Persisting bot message:", {
        hasConversationId: !!conversationId,
        conversationId,
        botMessageId: refs.current.botMessage.message_id,
        responseLength: refs.current.accumulatedResponse.length,
      });

      if (conversationId) {
        try {
          const finalMessage = createIMessage(
            refs.current.botMessage.message_id,
            conversationId,
            refs.current.accumulatedResponse,
            "assistant",
            "sent",
            refs.current.botMessage,
          );

          await db.putMessage(finalMessage);
          console.log(
            "[handleStreamClose] Bot message persisted successfully:",
            finalMessage.id,
          );

          await db.updateConversationFields(conversationId, {
            updatedAt: new Date(),
          });
        } catch (error) {
          console.error("Failed to persist final message:", error);
        }
      } else {
        console.warn(
          "[handleStreamClose] No conversation ID - message not persisted!",
        );
      }

      console.debug(
        "[handleStreamClose] All persistence done, ending stream state now",
      );
      streamState.endStream();

      streamInProgressRef.current = false;
      refs.current.botMessage = null;
      refs.current.currentStreamingMessages = [];
      refs.current.newConversation = { id: null, description: null };

      useChatStore.getState().setStreamingConversationId(null);

      // Keep the composer locked if a message is queued (it streams next);
      // otherwise this turn is fully done. (Normal turns already cleared this at
      // main_response_complete — this covers turns that closed without one.)
      if (!pendingStreamArgsRef.current) {
        useLoadingStore.getState().setMainResponseStreaming(false);
      }

      console.log(
        "[useChatStream] dispatching pending stream after stream close",
      );
      dispatchPending();
    } catch (error) {
      console.error("Error handling stream close:", error);
      streamState.endStream();
      resetStreamState();
      console.log(
        "[useChatStream] dispatching pending stream after stream error",
      );
      dispatchPending();
    }
  };

  const handleStreamError = (error: Error) => {
    console.error(
      "[useChatStream] handleStreamError:",
      error.name,
      error.message,
    );
    resetStreamState();

    if (error.name !== "AbortError") {
      toast.error(
        error.message || "An error occurred while processing your message",
      );

      if (refs.current.userPrompt) {
        useComposerStore.getState().setInputText(refs.current.userPrompt);
      }
    }
  };

  return streamFunction;
};

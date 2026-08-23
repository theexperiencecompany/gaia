import type { ToolDataEntry } from "@gaia/shared/chat";
import {
  mergeToolOutputIntoToolData,
  upsertApprovalToolData,
} from "@gaia/shared/chat";
import type { FlashListRef } from "@shopify/flash-list";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { chatDb } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chat-store";
import { chatApi, fetchChatStream, type Message } from "../api/chat-api";
import { chatKeys, useConversationQuery } from "../api/queries";
import type { AttachmentFile } from "../components/composer/attachment-preview";
import type { Conversation, ReplyToMessageData } from "../types";

const EMPTY_MESSAGES: Message[] = [];

/** Delay (ms) before re-fetching conversation after a turn ends or is cancelled. */
const POST_TURN_SYNC_DELAY_MS = 1500;

export type { Message } from "../api/chat-api";

interface UseChatOptions {
  onNavigate?: (conversationId: string) => void;
}

export interface SendMessageOptions {
  replyToMessage?: ReplyToMessageData | null;
  selectedTool?: string | null;
  toolCategory?: string | null;
  selectedWorkflow?: { id: string; name: string } | null;
  attachments?: AttachmentFile[];
}

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  isLoading: boolean;
  progress: string | null;
  progressToolName: string | null;
  conversationId: string | null;
  flatListRef: React.RefObject<FlashListRef<Message> | null>;
  sendMessage: (text: string, opts?: SendMessageOptions) => Promise<void>;
  /**
   * Re-run a failed turn, preserving its original send options. Only the most
   * recent assistant message — the one the request is bound to — is retryable.
   */
  retryMessage: (failedMessageId: string) => void;
  cancelStream: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(
  chatId: string | null,
  options?: UseChatOptions,
): UseChatReturn {
  const flatListRef = useRef<FlashListRef<Message>>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamIdRef = useRef<string | null>(null);
  const streamingResponseRef = useRef<string>("");
  const streamingToolDataRef = useRef<ToolDataEntry[]>([]);
  /**
   * Settle function for the in-flight turn. Every terminal path (done, error,
   * user cancel) funnels through it and only the first call wins — this is
   * what prevents the old double-finalize races where an abort triggered
   * onClose → onDone and re-persisted a half-finished response.
   */
  const settleRef = useRef<
    ((cause: "done" | "error" | "aborted") => void) | null
  >(null);
  const lastRequestRef = useRef<{
    text: string;
    opts: SendMessageOptions;
    /** Assistant message this request produced (temp id until server assigns). */
    assistantMessageId: string;
  } | null>(null);
  const queryClient = useQueryClient();

  const storeActiveChatId = useChatStore((state) => state.activeChatId);
  const effectiveChatId = chatId ?? storeActiveChatId;

  const activeConvIdRef = useRef<string | null>(effectiveChatId);
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(effectiveChatId);

  useEffect(() => {
    const newEffectiveId = chatId ?? storeActiveChatId;
    if (newEffectiveId === null) {
      // Reset to null when starting a new chat
      setCurrentConversationId(null);
      activeConvIdRef.current = null;
    } else if (!newEffectiveId.startsWith("temp-")) {
      setCurrentConversationId(newEffectiveId);
      activeConvIdRef.current = newEffectiveId;
    }
  }, [chatId, storeActiveChatId]);

  // When a conversation is opened, eagerly seed the React Query cache from
  // AsyncStorage so the UI renders instantly before the network fetch resolves.
  // This does NOT touch Zustand — streaming messages still take priority.
  useEffect(() => {
    if (!currentConversationId || currentConversationId.startsWith("temp-")) {
      return;
    }

    const cacheKey = chatKeys.messages(currentConversationId);
    // Only seed if React Query has no data yet for this conversation
    if (queryClient.getQueryData(cacheKey) !== undefined) return;

    chatDb.getMessages(currentConversationId).then((persisted) => {
      if (persisted.length > 0) {
        // setQueryData without overwriting if a fetch already completed
        queryClient.setQueryData(
          cacheKey,
          (existing: Message[] | undefined) => existing ?? persisted,
        );
      }
    });
  }, [currentConversationId, queryClient]);

  const {
    data: cachedMessages,
    isLoading,
    refetch: refetchQuery,
  } = useConversationQuery(currentConversationId);

  const streamingMessages = useChatStore(
    useShallow((state) =>
      currentConversationId
        ? (state.messagesByConversation[currentConversationId] ?? null)
        : null,
    ),
  );

  const messages = streamingMessages ?? cachedMessages ?? EMPTY_MESSAGES;

  const streamingState = useChatStore(
    useShallow((state) => state.streamingState),
  );

  const isTyping =
    streamingState.isTyping &&
    streamingState.conversationId === currentConversationId;

  const progress =
    streamingState.conversationId === currentConversationId
      ? streamingState.progress
      : null;

  const progressToolName =
    streamingState.conversationId === currentConversationId
      ? streamingState.progressToolName
      : null;

  useEffect(() => {
    if (cachedMessages && cachedMessages.length > 0 && currentConversationId) {
      chatApi.markConversationAsRead(currentConversationId);
    }
  }, [cachedMessages, currentConversationId]);

  const scrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToEnd({ animated: true });
  }, []);

  /** Reconcile the optimistic local state against server truth shortly after a turn ends. */
  const scheduleReconcile = useCallback(
    (conversationId: string) => {
      if (conversationId.startsWith("temp-")) return;
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: chatKeys.messages(conversationId),
        });
        queryClient.invalidateQueries({
          queryKey: chatKeys.conversations(),
        });
      }, POST_TURN_SYNC_DELAY_MS);
    },
    [queryClient],
  );

  const cancelStream = useCallback(() => {
    // Settle as "aborted" FIRST so the SSE close that the abort triggers can't
    // run onDone afterwards and persist the partial response as final.
    settleRef.current?.("aborted");
    settleRef.current = null;

    abortControllerRef.current?.abort();
    abortControllerRef.current = null;

    // Notify the backend so it can stop processing. Fire-and-forget.
    const streamId = streamIdRef.current;
    if (streamId) {
      chatApi.cancelStream(streamId).catch(() => {
        // Ignore — backend may already be done.
      });
      streamIdRef.current = null;
    }

    useChatStore.getState().setStreamingState({
      isStreaming: false,
      isTyping: false,
      conversationId: null,
      progress: null,
      progressToolName: null,
    });

    // Pull server truth: the backend persists whatever it produced before the
    // cancel arrived, and that partial answer should survive.
    const convId = activeConvIdRef.current;
    if (convId && !convId.startsWith("temp-")) {
      scheduleReconcile(convId);
    }
  }, [queryClient, scheduleReconcile]);

  const sendMessage = useCallback(
    async (text: string, opts?: SendMessageOptions) => {
      cancelStream();
      const store = useChatStore.getState();

      const replyToMessage = opts?.replyToMessage ?? null;
      const selectedTool = opts?.selectedTool ?? null;
      const toolCategory = opts?.toolCategory ?? null;
      const selectedWorkflow = opts?.selectedWorkflow ?? null;
      const attachments = opts?.attachments ?? [];

      const userMessage: Message = {
        id: `temp-user-${Date.now()}`,
        text,
        isUser: true,
        timestamp: new Date(),
        replyToMessage: replyToMessage ?? undefined,
      };

      const aiMessage: Message = {
        id: `temp-ai-${Date.now()}`,
        text: "",
        isUser: false,
        timestamp: new Date(),
      };

      lastRequestRef.current = {
        text,
        opts: {
          replyToMessage,
          selectedTool,
          toolCategory,
          selectedWorkflow,
          attachments,
        },
        assistantMessageId: aiMessage.id,
      };

      const uploadedFileIds = attachments
        .filter((a) => a.fileId)
        .map((a) => a.fileId as string);
      const uploadedFileData = attachments
        .filter((a) => a.fileId)
        .map((a) => ({
          fileId: a.fileId as string,
          fileName: a.name,
          contentType: a.mimeType,
          fileSize: a.size,
        }));

      const storeKey = activeConvIdRef.current || `temp-${Date.now()}`;
      activeConvIdRef.current = storeKey;

      if (!currentConversationId) {
        setCurrentConversationId(storeKey);
      }

      const existingMessages =
        store.messagesByConversation[storeKey] ??
        cachedMessages ??
        EMPTY_MESSAGES;

      store.setMessages(storeKey, [
        ...existingMessages,
        userMessage,
        aiMessage,
      ]);
      store.setStreamingState({
        isTyping: true,
        isStreaming: true,
        conversationId: storeKey,
      });
      streamingResponseRef.current = "";
      streamingToolDataRef.current = [];
      streamIdRef.current = null;

      // --- Single-settle turn finalization --------------------------------
      // Exactly one of done / error / aborted ever runs. The SSE layer can
      // fire multiple terminal signals (error then close, abort then close);
      // without this guard each of them re-persisted state and raced the
      // reconcile refetch.
      let settled: "done" | "error" | "aborted" | null = null;
      const settle = (cause: "done" | "error" | "aborted") => {
        if (settled) return;
        settled = cause;
        settleRef.current = null;

        const finalConvId = activeConvIdRef.current;
        const liveStore = useChatStore.getState();

        if (cause === "aborted") {
          // cancelStream owns the aborted path (state reset + refetch).
          return;
        }

        streamIdRef.current = null;
        abortControllerRef.current = null;

        const finalMessages = finalConvId
          ? liveStore.messagesByConversation[finalConvId]
          : undefined;

        if (finalMessages && finalConvId) {
          // Update React Query cache so the UI picks up the final messages
          queryClient.setQueryData(
            chatKeys.messages(finalConvId),
            finalMessages,
          );

          // Persist to AsyncStorage so messages survive app restarts
          chatDb.saveMessages(finalConvId, finalMessages).catch((err) => {
            console.warn(
              "[use-chat] Failed to persist messages on stream end:",
              err,
            );
          });

          liveStore.clearMessages(finalConvId);
        }

        liveStore.setStreamingState({
          isTyping: false,
          isStreaming: false,
          conversationId: null,
          progress: null,
          progressToolName: null,
        });

        if (finalConvId) {
          // The local accumulator is an approximation of what the server
          // persisted (tool outputs, memory data, real timestamps). Always
          // reconcile against server truth shortly after the turn ends.
          scheduleReconcile(finalConvId);
        }
      };
      settleRef.current = settle;

      try {
        const existingConvId = activeConvIdRef.current;
        const apiConversationId =
          existingConvId && !existingConvId.startsWith("temp-")
            ? existingConvId
            : null;

        const controller = await fetchChatStream(
          {
            message: text,
            conversationId: apiConversationId,
            messages: [...existingMessages, userMessage],
            fileIds: uploadedFileIds,
            fileData: uploadedFileData,
            selectedTool,
            toolCategory,
            workflowId: selectedWorkflow?.id ?? null,
            replyToMessage: replyToMessage ?? null,
          },
          {
            onStreamId: (id) => {
              streamIdRef.current = id;
            },
            onConversationCreated: (
              newConvId,
              userMsgId,
              botMsgId,
              description,
            ) => {
              const liveStore = useChatStore.getState();
              const msgs = liveStore.messagesByConversation[storeKey] || [];

              const updatedMsgs = msgs.map((msg, idx) => {
                if (idx === msgs.length - 2) return { ...msg, id: userMsgId };
                if (idx === msgs.length - 1) return { ...msg, id: botMsgId };
                return msg;
              });

              if (!chatId && newConvId) {
                liveStore.setMessages(newConvId, updatedMsgs);
                liveStore.clearMessages(storeKey);
                liveStore.setStreamingState({ conversationId: newConvId });
                liveStore.setActiveChatId(newConvId);

                // The server-assigned bot id replaces our temp id — keep the
                // retry binding pointing at the real message.
                if (lastRequestRef.current) {
                  lastRequestRef.current = {
                    ...lastRequestRef.current,
                    assistantMessageId: botMsgId,
                  };
                }

                // Show the new conversation in the sidebar immediately by
                // prepending to the React Query cache (the sidebar's single
                // source of truth); the background refetch confirms it.
                queryClient.setQueryData(
                  chatKeys.conversations(),
                  (prev: Conversation[] | undefined) => {
                    if (!prev) return prev;
                    if (prev.some((c) => c.id === newConvId)) return prev;
                    const now = new Date().toISOString();
                    const entry = {
                      id: newConvId,
                      title: description || "New conversation",
                      created_at: now,
                      updated_at: now,
                    };
                    return [entry, ...prev];
                  },
                );

                activeConvIdRef.current = newConvId;
                setCurrentConversationId(newConvId);
                options?.onNavigate?.(newConvId);
              } else {
                liveStore.setMessages(storeKey, updatedMsgs);
              }
            },
            onChunk: (chunk) => {
              streamingResponseRef.current += chunk;
              useChatStore
                .getState()
                .updateLastMessage(
                  activeConvIdRef.current!,
                  streamingResponseRef.current,
                );
            },
            onProgress: (message, toolName) => {
              useChatStore.getState().setStreamingState({
                progress: message,
                progressToolName: toolName ?? null,
              });
            },
            onFollowUpActions: (actions) => {
              useChatStore
                .getState()
                .updateLastMessageFollowUp(activeConvIdRef.current!, actions);
            },
            onToolData: (entry) => {
              // A HIL approval frame replaces the prior frame for its
              // approval_id in place; every other entry is appended.
              streamingToolDataRef.current = upsertApprovalToolData(
                streamingToolDataRef.current,
                entry,
              );
              // Keep the last AI message in sync with accumulated tool data
              // so tool cards render live during streaming.
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  toolData: streamingToolDataRef.current,
                });
            },
            onToolOutput: (output) => {
              // Backend streams the tool result on a separate event keyed
              // by tool_call_id; merge it into the matching tool_data entry
              // (web parity, mirrors useChatStream.handleToolOutput).
              streamingToolDataRef.current = mergeToolOutputIntoToolData(
                streamingToolDataRef.current,
                output,
              );
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  toolData: streamingToolDataRef.current,
                });
            },
            onDone: () => settle("done"),
            onTransportClosed: () => {
              // Transport died before the backend's done event — the answer
              // is truncated. Keep the partial text, mark retryable.
              console.error("Stream closed before completion");
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  error: "Connection lost before the response finished.",
                });
              settle("error");
            },
            onError: (error) => {
              console.error("Stream error:", error);
              // Keep everything streamed so far — only mark the message as
              // failed. Wiping the text (the old behaviour) destroyed the
              // partial answer the user was already reading.
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  error:
                    error.message ||
                    "Something went wrong while generating the response.",
                });
              settle("error");
            },
          },
        );
        abortControllerRef.current = controller;
      } catch (error) {
        console.error("Error starting stream:", error);
        useChatStore
          .getState()
          .updateLastAssistantMessage(activeConvIdRef.current!, {
            error: "Couldn't reach the server. Check your connection.",
          });
        settle("error");
      }
    },
    [
      chatId,
      currentConversationId,
      cancelStream,
      cachedMessages,
      queryClient,
      options,
      scheduleReconcile,
    ],
  );

  const retryMessage = useCallback(
    (failedMessageId: string) => {
      const last = lastRequestRef.current;
      const convId = activeConvIdRef.current;
      if (!last || !convId) return;
      // Only the assistant message this request produced is retryable.
      if (failedMessageId !== last.assistantMessageId) return;

      // Settlement clears the transient store; the finalized messages live in
      // the React Query cache — read from whichever still has them.
      const store = useChatStore.getState();
      const msgs =
        store.messagesByConversation[convId] ??
        queryClient.getQueryData<Message[]>(chatKeys.messages(convId));
      if (!msgs) return;

      // Drop the failed turn entirely, INCLUDING the user message —
      // sendMessage below appends a fresh copy of it.
      let lastUserIdx = -1;
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].isUser) {
          lastUserIdx = i;
          break;
        }
      }
      if (lastUserIdx < 0) return;

      const kept = msgs.slice(0, lastUserIdx);
      store.setMessages(convId, kept);
      if (!convId.startsWith("temp-")) {
        queryClient.setQueryData(chatKeys.messages(convId), kept);
      }

      void sendMessage(last.text, last.opts);
    },
    [sendMessage, queryClient],
  );

  const refetch = useCallback(async () => {
    if (currentConversationId) {
      await refetchQuery();
    }
  }, [currentConversationId, refetchQuery]);

  return {
    messages,
    isTyping,
    isLoading,
    progress,
    progressToolName,
    conversationId: currentConversationId,
    flatListRef,
    sendMessage,
    retryMessage,
    cancelStream,
    scrollToBottom,
    refetch,
  };
}

import {
  extractToolProgressMessage,
  mergeToolOutputIntoToolData,
  upsertTodoProgressToolData,
} from "@gaia/shared/chat";
import type { FlashListRef } from "@shopify/flash-list";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useChatStore } from "@/stores/chat-store";
import {
  type ApiFileData,
  type ApiToolData,
  cancelStream as cancelStreamRequest,
  chatApi,
  fetchChatStream,
  type Message,
  type ReplyToMessageData,
} from "../api/chat-api";
import { chatKeys, useConversationQuery } from "../api/queries";
import type { AttachmentFile } from "../components/composer/attachment-preview";

const EMPTY_MESSAGES: Message[] = [];

export type { Message } from "../api/chat-api";

interface UseChatOptions {
  onNavigate?: (conversationId: string) => void;
}

interface SendMessageOptions {
  replyToMessage?: ReplyToMessageData | null;
  selectedWorkflow?: { id: string; name: string } | null;
  selectedTool?: string | null;
  toolCategory?: string | null;
  attachments?: AttachmentFile[];
}

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  isLoading: boolean;
  progress: string | null;
  progressToolName: string | null;
  conversationId: string | null;
  flatListRef: React.RefObject<FlashListRef<unknown> | null>;
  sendMessage: (text: string, options?: SendMessageOptions) => Promise<void>;
  cancelStream: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(
  chatId: string | null,
  chatOptions?: UseChatOptions,
): UseChatReturn {
  const flatListRef = useRef<FlashListRef<unknown>>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamIdRef = useRef<string | null>(null);
  const streamingResponseRef = useRef<string>("");
  const streamingToolDataRef = useRef<ApiToolData[]>([]);
  const queryClient = useQueryClient();

  const storeActiveChatId = useChatStore((state) => state.activeChatId);
  const effectiveChatId = chatId ?? storeActiveChatId;

  const activeConvIdRef = useRef<string | null>(effectiveChatId);
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(effectiveChatId);

  useEffect(() => {
    if (chatId && storeActiveChatId !== chatId) {
      useChatStore.getState().setActiveChatId(chatId);
    }
  }, [chatId, storeActiveChatId]);

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

  const cancelStream = useCallback(() => {
    abortControllerRef.current?.abort();
    if (streamIdRef.current) {
      cancelStreamRequest(streamIdRef.current);
      streamIdRef.current = null;
    }
    abortControllerRef.current = null;
    useChatStore.getState().setStreamingState({
      isStreaming: false,
      isTyping: false,
      conversationId: null,
      progress: null,
      progressToolName: null,
    });
  }, []);

  const sendMessage = useCallback(
    async (text: string, options?: SendMessageOptions) => {
      const {
        replyToMessage = null,
        selectedWorkflow = null,
        selectedTool = null,
        toolCategory = null,
        attachments = [],
      } = options ?? {};

      cancelStream();
      const store = useChatStore.getState();

      const userMessage: Message = {
        id: `temp-user-${Date.now()}`,
        text,
        isUser: true,
        timestamp: new Date(),
        replyToMessage: replyToMessage ?? null,
      };

      const aiMessage: Message = {
        id: `temp-ai-${Date.now()}`,
        text: "",
        isUser: false,
        timestamp: new Date(),
        toolData: [],
      };

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
        progress: null,
        progressToolName: null,
      });
      streamingResponseRef.current = "";
      streamingToolDataRef.current = [];

      try {
        const existingConvId = activeConvIdRef.current;
        const apiConversationId =
          existingConvId && !existingConvId.startsWith("temp-")
            ? existingConvId
            : null;

        // Upload any pending attachments before streaming
        const uploadedFileData: ApiFileData[] = [];
        if (attachments.length > 0) {
          const uploadResults = await Promise.allSettled(
            attachments.map((att) =>
              chatApi.uploadFile({
                uri: att.uri,
                name: att.name,
                mimeType: att.mimeType,
              }),
            ),
          );

          for (const result of uploadResults) {
            if (result.status === "fulfilled") {
              uploadedFileData.push({
                fileId: result.value.fileId,
                fileName: result.value.fileName,
                fileSize: result.value.fileSize,
                contentType: result.value.contentType,
                url: result.value.url,
              });
            } else {
              console.warn("[useChat] File upload failed:", result.reason);
            }
          }
        }

        const controller = await fetchChatStream(
          {
            message: text,
            conversationId: apiConversationId,
            messages: [...existingMessages, userMessage],
            replyToMessage: replyToMessage ?? null,
            selectedWorkflow: selectedWorkflow ?? null,
            selectedTool: selectedTool ?? null,
            toolCategory: toolCategory ?? null,
            fileData: uploadedFileData,
            fileIds: uploadedFileData.map((f) => f.fileId),
          },
          {
            onConversationCreated: (
              newConvId,
              userMsgId,
              botMsgId,
              description,
            ) => {
              const store = useChatStore.getState();
              const msgs = store.messagesByConversation[storeKey] || [];

              const updatedMsgs = msgs.map((msg, idx) => {
                if (idx === msgs.length - 2) return { ...msg, id: userMsgId };
                if (idx === msgs.length - 1) return { ...msg, id: botMsgId };
                return msg;
              });

              if (!chatId && newConvId) {
                store.setMessages(newConvId, updatedMsgs);
                store.clearMessages(storeKey);
                store.setStreamingState({ conversationId: newConvId });
                store.setActiveChatId(newConvId);

                store.addConversation({
                  id: newConvId,
                  title: description || "New conversation",
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                });

                queryClient.invalidateQueries({
                  queryKey: chatKeys.conversations(),
                });

                activeConvIdRef.current = newConvId;
                setCurrentConversationId(newConvId);
                chatOptions?.onNavigate?.(newConvId);
              } else {
                store.setMessages(storeKey, updatedMsgs);
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
            onToolData: (entry) => {
              const progressMessage = extractToolProgressMessage(entry);
              if (progressMessage) {
                useChatStore
                  .getState()
                  .setStreamingState({ progress: progressMessage });
                return;
              }

              const normalizedEntry: ApiToolData = {
                tool_name: entry.tool_name,
                data:
                  typeof entry.data === "object" && entry.data !== null
                    ? (entry.data as Record<string, unknown>)
                    : { value: entry.data },
                timestamp: entry.timestamp,
              };

              streamingToolDataRef.current = [
                ...streamingToolDataRef.current,
                normalizedEntry,
              ];

              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  toolData: streamingToolDataRef.current,
                });
            },
            onToolOutput: (output) => {
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
            onTodoProgress: (snapshot) => {
              streamingToolDataRef.current = upsertTodoProgressToolData(
                streamingToolDataRef.current,
                snapshot,
              );

              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  toolData: streamingToolDataRef.current,
                });
            },
            onFollowUpActions: (actions) => {
              useChatStore
                .getState()
                .updateLastMessageFollowUp(activeConvIdRef.current!, actions);
            },
            onMainResponseComplete: () => {
              useChatStore.getState().setStreamingState({
                isTyping: false,
                progress: null,
                progressToolName: null,
              });
            },
            onConversationDescription: (description) => {
              const convId = activeConvIdRef.current;
              if (convId && !convId.startsWith("temp-")) {
                useChatStore
                  .getState()
                  .updateConversationTitle(convId, description);
                queryClient.invalidateQueries({
                  queryKey: chatKeys.conversations(),
                });
              }
            },
            onImageData: (data) => {
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  imageData: data,
                });
            },
            onMemoryData: (data) => {
              useChatStore
                .getState()
                .updateLastAssistantMessage(activeConvIdRef.current!, {
                  memoryData: data as Record<string, unknown>,
                });
            },
            onDone: () => {
              const finalConvId = activeConvIdRef.current;
              const store = useChatStore.getState();
              const finalMessages = store.messagesByConversation[finalConvId!];

              if (finalMessages && finalConvId) {
                queryClient.setQueryData(
                  chatKeys.messages(finalConvId),
                  finalMessages,
                );
                store.clearMessages(finalConvId);
              }

              store.setStreamingState({
                isTyping: false,
                isStreaming: false,
                conversationId: null,
                progress: null,
                progressToolName: null,
              });
              abortControllerRef.current = null;
              streamIdRef.current = null;
            },
            onStreamId: (streamId) => {
              streamIdRef.current = streamId;
            },
            onError: (error) => {
              console.error("Stream error:", error);
              useChatStore.getState().setStreamingState({
                isTyping: false,
                isStreaming: false,
                conversationId: null,
                progress: null,
                progressToolName: null,
              });
              useChatStore
                .getState()
                .updateLastMessage(
                  activeConvIdRef.current!,
                  "Sorry, I encountered an error. Please try again.",
                );
              streamIdRef.current = null;
            },
          },
        );
        abortControllerRef.current = controller;
      } catch (error) {
        console.error("Error starting stream:", error);
        useChatStore.getState().setStreamingState({
          isTyping: false,
          isStreaming: false,
          conversationId: null,
          progress: null,
          progressToolName: null,
        });
      }
    },
    [
      chatId,
      currentConversationId,
      cancelStream,
      cachedMessages,
      queryClient,
      chatOptions,
    ],
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
    cancelStream,
    scrollToBottom,
    refetch,
  };
}

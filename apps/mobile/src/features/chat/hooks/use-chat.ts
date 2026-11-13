import type { SelectedWorkflowDataInput } from "@gaia/shared/api/generated";
import { DISPLAY_STATE, withLiveRows } from "@gaia/shared/conversation";
import type { FlashListRef } from "@shopify/flash-list";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { chatDb } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chat-store";
import { chatApi, type Message } from "../api/chat-api";
import {
  chatKeys,
  useChatQueryClient,
  useConversationQuery,
  useConversationsQuery,
} from "../api/queries";
import type { AttachmentFile } from "../components/composer/attachment-preview";
import { useLiveConversation } from "../live/live-conversation-store";
import { retryMessage, sendMessage } from "../live/send-message";
import {
  type LiveLoading,
  useLiveLoading,
  useLiveMessages,
  useOpenConversation,
} from "../live/use-live-chat";
import type { ReplyToMessageData } from "../types";

const EMPTY_MESSAGES: Message[] = [];

export type { Message } from "../api/chat-api";

interface UseChatOptions {
  onNavigate?: (conversationId: string) => void;
}

export interface SendMessageOptions {
  replyToMessage?: ReplyToMessageData | null;
  selectedTool?: string | null;
  toolCategory?: string | null;
  selectedWorkflow?: SelectedWorkflowDataInput | null;
  attachments?: AttachmentFile[];
}

interface UseChatReturn {
  /** The saved history from before the conversation runtime, then the live rows. */
  messages: Message[];
  /** The loading row: GAIA owes the user something. */
  loading: LiveLoading;
  /** GAIA is doing something in this conversation that Stop would end. */
  busy: boolean;
  isLoading: boolean;
  conversationId: string | null;
  flatListRef: React.RefObject<FlashListRef<Message> | null>;
  sendMessage: (text: string, opts?: SendMessageOptions) => void;
  /** Resend a failed send as-is, or send the message behind a reply again with retry_of. */
  retryMessage: (messageId: string) => void;
  stop: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(
  chatId: string | null,
  options?: UseChatOptions,
): UseChatReturn {
  const flatListRef = useRef<FlashListRef<Message>>(null);
  const queryClient = useQueryClient();
  const storeActiveChatId = useChatStore((state) => state.activeChatId);
  const conversationId = chatId ?? storeActiveChatId;

  useOpenConversation(conversationId);

  // Seed the history cache from AsyncStorage so it renders before the fetch resolves.
  useEffect(() => {
    if (!conversationId) return;
    const cacheKey = chatKeys.messages(conversationId);
    if (queryClient.getQueryData(cacheKey) !== undefined) return;
    chatDb.getMessages(conversationId).then((persisted) => {
      if (persisted.length > 0) {
        queryClient.setQueryData(
          cacheKey,
          (existing: Message[] | undefined) => existing ?? persisted,
        );
      }
    });
  }, [conversationId, queryClient]);

  const {
    data: history,
    isLoading,
    refetch: refetchQuery,
  } = useConversationQuery(conversationId);
  const liveRows = useLiveMessages(conversationId);
  const loading = useLiveLoading(conversationId);
  const { view } = useLiveConversation(conversationId);
  const busy = view.display !== DISPLAY_STATE.IDLE;

  const messages = useMemo(() => {
    const saved = history ?? EMPTY_MESSAGES;
    return withLiveRows(saved, liveRows, (message) => message.id);
  }, [history, liveRows]);

  // Opening a conversation the list shows unread reads it, including one that
  // turns unread while it is on screen.
  const { data: conversations } = useConversationsQuery();
  const { updateConversationInCache } = useChatQueryClient();
  const unread =
    conversations?.find((conversation) => conversation.id === conversationId)
      ?.is_unread ?? false;
  useEffect(() => {
    if (!conversationId || !unread) return;
    updateConversationInCache(conversationId, { is_unread: false });
    chatApi.markConversationAsRead(conversationId);
  }, [conversationId, unread, updateConversationInCache]);

  const scrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToEnd({ animated: true });
  }, []);

  const onNavigate = options?.onNavigate;
  const openNewConversation = useCallback(
    (newConversationId: string) => {
      // A new conversation has no saved history: nothing to fetch before its first message lands.
      queryClient.setQueryData(
        chatKeys.messages(newConversationId),
        EMPTY_MESSAGES,
      );
      useChatStore.getState().setActiveChatId(newConversationId);
      onNavigate?.(newConversationId);
    },
    [onNavigate],
  );
  const send = useCallback(
    (text: string, opts?: SendMessageOptions) => {
      const attachments = opts?.attachments ?? [];
      const sentTo = sendMessage(
        conversationId,
        {
          text,
          reply_to_message: opts?.replyToMessage ?? null,
          selected_tool: opts?.selectedTool ?? null,
          tool_category: opts?.toolCategory ?? null,
          selected_workflow: opts?.selectedWorkflow ?? null,
        },
        attachments.flatMap((attachment) =>
          attachment.fileId
            ? [
                {
                  fileId: attachment.fileId,
                  fileName: attachment.name,
                  contentType: attachment.mimeType,
                  fileSize: attachment.size,
                  url: attachment.fileUrl,
                },
              ]
            : [],
        ),
        openNewConversation,
      );
      if (sentTo === conversationId) return;
      openNewConversation(sentTo);
    },
    [conversationId, openNewConversation, queryClient],
  );

  const retry = useCallback(
    (messageId: string) => {
      if (!conversationId) return;
      retryMessage(conversationId, messageId).catch((error: unknown) => {
        console.error("[use-chat] retry failed:", error);
      });
    },
    [conversationId],
  );

  const stop = useCallback(() => {
    if (!conversationId) return;
    chatApi.stopConversation(conversationId).catch((error: unknown) => {
      console.error("[use-chat] stop failed:", error);
    });
  }, [conversationId]);

  const refetch = useCallback(async () => {
    if (conversationId) await refetchQuery();
  }, [conversationId, refetchQuery]);

  return {
    messages,
    loading,
    busy,
    isLoading,
    conversationId,
    flatListRef,
    sendMessage: send,
    retryMessage: retry,
    stop,
    scrollToBottom,
    refetch,
  };
}

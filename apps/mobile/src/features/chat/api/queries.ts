import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation } from "@/features/chat/types";
import { apiService } from "@/lib/api";
import { chatDb } from "@/lib/db/chatDb";
import type { Message } from "./chat-api";
import { chatApi } from "./chat-api";

interface ApiConversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread?: boolean;
  is_starred?: boolean;
  createdAt: string;
  updatedAt?: string;
}

interface ConversationsResponse {
  conversations: ApiConversation[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

function normalizeConversation(apiConv: ApiConversation): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    created_at: apiConv.createdAt,
    updated_at: apiConv.updatedAt || apiConv.createdAt,
    is_unread: apiConv.is_unread,
    is_starred: apiConv.is_starred,
  };
}

async function fetchConversationsList(): Promise<Conversation[]> {
  const data = await apiService.get<ConversationsResponse>(
    "/conversations?page=1&limit=100",
  );
  return (data.conversations || []).map(normalizeConversation);
}

export const chatKeys = {
  all: ["chat"] as const,
  conversations: () => [...chatKeys.all, "conversations"] as const,
  conversation: (id: string) => [...chatKeys.all, "conversation", id] as const,
  messages: (id: string) => [...chatKeys.all, "messages", id] as const,
};

const MESSAGE_CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

async function fetchMessagesWithCache(
  conversationId: string,
): Promise<Message[]> {
  // Check AsyncStorage first — if we have recent messages, return them
  // immediately and avoid an API round-trip.
  const cachedTimestamp = await chatDb.getMessagesTimestamp(conversationId);
  const isCacheValid =
    cachedTimestamp !== null &&
    Date.now() - cachedTimestamp < MESSAGE_CACHE_TTL_MS;

  if (isCacheValid) {
    const cached = await chatDb.getMessages(conversationId);
    if (cached.length > 0) {
      return cached;
    }
  }

  // Cache miss or expired — fetch from API and persist to AsyncStorage.
  const messages = await chatApi.fetchMessages(conversationId);
  if (messages.length > 0) {
    chatDb.saveMessages(conversationId, messages).catch((err) => {
      console.warn(
        "[queries] Failed to persist messages to AsyncStorage:",
        err,
      );
    });
  }
  return messages;
}

export function useConversationQuery(conversationId: string | null) {
  return useQuery({
    queryKey: chatKeys.messages(conversationId!),
    queryFn: () => fetchMessagesWithCache(conversationId!),
    enabled: !!conversationId && !conversationId.startsWith("temp-"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useConversationsQuery() {
  return useQuery({
    queryKey: chatKeys.conversations(),
    queryFn: fetchConversationsList,
    staleTime: 2 * 60 * 1000,
  });
}

export function useChatQueryClient() {
  const queryClient = useQueryClient();

  const setMessagesCache = (conversationId: string, messages: Message[]) => {
    queryClient.setQueryData(chatKeys.messages(conversationId), messages);
  };

  const invalidateConversations = () => {
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  const invalidateMessages = (conversationId: string) => {
    queryClient.invalidateQueries({
      queryKey: chatKeys.messages(conversationId),
    });
  };

  const prefetchMessages = async (conversationId: string) => {
    await queryClient.prefetchQuery({
      queryKey: chatKeys.messages(conversationId),
      queryFn: () => chatApi.fetchMessages(conversationId),
      staleTime: 5 * 60 * 1000,
    });
  };

  const updateConversationInCache = (
    conversationId: string,
    updates: Partial<Conversation>,
  ) => {
    queryClient.setQueryData<Conversation[]>(
      chatKeys.conversations(),
      (prev) => {
        if (!prev) return prev;
        return prev.map((c) =>
          c.id === conversationId ? { ...c, ...updates } : c,
        );
      },
    );
  };

  return {
    setMessagesCache,
    invalidateConversations,
    invalidateMessages,
    prefetchMessages,
    updateConversationInCache,
  };
}

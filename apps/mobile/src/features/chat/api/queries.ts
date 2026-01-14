import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation } from "@/features/chat/types";
import { apiService } from "@/lib/api";
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

export function useConversationQuery(conversationId: string | null) {
  return useQuery({
    queryKey: chatKeys.messages(conversationId!),
    queryFn: () => chatApi.fetchMessages(conversationId!),
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

  return {
    setMessagesCache,
    invalidateConversations,
    invalidateMessages,
    prefetchMessages,
  };
}

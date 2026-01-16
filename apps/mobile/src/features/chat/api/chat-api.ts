import { apiService } from "@/lib/api";

export interface ApiFileData {
  fileId: string;
  fileName?: string;
  fileSize?: number;
  contentType?: string;
  url?: string;
}

export interface ApiToolData {
  tool_name: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface ApiMessage {
  type: "user" | "bot";
  response: string;
  date: string;
  message_id: string;
  fileIds: string[];
  fileData: ApiFileData[];
  tool_data?: ApiToolData[];
  metadata?: Record<string, unknown>;
}

export interface ApiConversationDetail {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread: boolean;
  messages: ApiMessage[];
  createdAt: string;
  updatedAt?: string;
}

export interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: Date;
  fileIds?: string[];
  fileData?: ApiFileData[];
  toolData?: ApiToolData[];
  followUpActions?: string[];
  metadata?: Record<string, unknown>;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
  isUnread: boolean;
}

function normalizeMessage(apiMsg: ApiMessage): Message {
  return {
    id: apiMsg.message_id,
    text: apiMsg.response,
    isUser: apiMsg.type === "user",
    timestamp: new Date(apiMsg.date),
    fileIds: apiMsg.fileIds,
    fileData: apiMsg.fileData,
    toolData: apiMsg.tool_data,
    metadata: apiMsg.metadata,
  };
}

function normalizeConversationDetail(
  apiConv: ApiConversationDetail,
): ConversationDetail {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    messages: apiConv.messages.map(normalizeMessage),
    createdAt: new Date(apiConv.createdAt),
    updatedAt: new Date(apiConv.updatedAt || apiConv.createdAt),
    isUnread: apiConv.is_unread,
  };
}

export async function fetchConversation(
  conversationId: string,
): Promise<ConversationDetail | null> {
  try {
    const response = await apiService.get<ApiConversationDetail>(
      `/conversations/${conversationId}`,
    );
    return normalizeConversationDetail(response);
  } catch (error) {
    console.error("Error fetching conversation:", error);
    return null;
  }
}

export async function fetchMessages(
  conversationId: string,
): Promise<Message[]> {
  try {
    const conversation = await fetchConversation(conversationId);
    return conversation?.messages || [];
  } catch (error) {
    console.error("Error fetching messages:", error);
    return [];
  }
}

export async function markConversationAsRead(
  conversationId: string,
): Promise<boolean> {
  try {
    await apiService.patch(`/conversations/${conversationId}/read`, {});
    return true;
  } catch (error) {
    console.error("Error marking conversation as read:", error);
    return false;
  }
}

export async function deleteConversation(
  conversationId: string,
): Promise<boolean> {
  try {
    await apiService.delete(`/conversations/${conversationId}`);
    return true;
  } catch (error) {
    console.error("Error deleting conversation:", error);
    return false;
  }
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<boolean> {
  try {
    await apiService.put(`/conversations/${conversationId}/description`, {
      description: title,
    });
    return true;
  } catch (error) {
    console.error("Error renaming conversation:", error);
    return false;
  }
}

export async function toggleStarConversation(
  conversationId: string,
  starred: boolean,
): Promise<boolean> {
  try {
    await apiService.put(`/conversations/${conversationId}/star`, { starred });
    return true;
  } catch (error) {
    console.error("Error starring conversation:", error);
    return false;
  }
}

export const chatApi = {
  fetchConversation,
  fetchMessages,
  markConversationAsRead,
  deleteConversation,
  renameConversation,
  toggleStarConversation,
};

export * from "./chat-stream";

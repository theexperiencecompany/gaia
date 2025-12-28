/**
 * Chat API Service
 * Handles all chat-related API calls
 */

import { apiService } from "@/lib/api";

// =============================================================================
// Types - API Response Types
// =============================================================================

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

// =============================================================================
// Types - Normalized App Types
// =============================================================================

export interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: Date;
  fileIds?: string[];
  fileData?: ApiFileData[];
  toolData?: ApiToolData[];
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

// =============================================================================
// Transformers
// =============================================================================

/**
 * Transform API message to app message format
 */
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

/**
 * Transform API conversation to app conversation format
 */
function normalizeConversationDetail(
  apiConv: ApiConversationDetail
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

// =============================================================================
// API Functions
// =============================================================================

/**
 * Create a new conversation
 */
export async function createConversation(
  description: string = "New Chat"
): Promise<{ conversation_id: string } | null> {
  try {
    // Generate a unique conversation ID
    const conversationId = `conv-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    
    const response = await apiService.post<{ conversation_id: string }>(
      "/conversations",
      {
        conversation_id: conversationId,
        description,
        is_system_generated: false,
        is_unread: false,
      }
    );
    return response;
  } catch (error) {
    console.error("Error creating conversation:", error);
    return null;
  }
}

/**
 * Fetch a single conversation with all its messages
 */
export async function fetchConversation(
  conversationId: string
): Promise<ConversationDetail | null> {
  try {
    const response = await apiService.get<ApiConversationDetail>(
      `/conversations/${conversationId}`
    );
    return normalizeConversationDetail(response);
  } catch (error) {
    console.error("Error fetching conversation:", error);
    return null;
  }
}

/**
 * Fetch messages for a conversation
 */
export async function fetchMessages(
  conversationId: string
): Promise<Message[]> {
  try {
    const conversation = await fetchConversation(conversationId);
    return conversation?.messages || [];
  } catch (error) {
    console.error("Error fetching messages:", error);
    return [];
  }
}

/**
 * Mark conversation as read
 */
export async function markConversationAsRead(
  conversationId: string
): Promise<boolean> {
  try {
    await apiService.patch(`/conversations/${conversationId}/read`, {});
    return true;
  } catch (error) {
    console.error("Error marking conversation as read:", error);
    return false;
  }
}

/**
 * Delete a conversation
 */
export async function deleteConversation(
  conversationId: string
): Promise<boolean> {
  try {
    await apiService.delete(`/conversations/${conversationId}`);
    return true;
  } catch (error) {
    console.error("Error deleting conversation:", error);
    return false;
  }
}

/**
 * Rename a conversation
 */
export async function renameConversation(
  conversationId: string,
  title: string
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

/**
 * Star/unstar a conversation
 */
export async function toggleStarConversation(
  conversationId: string,
  starred: boolean
): Promise<boolean> {
  try {
    await apiService.put(`/conversations/${conversationId}/star`, { starred });
    return true;
  } catch (error) {
    console.error("Error starring conversation:", error);
    return false;
  }
}

// =============================================================================
// Export as object for consistency
// =============================================================================

export const chatApi = {
  fetchConversation,
  fetchMessages,
  markConversationAsRead,
  deleteConversation,
  renameConversation,
  toggleStarConversation,
};

// Re-export streaming API
export * from "./chat-stream";

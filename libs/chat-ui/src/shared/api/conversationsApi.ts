/**
 * Shared conversations/chat API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

export const CONVERSATION_ENDPOINTS = {
  list: "/conversations",
  get: (conversationId: string) => `/conversations/${conversationId}`,
  delete: (conversationId: string) => `/conversations/${conversationId}`,
  deleteAll: "/conversations",
  rename: (conversationId: string) =>
    `/conversations/${conversationId}/description`,
  star: (conversationId: string) => `/conversations/${conversationId}/star`,
  markAsRead: (conversationId: string) =>
    `/conversations/${conversationId}/read`,
  markAsUnread: (conversationId: string) =>
    `/conversations/${conversationId}/unread`,
  pinMessage: (conversationId: string, messageId: string) =>
    `/conversations/${conversationId}/messages/${messageId}/pin`,
  batchSync: "/conversations/batch-sync",
  upload: "/upload",
  generateImage: "/image/generate",
  chatStream: "chat-stream",
} as const;

export interface ConversationListParams {
  page?: number;
  limit?: number;
}

export interface ConversationSyncItem {
  conversation_id: string;
  last_updated?: string;
}

export interface BatchSyncConversationsParams {
  conversations: ConversationSyncItem[];
}

export interface RenameConversationParams {
  description: string;
}

export interface StarConversationParams {
  starred: boolean;
}

export interface PinMessageParams {
  pinned: boolean;
}

export interface GenerateImageParams {
  message: string;
}

export interface ChatStreamFileData {
  fileId: string;
  name?: string;
  url?: string;
  type?: string;
  size?: number;
  mimeType?: string;
}

export interface ChatStreamReplyTo {
  id: string;
  content: string;
  role: "user" | "assistant";
}

export interface ChatStreamMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatStreamParams {
  conversation_id: string | null;
  message: string;
  fileIds?: string[];
  fileData?: ChatStreamFileData[];
  selectedTool?: string | null;
  toolCategory?: string | null;
  selectedWorkflow?: Record<string, unknown> | null;
  selectedCalendarEvent?: Record<string, unknown> | null;
  replyToMessage?: ChatStreamReplyTo | null;
  messages?: ChatStreamMessage[];
}

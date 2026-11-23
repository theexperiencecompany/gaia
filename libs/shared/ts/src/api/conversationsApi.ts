/**
 * Shared conversations/chat API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

import type { ConversationSyncItem } from "./generated";

export type { ConversationSyncItem } from "./generated";

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
} as const;

export interface ConversationListParams {
  page?: number;
  limit?: number;
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

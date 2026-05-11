/**
 * Pure types extracted from chatApi.ts. Lives in libs/chat-ui as the
 * canonical source so both apps/web's runtime impl and chat-ui's stubs
 * import from one place — no drift.
 */
import type { MessageType } from "./convoTypes";

export interface FileUploadResponse {
  fileId: string;
  fileName: string;
  fileSize: number;
  contentType: string;
  url?: string;
  description?: string;
  message?: string;
}

export interface GenerateImageResponse {
  url: string;
  improved_prompt?: string;
}

export enum SystemPurpose {
  EMAIL_PROCESSING = "email_processing",
  WORKFLOW_EXECUTION = "workflow_execution",
  OTHER = "other",
}

export enum ConversationSource {
  WEB = "web",
  MOBILE = "mobile",
  TELEGRAM = "telegram",
  DISCORD = "discord",
  SLACK = "slack",
  WHATSAPP = "whatsapp",
  WORKFLOW_SYSTEM = "workflow_system",
}

export interface Conversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  starred?: boolean;
  is_system_generated?: boolean;
  system_purpose?: SystemPurpose;
  is_unread?: boolean;
  source?: ConversationSource;
  createdAt: string;
  updatedAt?: string;
}

export interface ConversationWithMessages {
  id: string;
  title: string;
  messages: MessageType[];
}

export interface FetchConversationsResponse {
  conversations: Conversation[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface ConversationSyncItem {
  conversation_id: string;
  last_updated?: string;
}

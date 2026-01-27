export type {
  ApiFileData,
  ApiToolData,
  Message,
} from "@/features/chat/api/chat-api";

import type { Message } from "@/features/chat/api/chat-api";

export interface ChatSession {
  id: string;
  title: string;
  lastMessage?: string;
  timestamp: Date;
}

export interface ChatState {
  messages: Message[];
  isTyping: boolean;
  activeSessionId?: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  is_starred?: boolean;
  is_unread?: boolean;
}

export interface GroupedConversations {
  starred: Conversation[];
  today: Conversation[];
  yesterday: Conversation[];
  lastWeek: Conversation[];
  previousChats: Conversation[];
}

export interface Suggestion {
  id: string;
  iconUrl: string;
  text: string;
}

export interface AIModel {
  id: string;
  name: string;
  provider: string;
  icon: string;
  isPro?: boolean;
  isDefault?: boolean;
}

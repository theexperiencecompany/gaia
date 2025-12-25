// Re-export Message from chat-api for backwards compatibility
export type { Message } from "@/features/chat/api/chat-api";

import type { Message } from "@/features/chat/api/chat-api";

export interface ChatSession {
  id: string;
  title: string;
  lastMessage?: string;
  timestamp: Date;
}

export interface Suggestion {
  id: string;
  iconUrl: string;
  text: string;
}

export interface ChatState {
  messages: Message[];
  isTyping: boolean;
  activeSessionId?: string;
}

export interface AIModel {
  id: string;
  name: string;
  provider: string;
  icon: string;
  isPro?: boolean;
  isDefault?: boolean;
}


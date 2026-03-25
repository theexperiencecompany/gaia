export type SearchMode = "messages" | "conversations" | "notes" | "all";

export interface SearchConversationResult {
  conversation_id: string;
  description: string;
  snippet?: string;
}

export interface SearchMessageResult {
  conversation_id: string;
  message_id: string;
  snippet: string;
  timestamp?: string;
}

export interface SearchNoteResult {
  id: string;
  snippet: string;
  title?: string;
}

export interface SearchResult {
  type: SearchMode;
  data: SearchConversationResult | SearchMessageResult | SearchNoteResult;
}

export interface SearchParams {
  query: string;
  limit?: number;
  offset?: number;
  conversationId?: string;
  type?: SearchMode;
}

export interface SearchResponse {
  conversations: SearchConversationResult[];
  messages: SearchMessageResult[];
  notes: SearchNoteResult[];
}

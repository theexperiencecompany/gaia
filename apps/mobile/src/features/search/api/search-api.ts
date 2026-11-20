import type { MessageSearchResult } from "@gaia/shared/api/generated";
import { apiService } from "@/lib/api";

export interface SearchConversationResult {
  conversation_id: string;
  description: string;
}

export type SearchMessageResult = MessageSearchResult;

export interface SearchNoteResult {
  id: string;
  snippet: string;
}

export interface SearchResponse {
  conversations: SearchConversationResult[];
  messages: SearchMessageResult[];
  notes: SearchNoteResult[];
}

export const searchConversations = (query: string) =>
  apiService.get<SearchResponse>(
    `/search?q=${encodeURIComponent(query)}&type=conversations`,
  );

export const searchMessages = (query: string) =>
  apiService.get<SearchResponse>(
    `/search?q=${encodeURIComponent(query)}&type=messages`,
  );

export const search = (query: string) =>
  apiService.get<SearchResponse>(`/search?query=${encodeURIComponent(query)}`);

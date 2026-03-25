import type {
  SearchConversationResult,
  SearchMessageResult,
  SearchMode,
  SearchNoteResult,
  SearchParams,
  SearchResponse,
} from "../types/search";
import { buildQueryString } from "./queryBuilder";

export const SearchApiEndpoints = {
  search: "/search",
} as const;

export type SearchApiEndpoints = typeof SearchApiEndpoints;

export interface SearchApi {
  search(params: SearchParams): Promise<SearchResponse>;
  searchMessages(query: string): Promise<SearchMessageResult[]>;
  searchConversations(query: string): Promise<SearchConversationResult[]>;
  searchNotes(query: string): Promise<SearchNoteResult[]>;
}

export function buildSearchQuery(params: SearchParams): string {
  const filters: Record<string, string | number | boolean | undefined | null> =
    {
      query: params.query,
      limit: params.limit,
      offset: params.offset,
      conversation_id: params.conversationId,
      type: params.type,
    };

  return `${SearchApiEndpoints.search}${buildQueryString(filters)}`;
}

export type { SearchMode };

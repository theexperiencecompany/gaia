import { apiService } from "@/lib/api/service";

export interface SearchMessageResult {
  conversation_id: string;
  message: {
    message_id: string;
    type: "bot" | "user";
    date: string;
  };
  snippet: string;
}

export interface SearchConversationResult {
  conversation_id: string;
  description: string;
}

export interface SearchNoteResult {
  id: string;
  snippet: string;
}

export interface ComprehensiveSearchResponse {
  conversations: SearchConversationResult[];
  messages: SearchMessageResult[];
  notes: SearchNoteResult[];
}

export const searchApi = {
  /** Comprehensive search over conversations, messages, and notes. */
  search: async (query: string): Promise<ComprehensiveSearchResponse> => {
    return apiService.get<ComprehensiveSearchResponse>(
      `/search?query=${encodeURIComponent(query)}`,
      {
        errorMessage: "Failed to perform search",
      },
    );
  },
};

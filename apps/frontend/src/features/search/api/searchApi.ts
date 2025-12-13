import { apiService } from "@/lib/api";

export interface SearchResult {
  id: string;
  conversationId: string;
  message: string;
  timestamp: string;
  type: "user" | "bot";
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

// Interface for the message search response from Search.tsx
export interface MessageSearchResult {
  message: {
    message_id: string;
    response: string;
    date: string;
    type: string;
  };
  conversation_id: string;
}

export interface MessageSearchResponse {
  results: MessageSearchResult[];
}

// Interfaces for search results (matching SearchCard.tsx expectations)
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

// Interface for the comprehensive search response from SearchCommand.tsx
export interface ComprehensiveSearchResponse {
  conversations: SearchConversationResult[];
  messages: SearchMessageResult[];
  notes: SearchNoteResult[];
}

export const searchApi = {
  // Search messages (for Search.tsx component) - uses general search endpoint
  searchMessages: async (query: string): Promise<MessageSearchResponse> => {
    const response = await apiService.get<ComprehensiveSearchResponse>(
      `/search?query=${encodeURIComponent(query)}`,
      {
        errorMessage: "Failed to search messages",
      },
    );
    // Transform the comprehensive response to match the expected format
    return {
      results: response.messages.map((msg) => ({
        message: {
          message_id: msg.message.message_id,
          response: msg.snippet,
          date: msg.message.date,
          type: msg.message.type,
        },
        conversation_id: msg.conversation_id,
      })),
    };
  },

  // Comprehensive search (for SearchCommand.tsx component)
  search: async (query: string): Promise<ComprehensiveSearchResponse> => {
    return apiService.get<ComprehensiveSearchResponse>(
      `/search?query=${encodeURIComponent(query)}`,
      {
        errorMessage: "Failed to perform search",
      },
    );
  },

  // Search with filters (uses general search endpoint, filters applied client-side)
  searchWithFilters: async (params: {
    query: string;
    conversationId?: string;
    startDate?: string;
    endDate?: string;
    type?: "user" | "bot";
  }): Promise<SearchResponse> => {
    const response = await apiService.get<ComprehensiveSearchResponse>(
      `/search?query=${encodeURIComponent(params.query)}`,
      {
        errorMessage: "Failed to search messages",
      },
    );

    // Filter results client-side since backend doesn't support these filters
    let filteredMessages = response.messages;

    if (params.conversationId) {
      filteredMessages = filteredMessages.filter(
        (msg) => msg.conversation_id === params.conversationId,
      );
    }

    if (params.type) {
      filteredMessages = filteredMessages.filter(
        (msg) => msg.message.type === params.type,
      );
    }

    // Note: Date filtering would require parsing the date field
    // if (params.startDate || params.endDate) { ... }

    return {
      results: filteredMessages.map((msg) => ({
        id: msg.message.message_id,
        conversationId: msg.conversation_id,
        message: msg.snippet,
        timestamp: msg.message.date,
        type: msg.message.type as "user" | "bot",
      })),
      total: filteredMessages.length,
    };
  },
};

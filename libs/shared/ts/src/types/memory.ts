export interface Memory {
  id: string;
  content: string;
  source?: string;
  conversationId?: string;
  createdAt?: string;
  updatedAt?: string;
  relevanceScore?: number;
  categories?: string[];
  metadata?: Record<string, unknown>;
}

export interface MemoryCreate {
  content: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

export interface MemorySearchParams {
  query: string;
  limit?: number;
  offset?: number;
}

export interface MemorySearchResponse {
  memories: Memory[];
  total: number;
}

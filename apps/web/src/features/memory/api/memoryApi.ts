import { apiService } from "@/lib/api";

export interface Memory {
  id: string;
  content: string;
  user_id: string;
  metadata?: Record<string, unknown>;
  categories?: string[];
  created_at?: string;
  updated_at?: string;
  expiration_date?: string | null;
  internal_metadata?: Record<string, unknown> | null;
  deleted_at?: string | null;
  relevance_score?: number | null;
}

export interface MemoryRelation {
  source: string;
  source_type: string;
  relationship: string;
  target: string;
  target_type: string;
}

export interface MemoryCreate {
  content: string;
}

export interface MemoryUpdate {
  content: string;
}

export interface MemoriesResponse {
  memories: Memory[];
  relations: MemoryRelation[];
  total_count: number;
  success?: boolean;
}

export interface MemoryResponse {
  success: boolean;
  message?: string;
  memory?: Memory;
}

export interface DeleteResponse {
  success: boolean;
  message?: string;
}

export const memoryApi = {
  // Fetch all memories
  fetchMemories: async (): Promise<MemoriesResponse> => {
    return apiService.get<MemoriesResponse>("/memory", {
      silent: true, // Don't show toast on fetch
    });
  },

  // Create a new memory
  createMemory: async (memory: MemoryCreate): Promise<MemoryResponse> => {
    return apiService.post<MemoryResponse>("/memory", memory, {
      silent: true, // Component handles toast
    });
  },

  // Update a memory
  updateMemory: async (
    id: string,
    memory: MemoryUpdate,
  ): Promise<MemoryResponse> => {
    return apiService.put<MemoryResponse>(`/memory/${id}`, memory, {
      silent: true,
    });
  },

  // Delete a memory
  deleteMemory: async (id: string): Promise<DeleteResponse> => {
    return apiService.delete<DeleteResponse>(`/memory/${id}`, {
      silent: true, // Component handles toast
    });
  },

  // Delete all memories
  deleteAllMemories: async (): Promise<DeleteResponse> => {
    return apiService.delete<DeleteResponse>("/memory", {
      silent: true, // Component handles toast
    });
  },
};

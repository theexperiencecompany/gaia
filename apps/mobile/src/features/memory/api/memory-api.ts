import { apiService } from "@/lib/api";

export interface Memory {
  id: string;
  content: string;
  source_conversation_id?: string;
  created_at: string;
}

export interface MemoriesResponse {
  memories: Memory[];
}

export const memoryApi = {
  getMemories: (search?: string): Promise<MemoriesResponse> =>
    apiService.get<MemoriesResponse>(
      search ? `/memories?search=${encodeURIComponent(search)}` : "/memories",
    ),

  createMemory: (content: string): Promise<Memory> =>
    apiService.post<Memory>("/memories", { content }),

  deleteMemory: (id: string): Promise<void> =>
    apiService.delete(`/memories/${id}`),

  clearAllMemory: (): Promise<void> => apiService.delete("/memories"),
};

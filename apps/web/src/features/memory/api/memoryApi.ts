import type {
  CreateMemoryRequest,
  CreateMemoryResponse,
  DeleteMemoryResponse,
  MemoryDocType,
  MemoryDocument,
  MemoryDocumentsResponse,
  MemoryEntry,
  MemoryEpisodesResponse,
  MemoryGraphResponse,
  MemoryListResponse,
  MemoryOverviewResponse,
  MemorySearchResult,
  MemoryTreeResponse,
} from "@/features/memory/api/types";
import { apiService } from "@/lib/api/service";

interface ListMemoriesParams {
  page?: number;
  pageSize?: number;
  category?: string;
}

export const memoryApi = {
  listMemories: async ({
    page = 1,
    pageSize = 20,
    category,
  }: ListMemoriesParams = {}): Promise<MemoryListResponse> => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (category) params.set("category", category);
    return apiService.get<MemoryListResponse>(`/memory?${params}`, {
      silent: true,
    });
  },

  searchMemories: async (
    query: string,
    limit = 20,
  ): Promise<MemorySearchResult> => {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return apiService.get<MemorySearchResult>(`/memory/search?${params}`, {
      silent: true,
    });
  },

  getHistory: async (id: string): Promise<MemorySearchResult> => {
    return apiService.get<MemorySearchResult>(`/memory/${id}/history`, {
      silent: true,
    });
  },

  getOverview: async (): Promise<MemoryOverviewResponse> => {
    return apiService.get<MemoryOverviewResponse>("/memory/overview", {
      silent: true,
    });
  },

  getTree: async (): Promise<MemoryTreeResponse> => {
    return apiService.get<MemoryTreeResponse>("/memory/tree", {
      silent: true,
    });
  },

  getGraph: async (): Promise<MemoryGraphResponse> => {
    return apiService.get<MemoryGraphResponse>("/memory/graph", {
      silent: true,
    });
  },

  getEpisodes: async (
    start: string,
    end: string,
  ): Promise<MemoryEpisodesResponse> => {
    const params = new URLSearchParams({ start, end });
    return apiService.get<MemoryEpisodesResponse>(
      `/memory/episodes?${params}`,
      { silent: true },
    );
  },

  getDocuments: async (): Promise<MemoryDocumentsResponse> => {
    return apiService.get<MemoryDocumentsResponse>("/memory/documents", {
      silent: true,
    });
  },

  updateDocument: async (
    docType: MemoryDocType,
    content: string,
  ): Promise<MemoryDocument> => {
    return apiService.put<MemoryDocument>(
      `/memory/documents/${docType}`,
      { content },
      { silent: true },
    );
  },

  createMemory: async (
    request: CreateMemoryRequest,
  ): Promise<CreateMemoryResponse> => {
    return apiService.post<CreateMemoryResponse>("/memory", request, {
      silent: true,
    });
  },

  updateMemory: async (id: string, content: string): Promise<MemoryEntry> => {
    return apiService.patch<MemoryEntry>(
      `/memory/${id}`,
      { content },
      { silent: true },
    );
  },

  deleteMemory: async (id: string): Promise<DeleteMemoryResponse> => {
    return apiService.delete<DeleteMemoryResponse>(`/memory/${id}`, {
      silent: true,
    });
  },

  deleteAllMemories: async (): Promise<DeleteMemoryResponse> => {
    return apiService.delete<DeleteMemoryResponse>("/memory", {
      silent: true,
    });
  },
};

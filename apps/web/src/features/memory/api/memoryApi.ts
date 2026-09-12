import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

interface ListMemoriesParams {
  page?: number;
  pageSize?: number;
  category?: string;
}

export const memoryApi = {
  listMemories: ({
    page = 1,
    pageSize = 20,
    category,
  }: ListMemoriesParams = {}) =>
    api.get("/api/v1/memory", {
      query: { page, page_size: pageSize, category },
      silent: true,
    }),

  searchMemories: (query: string, limit = 20) =>
    api.get("/api/v1/memory/search", {
      query: { q: query, limit },
      silent: true,
    }),

  getHistory: (id: string) =>
    api.get("/api/v1/memory/{memory_id}/history", {
      path: { memory_id: id },
      silent: true,
    }),

  getOverview: () => api.get("/api/v1/memory/overview", { silent: true }),

  getTree: () => api.get("/api/v1/memory/tree", { silent: true }),

  getGraph: () => api.get("/api/v1/memory/graph", { silent: true }),

  getEpisodes: (start: string, end: string) =>
    api.get("/api/v1/memory/episodes", { query: { start, end }, silent: true }),

  getDocuments: () => api.get("/api/v1/memory/documents", { silent: true }),

  updateDocument: (docType: Schema<"MemoryDocType">, content: string) =>
    api.put("/api/v1/memory/documents/{doc_type}", {
      path: { doc_type: docType },
      body: { content },
      silent: true,
    }),

  createMemory: (request: Schema<"CreateMemoryRequest">) =>
    api.post("/api/v1/memory", { body: request, silent: true }),

  updateMemory: (id: string, content: string) =>
    api.patch("/api/v1/memory/{memory_id}", {
      path: { memory_id: id },
      body: { content },
      silent: true,
    }),

  deleteMemory: (id: string) =>
    api.delete("/api/v1/memory/{memory_id}", {
      path: { memory_id: id },
      silent: true,
    }),

  deleteAllMemories: () => api.delete("/api/v1/memory", { silent: true }),
};

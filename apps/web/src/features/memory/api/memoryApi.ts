import type { CreateMemoryRequest, MemoryDocType } from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import type { ApiQuery } from "@/lib/api/typed.types";

export const memoryApi = {
  listMemories: (query: ApiQuery<"get", "/api/v1/memory"> = {}) =>
    api.get("/api/v1/memory", { query, silent: true }),

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

  updateDocument: (docType: MemoryDocType, content: string) =>
    api.put("/api/v1/memory/documents/{doc_type}", {
      path: { doc_type: docType },
      body: { content },
      silent: true,
    }),

  createMemory: (request: CreateMemoryRequest) =>
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

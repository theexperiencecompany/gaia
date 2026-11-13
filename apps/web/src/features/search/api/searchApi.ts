import { api } from "@/lib/api/typed";

export const searchApi = {
  // Comprehensive search (for SearchCommand.tsx component)
  search: (query: string) =>
    api.get("/api/v1/search", {
      query: { query },
      errorMessage: "Failed to perform search",
    }),
};

import { api } from "@/lib/api/typed";

export const briefingApi = {
  // Fetch past briefings, most recent first.
  fetchBriefings: async (limit = 30) => {
    const data = await api.get("/api/v1/briefings", {
      query: { limit },
      silent: true,
    });
    return data.briefings;
  },
};

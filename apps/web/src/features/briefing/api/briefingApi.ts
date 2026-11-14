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

  // Fetch the Air Mail city stamps the user has collected.
  fetchPostmarks: () =>
    api.get("/api/v1/briefings/postmarks", { silent: true }),

  // Fetch one brief; the first open marks it opened on the server.
  fetchBriefing: (briefingId: string) =>
    api.get("/api/v1/briefings/{briefing_id}", {
      path: { briefing_id: briefingId },
      silent: true,
    }),
};

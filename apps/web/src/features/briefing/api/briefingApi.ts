import { api } from "@/lib/api/typed";
import { BRIEFING_ARCHIVE_PAGE_SIZE } from "../constants";

export const briefingApi = {
  // Fetch one page of past briefings, most recent first; before is the last page's next_cursor.
  fetchBriefings: (before: string | null) =>
    api.get("/api/v1/briefings", {
      query: { limit: BRIEFING_ARCHIVE_PAGE_SIZE, before: before ?? undefined },
      silent: true,
    }),

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

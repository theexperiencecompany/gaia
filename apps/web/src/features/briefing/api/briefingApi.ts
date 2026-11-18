import type {
  BriefingEditionsUpdate,
  BriefingScheduleUpdate,
} from "@shared/api/generated";
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

  // How often briefs come, and the daily brief's hour on the user's clock.
  fetchSchedule: () => api.get("/api/v1/briefings/schedule"),

  // Silent so a refused "off" can open its own dialog instead of a toast.
  updateSchedule: (update: BriefingScheduleUpdate) =>
    api.put("/api/v1/briefings/schedule", { body: update, silent: true }),

  // Every daily edition family, and whether the user keeps it on or favours it.
  fetchEditions: () => api.get("/api/v1/briefings/editions"),

  // Silent so the editions grid rolls back and words its own toast.
  updateEditions: (update: BriefingEditionsUpdate) =>
    api.put("/api/v1/briefings/editions", { body: update, silent: true }),
};

import { ApiError } from "@shared/api";
import type {
  BriefDeliveryWorkflow,
  BriefDeliveryWorkflowsConflict,
  BriefingEditionsUpdate,
  BriefingScheduleUpdate,
} from "@shared/api/generated";
import { queryOptions } from "@tanstack/react-query";
import { z } from "zod";

import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { api } from "@/lib/api/typed";

import { BRIEFING_ARCHIVE_PAGE_SIZE } from "../constants";
import { BRIEFING_STALE_MS, briefingKeys } from "./queryKeys";

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
  fetchSchedule: () =>
    api.get("/api/v1/briefings/schedule", {
      silent: true,
    }),

  // Silent so a refused "off" can open its own dialog instead of a toast.
  updateSchedule: (update: BriefingScheduleUpdate) =>
    api.put("/api/v1/briefings/schedule", {
      body: update,
      silent: true,
    }),

  // Every daily edition family, and whether the user keeps it on or favours it.
  fetchEditions: () =>
    api.get("/api/v1/briefings/editions", {
      silent: true,
    }),

  // Silent so the editions grid rolls back and words its own toast.
  updateEditions: (update: BriefingEditionsUpdate) =>
    api.put("/api/v1/briefings/editions", {
      body: update,
      silent: true,
    }),
};

/** One brief by id; fetching it is what marks it opened on the server. */
export const briefingQuery = (briefingId: string) =>
  queryOptions({
    queryKey: briefingKeys.detail(briefingId),
    queryFn: () => briefingApi.fetchBriefing(briefingId),
    staleTime: BRIEFING_STALE_MS,
    retry: false,
  });

export const postmarksQuery = () =>
  queryOptions({
    queryKey: briefingKeys.postmarks,
    queryFn: briefingApi.fetchPostmarks,
    staleTime: BRIEFING_STALE_MS,
  });

export const briefingScheduleQuery = () =>
  queryOptions({
    queryKey: briefingKeys.schedule,
    queryFn: briefingApi.fetchSchedule,
    staleTime: BRIEFING_STALE_MS,
  });

export const briefingEditionsQuery = () =>
  queryOptions({
    queryKey: briefingKeys.editions,
    queryFn: briefingApi.fetchEditions,
    staleTime: BRIEFING_STALE_MS,
  });

const BriefDeliveryWorkflowsSchema = z.array(
  z.object({
    id: z.string(),
    title: z.string(),
  }) satisfies z.ZodType<BriefDeliveryWorkflow>,
);

/** A refused "off": the API's own words and the workflows still delivering to the brief. */
export type BriefsOffBlock = Pick<
  BriefDeliveryWorkflowsConflict,
  "message" | "workflows"
>;

/** What blocked turning briefs off, when that is why the save failed, else null. */
export function readBriefsOffBlock(error: unknown): BriefsOffBlock | null {
  if (
    !(error instanceof ApiError) ||
    error.code !== API_ERROR_CODES.BRIEF_DELIVERY_WORKFLOWS_EXIST
  ) {
    return null;
  }
  return {
    message: error.message,
    workflows: BriefDeliveryWorkflowsSchema.parse(error.envelope?.workflows),
  };
}

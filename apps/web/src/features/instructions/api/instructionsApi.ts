import { ApiError } from "@shared/api";
import type { UpdateInstructionsRequest } from "@shared/api/generated";
import { queryOptions } from "@tanstack/react-query";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { api } from "@/lib/api/typed";

import { instructionsKeys } from "./queryKeys";

export const instructionsApi = {
  get: (scope: string) =>
    api.get("/api/v1/instructions/{scope}", {
      path: { scope },
      silent: true,
    }),

  /** Silent so the caller can show a conflict inline instead of a toast. */
  update: (scope: string, body: UpdateInstructionsRequest) =>
    api.put("/api/v1/instructions/{scope}", {
      path: { scope },
      body,
      silent: true,
    }),
};

/** Shared by every reader of a scope so a list preview and its editor hit one cache entry. */
export const instructionsQueryOptions = (scope: string) =>
  queryOptions({
    queryKey: instructionsKeys.scope(scope),
    queryFn: () => instructionsApi.get(scope),
    staleTime: 0,
  });

/** The revision to save against when a save lost a race to another writer, else null. */
export function instructionsConflictRevision(error: unknown): number | null {
  if (
    !(error instanceof ApiError) ||
    error.code !== API_ERROR_CODES.INSTRUCTIONS_CONFLICT
  ) {
    return null;
  }
  const revision = error.envelope?.current_revision;
  return typeof revision === "number" ? revision : null;
}

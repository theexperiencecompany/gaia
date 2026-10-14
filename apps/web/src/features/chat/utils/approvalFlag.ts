import type { ConversationSummary } from "@shared/api/generated";

/**
 * The one field sync compares. Typed off the generated `ConversationSummary`
 * (which carries `has_live_approval`), optional so cached rows that predate
 * the field keep compiling — they read as no live approval until refetched.
 */
type ApprovalFlagRow = Partial<Pick<ConversationSummary, "has_live_approval">>;

export type { ApprovalFlagRow };

/**
 * Reads the backend's `has_live_approval` off an API conversation row.
 *
 * Strict `=== true` so no truthy garbage ever lights the approval dot.
 */
export function apiRowHasLiveApproval(
  row: ApprovalFlagRow | null | undefined,
): boolean {
  return row?.has_live_approval === true;
}

/**
 * Whether a cached conversation row needs refetching for its approval flag.
 *
 * Sync staleness compares `updatedAt` timestamps, but flag flips never bump
 * `updatedAt` (they must not re-sort the list). Without this, a row cached
 * before the flag existed keeps `undefined` forever and the dot never
 * lights. Compares the field sync is responsible for, nothing else.
 */
export function isApprovalFlagStale(
  localHasFlag: boolean | undefined,
  remoteRow: ApprovalFlagRow | null | undefined,
): boolean {
  return apiRowHasLiveApproval(remoteRow) !== (localHasFlag ?? false);
}

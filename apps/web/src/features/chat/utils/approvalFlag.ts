import type { ConversationSummary } from "@shared/api/generated";

/**
 * The one field sync compares. Typed off the generated `ConversationSummary`
 * (which carries `awaiting_approval`), optional so cached rows that predate
 * the field keep compiling — they read as awaiting nothing until refetched.
 */
type ApprovalFlagRow = Partial<Pick<ConversationSummary, "awaiting_approval">>;

export type { ApprovalFlagRow };

/**
 * Reads the backend's `awaiting_approval` off an API conversation row.
 *
 * Strict `=== true` so no truthy garbage ever lights the approval dot.
 */
export function apiRowAwaitsApproval(
  row: ApprovalFlagRow | null | undefined,
): boolean {
  return row?.awaiting_approval === true;
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
  return apiRowAwaitsApproval(remoteRow) !== (localHasFlag ?? false);
}

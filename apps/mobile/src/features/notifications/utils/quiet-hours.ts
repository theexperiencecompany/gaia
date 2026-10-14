import type { QuietHours } from "@gaia/shared/types";

export type QuietHoursCommit =
  | { kind: "unchanged" }
  | { kind: "same-edges" }
  | { kind: "save"; next: QuietHours };

/** What committing an edited quiet-hours draft over the stored window does. */
export function resolveQuietHoursCommit(
  saved: QuietHours,
  draft: QuietHours,
): QuietHoursCommit {
  if (
    draft.start_hour === saved.start_hour &&
    draft.end_hour === saved.end_hour
  ) {
    return { kind: "unchanged" };
  }
  if (draft.start_hour === draft.end_hour) return { kind: "same-edges" };
  return { kind: "save", next: draft };
}

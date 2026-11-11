import type { InstructionsResponse } from "@gaia/shared/api/generated";

/** Outcome of a revision-guarded instructions save; a conflict carries the revision to overwrite. */
export type SaveInstructionsResult =
  | { status: "saved"; instructions: InstructionsResponse }
  | { status: "conflict"; currentRevision: number };

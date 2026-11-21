/** Parse boundary for the artifact_done tool card, tied to its declared type. */
import { z } from "zod";
import type { ArtifactKind } from "../api/generated";
import type {
  ArtifactCardData,
  ArtifactCardStatus,
  ArtifactFailureReason,
} from "./types";

/** Every value of a union, each keyed by itself: a missing or an extra value fails to compile. */
type EveryValue<Union extends string> = { readonly [Value in Union]: Value };

const ARTIFACT_KIND_VALUES = {
  dashboard: "dashboard",
  report: "report",
  plan: "plan",
  comparison: "comparison",
  memo: "memo",
  document: "document",
} as const satisfies EveryValue<ArtifactKind>;

export const ARTIFACT_KINDS: readonly ArtifactKind[] =
  Object.values(ARTIFACT_KIND_VALUES);

const ARTIFACT_FAILURE_REASONS = {
  validation: "validation",
  refused: "refused",
  timeout: "timeout",
  truncated: "truncated",
} as const satisfies EveryValue<ArtifactFailureReason>;

const ARTIFACT_CARD_STATUSES = {
  ready: "ready",
  failed: "failed",
} as const satisfies EveryValue<ArtifactCardStatus>;

export const ArtifactCardDataSchema = z.object({
  stream_id: z.string(),
  kind: z.enum(ARTIFACT_KIND_VALUES),
  title: z.string(),
  status: z.enum(ARTIFACT_CARD_STATUSES),
  artifact_id: z.string().nullish(),
  reason: z.enum(ARTIFACT_FAILURE_REASONS).nullish(),
}) satisfies z.ZodType<ArtifactCardData>;

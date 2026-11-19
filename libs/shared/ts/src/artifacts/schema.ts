/** Parse boundaries for the artifact frames and cards, tied to the generated API types. */
import { z } from "zod";
import type {
  ArtifactDelta,
  ArtifactFailureReason,
  ArtifactKind,
} from "../api/generated";
import type { ArtifactCardData, ArtifactCardStatus } from "./types";

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
  streaming: "streaming",
  stopped: "stopped",
} as const satisfies EveryValue<ArtifactCardStatus>;

const header = {
  stream_id: z.string(),
  kind: z.enum(ARTIFACT_KIND_VALUES),
  title: z.string(),
};

export const ArtifactDeltaSchema = z.object({
  ...header,
  delta: z.string(),
}) satisfies z.ZodType<ArtifactDelta>;

export const ArtifactCardDataSchema = z.object({
  ...header,
  status: z.enum(ARTIFACT_CARD_STATUSES),
  artifact_id: z.string().nullish(),
  reason: z.enum(ARTIFACT_FAILURE_REASONS).nullish(),
  program: z.string().optional(),
}) satisfies z.ZodType<ArtifactCardData>;

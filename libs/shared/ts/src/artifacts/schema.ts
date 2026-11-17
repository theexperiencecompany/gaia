/** Parse boundaries for the artifact frames and cards, tied to the generated API types. */
import { z } from "zod";
import type {
  ArtifactDelta,
  ArtifactFailureReason,
  ArtifactKind,
} from "../api/generated";
import type { ArtifactCardData } from "./types";

export const ARTIFACT_KINDS = [
  "dashboard",
  "report",
  "plan",
  "comparison",
  "memo",
  "document",
] as const satisfies readonly ArtifactKind[];

const ARTIFACT_FAILURE_REASONS = [
  "validation",
  "refused",
  "timeout",
  "truncated",
] as const satisfies readonly ArtifactFailureReason[];

const header = {
  stream_id: z.string(),
  kind: z.enum(ARTIFACT_KINDS),
  title: z.string(),
};

export const ArtifactDeltaSchema = z.object({
  ...header,
  delta: z.string(),
}) satisfies z.ZodType<ArtifactDelta>;

export const ArtifactCardDataSchema = z.object({
  ...header,
  status: z.enum(["ready", "failed", "streaming", "stopped"]),
  artifact_id: z.string().nullish(),
  reason: z.enum(ARTIFACT_FAILURE_REASONS).nullish(),
  program: z.string().optional(),
}) satisfies z.ZodType<ArtifactCardData>;

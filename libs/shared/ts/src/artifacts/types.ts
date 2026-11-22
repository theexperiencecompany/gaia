/** The artifact_done tool card: where a create_artifact run stands (ArtifactCard in apps/api/app/models/openui_artifact_models.py). */
import type { ArtifactKind } from "../api/generated";

export type ArtifactCardStatus = "streaming" | "ready" | "failed" | "stopped";

export type ArtifactFailureReason =
  | "validation"
  | "refused"
  | "timeout"
  | "truncated";

export interface ArtifactCardData {
  stream_id: string;
  kind: ArtifactKind;
  title: string;
  status: ArtifactCardStatus;
  /** The stored artifact, once status is ready; its program is fetched by this id. */
  artifact_id?: string | null;
  /** Why it gave up, on a failure the tool caught. */
  reason?: ArtifactFailureReason | null;
  /** The first draft so far, while status is streaming. */
  program?: string | null;
}

/** The card a live OpenUI artifact folds into, and the streamed frames that build it. */

/** "stopped" is the client's own: the user stopped the turn before the artifact was done. */
export type ArtifactCardStatus = "streaming" | "ready" | "failed" | "stopped";

/** Why a failed artifact gave up: ArtifactFailureReason in apps/api/app/models/openui_artifact_models.py. */
export type ArtifactFailureReason =
  | "validation"
  | "refused"
  | "timeout"
  | "truncated";

export interface ArtifactCardData {
  stream_id: string;
  kind: string;
  title: string;
  status: ArtifactCardStatus;
  /** Present once stored (status "ready"). */
  artifact_id?: string;
  /** Present on a failure the tool caught (status "failed"). */
  reason?: ArtifactFailureReason;
  /** The first draft as it streams; the stored program is fetched by artifact_id. */
  program?: string;
}

export interface ArtifactDeltaFrame {
  stream_id: string;
  kind: string;
  title: string;
  delta: string;
}

/** The card a live OpenUI artifact folds into, and the streamed chunks that build it. */
import type { ArtifactCard, ArtifactStatus } from "../api/generated";

export type { ArtifactDelta } from "../api/generated";

/** "streaming" and "stopped" are the client's own: a card before its done frame, and one the user stopped. */
export type ArtifactCardStatus = ArtifactStatus | "streaming" | "stopped";

/** The API's ArtifactCard as the chat shows it, with the first draft as it streams. */
export type ArtifactCardData = Omit<ArtifactCard, "status"> & {
  status: ArtifactCardStatus;
  /** The stored program is fetched by artifact_id. */
  program?: string;
};

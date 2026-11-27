import type {
  ArtifactDataCard,
  ArtifactFileEvent,
  ArtifactRegistryEntry,
} from "@shared/api/generated";

export type {
  ImageData,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "@shared/api/generated";
export type { CodeData, GoogleDocsData } from "@shared/chat";

/** Inline contents only artifact_data cards stored before the artifact registry carry. */
export interface LegacyArtifactEventFields {
  body?: string;
}

/** One artifact_data card: a file written or removed, as the timeline groups them. */
export type ArtifactEvent = ArtifactDataCard["data"] &
  LegacyArtifactEventFields;

/** A stored registry entry as the client holds it: stamped with its conversation. */
export const fromRegistryEntries = (
  entries: ArtifactRegistryEntry[],
  sessionId: string,
): ArtifactData[] =>
  entries.map((entry) => ({
    session_id: sessionId,
    path: entry.path,
    size_bytes: entry.size_bytes ?? 0,
    mtime: entry.mtime ?? undefined,
    content_type: entry.content_type,
    body: entry.body,
  }));

/** A file the conversation holds: a registry entry or a live file event, stamped with its conversation. */
export type ArtifactData = Pick<
  ArtifactFileEvent,
  "session_id" | "path" | "size_bytes" | "content_type"
> &
  Partial<Pick<ArtifactFileEvent, "event" | "mtime">> &
  Partial<Pick<ArtifactRegistryEntry, "body">>;

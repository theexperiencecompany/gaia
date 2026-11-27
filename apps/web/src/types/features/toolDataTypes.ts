import type { ArtifactRegistryEntry } from "@shared/api/generated";

export type { ImageData } from "@shared/api/generated";
export type {
  CodeData,
  GoogleDocsData,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "@shared/chat";

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

export interface ArtifactData {
  /** Conversation id the artifact belongs to (used to build fetch URLs). */
  session_id: string;
  /** "upsert" adds or refreshes a card; "remove" drops it. */
  event?: "upsert" | "remove";
  /** Path relative to the session's artifacts/ (or the upload name). */
  path: string;
  size_bytes: number;
  mtime?: number;
  content_type?: string | null;
  /**
   * UTF-8 file contents inlined when small + textual. When present, the
   * preview renders instantly without a follow-up fetch and survives reload
   * via the persisted conversation. Absent for large or binary files.
   */
  body?: string;
}

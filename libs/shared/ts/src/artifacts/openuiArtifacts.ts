/**
 * Live OpenUI artifacts in a chat turn. create_artifact (apps/api/app/agents/tools/artifact_tool.py)
 * streams the program as live-only `artifact_delta` frames, then leaves one persisted
 * `artifact_done` tool_data entry. Both fold into a single card entry keyed by stream_id.
 */
import type { StreamToolDataEntry } from "../chat/streaming";

export const ARTIFACT_CARD_TOOL_NAME = "artifact_done";

export type ArtifactCardStatus = "streaming" | "ready" | "failed";

export interface ArtifactCardData {
  stream_id: string;
  kind: string;
  title: string;
  status: ArtifactCardStatus;
  /** Present once stored (status "ready"). */
  artifact_id?: string;
  /** The first draft as it streams; the stored program is fetched by artifact_id. */
  program?: string;
}

export interface ArtifactDeltaFrame {
  stream_id: string;
  kind: string;
  title: string;
  delta: string;
}

const cardOf = (entry: StreamToolDataEntry): ArtifactCardData | null =>
  entry.tool_name === ARTIFACT_CARD_TOOL_NAME
    ? (entry.data as ArtifactCardData)
    : null;

function upsertCard<T extends StreamToolDataEntry>(
  entries: T[],
  streamId: string,
  next: (previous: ArtifactCardData | null) => T,
): T[] {
  const index = entries.findIndex(
    (entry) => cardOf(entry)?.stream_id === streamId,
  );
  if (index < 0) return [...entries, next(null)];
  return entries.map((entry, i) => (i === index ? next(cardOf(entry)) : entry));
}

/** Append a streamed chunk to its artifact's card, opening the card on the first chunk. */
export function applyArtifactDelta<T extends StreamToolDataEntry>(
  entries: T[],
  frame: ArtifactDeltaFrame,
): T[] {
  return upsertCard(
    entries,
    frame.stream_id,
    (previous) =>
      ({
        tool_name: ARTIFACT_CARD_TOOL_NAME,
        timestamp: new Date().toISOString(),
        data: {
          stream_id: frame.stream_id,
          kind: frame.kind,
          title: frame.title,
          status: "streaming",
          program: `${previous?.program ?? ""}${frame.delta}`,
        } satisfies ArtifactCardData,
      }) as T,
  );
}

/** The persisted artifact_done entry replaces its streaming card; other entries append. */
export function upsertArtifactDone<T extends StreamToolDataEntry>(
  entries: T[],
  entry: T,
): T[] {
  const done = cardOf(entry);
  if (!done) return [...entries, entry];
  return upsertCard(entries, done.stream_id, (previous) => ({
    ...entry,
    data: { ...done, program: previous?.program },
  }));
}

export function isArtifactDeltaFrame(
  value: unknown,
): value is ArtifactDeltaFrame {
  if (typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  return (
    typeof frame.stream_id === "string" &&
    typeof frame.kind === "string" &&
    typeof frame.title === "string" &&
    typeof frame.delta === "string"
  );
}

/**
 * Live OpenUI artifacts in a chat turn. create_artifact (apps/api/app/agents/tools/artifact_tool.py)
 * streams the program as live-only `artifact_delta` frames, then leaves one persisted
 * `artifact_done` tool_data entry. Both fold into a single card entry keyed by stream_id.
 */
import type { StreamToolDataEntry } from "../chat/streaming";
import { ArtifactCardDataSchema } from "./schema";
import type { ArtifactCardData, ArtifactDelta } from "./types";

export const ARTIFACT_CARD_TOOL_NAME = "artifact_done";

function cardOf(entry: StreamToolDataEntry): ArtifactCardData | null {
  if (entry.tool_name !== ARTIFACT_CARD_TOOL_NAME) return null;
  const parsed = ArtifactCardDataSchema.safeParse(entry.data);
  return parsed.success ? parsed.data : null;
}

function upsertCard(
  entries: StreamToolDataEntry[],
  streamId: string,
  next: (previous: ArtifactCardData | null) => StreamToolDataEntry,
): StreamToolDataEntry[] {
  const index = entries.findIndex(
    (entry) => cardOf(entry)?.stream_id === streamId,
  );
  if (index < 0) return [...entries, next(null)];
  return entries.map((entry, i) => (i === index ? next(cardOf(entry)) : entry));
}

/** Append a streamed chunk to its artifact's card, opening the card on the first chunk. */
export function applyArtifactDelta(
  entries: StreamToolDataEntry[],
  frame: ArtifactDelta,
): StreamToolDataEntry[] {
  return upsertCard(entries, frame.stream_id, (previous) => ({
    tool_name: ARTIFACT_CARD_TOOL_NAME,
    timestamp: new Date().toISOString(),
    data: {
      stream_id: frame.stream_id,
      kind: frame.kind,
      title: frame.title,
      status: "streaming",
      program: `${previous?.program ?? ""}${frame.delta}`,
    } satisfies ArtifactCardData,
  }));
}

/** The persisted artifact_done entry replaces its streaming card; other entries append. */
export function upsertArtifactDone(
  entries: StreamToolDataEntry[],
  entry: StreamToolDataEntry,
): StreamToolDataEntry[] {
  const done = cardOf(entry);
  if (!done) return [...entries, entry];
  return upsertCard(entries, done.stream_id, (previous) => ({
    ...entry,
    data: { ...done, program: previous?.program } satisfies ArtifactCardData,
  }));
}

/**
 * A stopped turn's artifacts still writing end as stopped. The run is cancelled
 * before create_artifact can send its done frame, so nothing else ends them.
 */
export function stopStreamingArtifacts(
  entries: StreamToolDataEntry[],
): StreamToolDataEntry[] {
  return entries.map((entry) => {
    const card = cardOf(entry);
    return card?.status === "streaming"
      ? {
          ...entry,
          data: { ...card, status: "stopped" } satisfies ArtifactCardData,
        }
      : entry;
  });
}

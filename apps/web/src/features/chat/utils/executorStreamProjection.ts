import { createTurnAccumulator, type TurnAccumulator } from "@shared/chat";
import { createOwnToolDataFold, foldOwnToolData } from "@shared/utils";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import type { IMessage } from "@/lib/db/chatDb";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { ImageData, MemoryData } from "@/types/features/toolDataTypes";

/** How one stream's accumulator lands on the message it renders into. */
export interface StreamProjection {
  project: (current: IMessage, acc: TurnAccumulator) => IMessage;
  finalize: (
    current: IMessage,
    acc: TurnAccumulator,
    error: string | undefined,
  ) => IMessage;
}

/** A background subagent's projection: fold its own cards in, touch nothing else. */
export const subagentProjection = (): StreamProjection => {
  let fold = createOwnToolDataFold();
  const project = (current: IMessage, acc: TurnAccumulator): IMessage => {
    const folded = foldOwnToolData(
      fold,
      (current.tool_data as TurnAccumulator["toolData"] | null) ?? [],
      acc.toolData,
    );
    fold = folded.fold;
    return {
      ...current,
      tool_data: folded.toolData as TypedToolDataEntry[],
      updatedAt: new Date(),
    };
  };
  // The turn's text and status belong to the run that owns the message; a
  // subagent that fails says so in its own row and in the executor's report.
  return { project, finalize: (current, acc) => project(current, acc) };
};

/** Project the shared accumulator onto the placeholder message record.
 *
 * `writeContent` is false unless the stream actually produced response text:
 * an executor stream emits no `response` frames, so its accumulator text stays
 * at the seed and writing it would stamp that stale snapshot over the comms
 * narration the backend concurrently saves.
 */
const applyAccumulatorToMessage = (
  base: IMessage,
  acc: TurnAccumulator,
  writeContent: boolean,
): IMessage => ({
  ...base,
  ...(writeContent ? { content: acc.responseText } : {}),
  tool_data:
    acc.toolData.length > 0 ? (acc.toolData as TypedToolDataEntry[]) : null,
  follow_up_actions: acc.followUpActions,
  image_data: (acc.imageData as ImageData | null) ?? null,
  memory_data: (acc.extras.memory_data as MemoryData | undefined) ?? null,
  todo_progress: (acc.todoProgress as TodoProgressData | null) ?? null,
  updatedAt: new Date(),
});

/**
 * An executor run's projection and its starting accumulator. It REPLACES the
 * record's fields, so a continued message seeds the accumulator with what it
 * already has, or its earlier cards and text would be wiped by the first
 * resumed frame; only once a `response` frame moves the text off that seed is
 * the text written.
 */
export const executorProjection = (
  existing: IMessage | undefined,
): { projection: StreamProjection; initial: TurnAccumulator } => {
  const seededContent = existing?.content ?? "";
  const initial = existing
    ? {
        ...createTurnAccumulator(seededContent),
        toolData: [
          ...((existing.tool_data as TurnAccumulator["toolData"]) ?? []),
        ],
      }
    : createTurnAccumulator();
  const hasNewContent = (acc: TurnAccumulator) =>
    acc.responseText !== seededContent;
  return {
    initial,
    projection: {
      project: (current, acc) =>
        applyAccumulatorToMessage(current, acc, hasNewContent(acc)),
      finalize: (current, acc, error) => ({
        ...applyAccumulatorToMessage(current, acc, hasNewContent(acc)),
        status: error ? "failed" : "sent",
        error: error ?? null,
      }),
    },
  };
};

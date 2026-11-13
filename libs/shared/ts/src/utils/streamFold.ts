import { APPROVAL_REQUEST_TOOL_NAME } from "../chat/approvals";
import type { StreamToolDataEntry } from "../chat/streaming";
import type { SubagentGroupData } from "../chat/types";
import { SUBAGENT_GROUP_TOOL_NAME } from "../chat/types";

const TODO_PROGRESS_TOOL_NAME = "todo_progress";

/**
 * What one stream found in the message the first time it folded each of its
 * entries — the part of that entry it does not own and must keep.
 */
export interface OwnToolDataFold {
  readonly priors: ReadonlyMap<string, StreamToolDataEntry | null>;
}

export const createOwnToolDataFold = (): OwnToolDataFold => ({
  priors: new Map(),
});

const identityOf = (entry: StreamToolDataEntry): string => {
  const data = entry.data as Record<string, unknown> | null;
  if (entry.tool_name === SUBAGENT_GROUP_TOOL_NAME) {
    return `subagent:${String((data as SubagentGroupData | null)?.subagent_id)}`;
  }
  if (entry.tool_name === APPROVAL_REQUEST_TOOL_NAME) {
    return `approval:${String(data?.approval_id)}`;
  }
  if (entry.tool_name === TODO_PROGRESS_TOOL_NAME)
    return TODO_PROGRESS_TOOL_NAME;
  return `${entry.tool_name}:${entry.timestamp ?? ""}`;
};

/** One stream's entry combined with what the message held under the same identity. */
const combine = (
  own: StreamToolDataEntry,
  prior: StreamToolDataEntry | null,
  current: StreamToolDataEntry | undefined,
): StreamToolDataEntry => {
  if (own.tool_name === TODO_PROGRESS_TOOL_NAME) {
    // Keyed by source: another run's snapshot keeps updating beside this one.
    return {
      ...own,
      data: {
        ...((current?.data as object | undefined) ?? {}),
        ...(own.data as object),
      },
    };
  }
  if (own.tool_name !== SUBAGENT_GROUP_TOOL_NAME || prior === null) return own;
  // A resumed run streams only what it did after the pause; the parked run's
  // calls are already in the message and stay ahead of them.
  const before = prior.data as SubagentGroupData;
  const after = own.data as SubagentGroupData;
  return {
    ...own,
    timestamp: prior.timestamp ?? own.timestamp,
    data: {
      ...after,
      started_at: before.started_at,
      tool_calls: [...before.tool_calls, ...after.tool_calls],
      nested_subagents: [...before.nested_subagents, ...after.nested_subagents],
    } satisfies SubagentGroupData,
  };
};

/**
 * Fold a detached stream's own entries into a message another run may still be writing.
 *
 * Upserts each by identity rather than replacing tool_data: its subagent group (a
 * resumed run's calls join the parked run's), an approval card (settled in place),
 * todo progress (merged by source). Idempotent: pass every flush's full accumulator.
 */
export const foldOwnToolData = (
  fold: OwnToolDataFold,
  current: StreamToolDataEntry[],
  own: StreamToolDataEntry[],
): { fold: OwnToolDataFold; toolData: StreamToolDataEntry[] } => {
  const priors = new Map(fold.priors);
  let toolData = [...current];
  for (const entry of own) {
    const key = identityOf(entry);
    const index = toolData.findIndex((e) => identityOf(e) === key);
    if (!priors.has(key)) priors.set(key, index >= 0 ? toolData[index] : null);
    const merged = combine(
      entry,
      priors.get(key) ?? null,
      index >= 0 ? toolData[index] : undefined,
    );
    toolData =
      index >= 0
        ? toolData.map((e, i) => (i === index ? merged : e))
        : [...toolData, merged];
  }
  return { fold: { priors }, toolData };
};

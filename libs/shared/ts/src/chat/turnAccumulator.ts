import type {
  ChatStreamEvent,
  StreamToolDataEntry,
  StreamToolOutput,
} from "./streaming";
import {
  mergeToolOutputIntoToolData,
  TOOL_CALLS_DATA_TOOL_NAME,
  upsertTodoProgressToolData,
} from "./streaming";
import type {
  SubagentGroupData,
  TodoProgressSnapshot,
  ToolCallEntry,
} from "./types";
import { REASONING_TOOL_NAME, SUBAGENT_GROUP_TOOL_NAME } from "./types";

/**
 * Pure accumulation state for one assistant turn. Every streaming transport
 * (live chat SSE, executor-resume SSE, mobile) folds its parsed events into
 * this shape via applyStreamEvent, so live rendering, background runs, and
 * reload all see identically-assembled data.
 */
export interface TurnAccumulator {
  responseText: string;
  toolData: StreamToolDataEntry[];
  followUpActions: string[] | null;
  imageData: { url: string; prompt?: string } | null;
  generatingImage: boolean;
  todoProgress: Record<string, TodoProgressSnapshot> | null;
  /** Untyped passthrough payload fields (e.g. memory_data) merged onto the message. */
  extras: Record<string, unknown>;
}

export const createTurnAccumulator = (): TurnAccumulator => ({
  responseText: "",
  toolData: [],
  followUpActions: null,
  imageData: null,
  generatingImage: false,
  todoProgress: null,
  extras: {},
});

const REASONING_CATEGORY = "reasoning";

// A thinking step: a ToolCallEntry carrying `reasoning` (rendered as a
// collapsible "Thinking" row, not a tool call).
const makeReasoningStep = (content: string): ToolCallEntry => ({
  tool_name: REASONING_TOOL_NAME,
  tool_category: REASONING_CATEGORY,
  message: "",
  reasoning: content,
});

// Append a reasoning delta onto a trailing thinking step, or start a new one
// when the previous step was a real tool call, so consecutive deltas merge into
// one block that naturally breaks at each tool call.
const appendReasoningStep = (
  steps: ToolCallEntry[],
  content: string,
): ToolCallEntry[] => {
  const last = steps.at(-1);
  if (last?.reasoning != null) {
    return [
      ...steps.slice(0, -1),
      { ...last, reasoning: last.reasoning + content },
    ];
  }
  return [...steps, makeReasoningStep(content)];
};

/** Recursively find and update a SubagentGroupData by ID anywhere in the tree. */
const updateSubagentGroup = (
  group: SubagentGroupData,
  targetId: string,
  updater: (g: SubagentGroupData) => SubagentGroupData,
): SubagentGroupData => {
  if (group.subagent_id === targetId) return updater(group);
  return {
    ...group,
    nested_subagents: group.nested_subagents.map((nested) =>
      updateSubagentGroup(nested, targetId, updater),
    ),
  };
};

/** Apply updateSubagentGroup across the full tool_data list. */
export const updateSubagentInToolData = <T extends StreamToolDataEntry>(
  toolData: T[],
  targetId: string,
  updater: (g: SubagentGroupData) => SubagentGroupData,
): T[] =>
  toolData.map((entry) => {
    if (entry.tool_name !== SUBAGENT_GROUP_TOOL_NAME) return entry;
    return {
      ...entry,
      data: updateSubagentGroup(
        entry.data as SubagentGroupData,
        targetId,
        updater,
      ),
    };
  });

const applyToolData = (
  acc: TurnAccumulator,
  entry: StreamToolDataEntry,
): TurnAccumulator => {
  // Route tool_calls_data entries into the matching subagent group.
  if (entry.subagent_id && entry.tool_name === TOOL_CALLS_DATA_TOOL_NAME) {
    return {
      ...acc,
      toolData: updateSubagentInToolData(
        acc.toolData,
        entry.subagent_id,
        (g) => ({
          ...g,
          tool_calls: [...g.tool_calls, entry.data as ToolCallEntry],
        }),
      ),
    };
  }
  return { ...acc, toolData: [...acc.toolData, entry] };
};

const applyReasoning = (
  acc: TurnAccumulator,
  content: string,
  subagentId: string | undefined,
): TurnAccumulator => {
  if (!content) return acc;

  if (subagentId) {
    return {
      ...acc,
      toolData: updateSubagentInToolData(acc.toolData, subagentId, (g) => ({
        ...g,
        tool_calls: appendReasoningStep(g.tool_calls, content),
      })),
    };
  }

  // Executor-level thinking rides a tool_calls_data entry (data is an ordered
  // step list) so it flows through the root timeline like a tool call.
  const last = acc.toolData.at(-1);
  const lastSteps =
    last?.tool_name === TOOL_CALLS_DATA_TOOL_NAME && Array.isArray(last.data)
      ? (last.data as ToolCallEntry[])
      : undefined;
  const trailing = lastSteps?.at(-1);

  if (last && lastSteps && trailing?.reasoning != null) {
    return {
      ...acc,
      toolData: [
        ...acc.toolData.slice(0, -1),
        { ...last, data: appendReasoningStep(lastSteps, content) },
      ],
    };
  }

  return {
    ...acc,
    toolData: [
      ...acc.toolData,
      {
        tool_name: TOOL_CALLS_DATA_TOOL_NAME,
        tool_category: REASONING_CATEGORY,
        data: [makeReasoningStep(content)],
        timestamp: new Date().toISOString(),
      },
    ],
  };
};

const applyToolOutput = (
  acc: TurnAccumulator,
  output: StreamToolOutput,
): TurnAccumulator => {
  if (output.subagent_id) {
    return {
      ...acc,
      toolData: updateSubagentInToolData(
        acc.toolData,
        output.subagent_id,
        (g) => ({
          ...g,
          tool_calls: g.tool_calls.map((tc) =>
            tc.tool_call_id === output.tool_call_id
              ? { ...tc, output: output.output }
              : tc,
          ),
        }),
      ),
    };
  }
  return {
    ...acc,
    toolData: mergeToolOutputIntoToolData(acc.toolData, output),
  };
};

const applySubagentStart = (
  acc: TurnAccumulator,
  payload: {
    subagent_id: string;
    subagent_name: string;
    agent_type: "handoff" | "spawned";
    started_at: string;
    icon_url?: string;
    tool_category?: string;
    parent_subagent_id?: string;
  },
): TurnAccumulator => {
  const group: SubagentGroupData = {
    subagent_id: payload.subagent_id,
    subagent_name: payload.subagent_name,
    agent_type: payload.agent_type,
    tool_calls: [],
    duration_ms: null,
    token_count: null,
    started_at: payload.started_at,
    completed_at: null,
    icon_url: payload.icon_url ?? null,
    tool_category: payload.tool_category ?? null,
    nested_subagents: [],
  };

  // A subagent spawned from within another subagent nests inside its parent.
  if (payload.parent_subagent_id) {
    return {
      ...acc,
      toolData: updateSubagentInToolData(
        acc.toolData,
        payload.parent_subagent_id,
        (g) => ({ ...g, nested_subagents: [...g.nested_subagents, group] }),
      ),
    };
  }

  return {
    ...acc,
    toolData: [
      ...acc.toolData,
      {
        tool_name: SUBAGENT_GROUP_TOOL_NAME,
        tool_category: "subagent",
        data: group,
        timestamp: payload.started_at,
      },
    ],
  };
};

const applySubagentEnd = (
  acc: TurnAccumulator,
  payload: {
    subagent_id: string;
    duration_ms: number | undefined;
    token_count: number | null;
  },
): TurnAccumulator => ({
  ...acc,
  toolData: updateSubagentInToolData(
    acc.toolData,
    payload.subagent_id,
    (g) => ({
      ...g,
      duration_ms: payload.duration_ms ?? null,
      token_count: payload.token_count,
      completed_at: new Date().toISOString(),
    }),
  ),
});

const applyTodoProgress = (
  acc: TurnAccumulator,
  snapshot: TodoProgressSnapshot,
): TurnAccumulator => {
  const source = snapshot.source || "executor";
  return {
    ...acc,
    todoProgress: { ...(acc.todoProgress ?? {}), [source]: snapshot },
    toolData: upsertTodoProgressToolData(acc.toolData, snapshot),
  };
};

const isImageDataPayload = (
  value: unknown,
): value is { url: string; prompt?: string } =>
  typeof value === "object" && value !== null && "url" in value;

// Untyped passthrough frames (image tool statuses, memory data, …) that reach
// the parser as `unknown`. Image generation gets first-class accumulator state;
// everything else lands in `extras` and is merged onto the message verbatim.
const applyUnknownPayload = (
  acc: TurnAccumulator,
  payload: Record<string, unknown>,
): TurnAccumulator => {
  if (payload.status === "generating_image") {
    return {
      ...acc,
      generatingImage: true,
      imageData: { url: "" },
      responseText: "",
    };
  }
  if (isImageDataPayload(payload.image_data)) {
    return { ...acc, generatingImage: false, imageData: payload.image_data };
  }
  return { ...acc, extras: { ...acc.extras, ...payload } };
};

/**
 * Fold one parsed stream event into the accumulator. Pure: returns a new
 * accumulator, never mutates. Lifecycle events (done, error, progress,
 * conversation init, desktop tool requests, …) intentionally return the
 * accumulator unchanged — they belong to the turn session, not the message.
 */
export const applyStreamEvent = (
  acc: TurnAccumulator,
  event: ChatStreamEvent,
): TurnAccumulator => {
  switch (event.type) {
    case "response":
      return { ...acc, responseText: acc.responseText + event.chunk };
    case "tool_data":
      return applyToolData(acc, event.entry);
    case "tool_output":
      return applyToolOutput(acc, event.output);
    case "reasoning":
      return applyReasoning(acc, event.content, event.subagent_id);
    case "subagent_start":
      return applySubagentStart(acc, event.payload);
    case "subagent_end":
      return applySubagentEnd(acc, event.payload);
    case "todo_progress":
      return applyTodoProgress(acc, event.snapshot);
    case "follow_up_actions":
      return { ...acc, followUpActions: event.actions };
    case "unknown":
      return applyUnknownPayload(acc, event.payload);
    case "done":
    case "keepalive":
    case "error":
    case "parse_error":
    case "main_response_complete":
    case "progress":
    case "conversation_initialized":
    case "conversation_description":
    case "desktop_tool_request":
    case "token_usage":
      return acc;
    default: {
      // Exhaustiveness guard: adding a ChatStreamEvent member without deciding
      // how it accumulates is a compile error, not a silent drop.
      const unhandled: never = event;
      return unhandled;
    }
  }
};

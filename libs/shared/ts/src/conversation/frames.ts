import { z } from "zod";
import type {
  ConversationUpdatedFrame,
  EntryFrame,
  EntryUpdatedFrame,
  LiveTask,
  ReplyDeltaFrame,
  RetractFrame,
  StateFrame,
  WorkDeltaFrame,
} from "../api/generated";
import { ToolDataEntrySchema } from "../chat/schema";
import type { ChatStreamEvent } from "../chat/streaming";
import type { TodoProgressSnapshot } from "../chat/types";
import { EntrySchema } from "./entries";
import type { ConversationStreamEvent } from "./types";

/**
 * Zod mirror of the conversation event stream's frames, each tied to its generated
 * API type. A delta's tagged payload is mapped onto the ChatStreamEvent the shared
 * TurnAccumulator folds.
 */

export const FRAME_KIND = {
  ENTRY: "entry",
  ENTRY_UPDATED: "entry_updated",
  REPLY_DELTA: "reply_delta",
  WORK_DELTA: "work_delta",
  RETRACT: "retract",
  STATE: "state",
  CONVERSATION_UPDATED: "conversation_updated",
} as const;

export const DISPLAY_STATE = {
  IDLE: "idle",
  THINKING: "thinking",
  WORKING: "working",
  AWAITING_APPROVAL: "awaiting_approval",
} as const;

const optionalString = z
  .string()
  .nullish()
  .transform((value) => value ?? undefined);

const StreamPayloadSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("response"), response: z.string() }),
  z.object({
    type: z.literal("reasoning"),
    reasoning: z.object({ content: z.string(), subagent_id: optionalString }),
  }),
  z.object({ type: z.literal("tool_data"), tool_data: ToolDataEntrySchema }),
  z.object({
    type: z.literal("tool_output"),
    tool_output: z.object({
      tool_call_id: z.string(),
      output: z.string(),
      subagent_id: optionalString,
    }),
  }),
  z.object({
    type: z.literal("message_boundary"),
    message_boundary: z.object({
      message_id: z.string(),
      discarded: z.boolean(),
    }),
  }),
  z.object({
    type: z.literal("subagent_start"),
    subagent_start: z.object({
      subagent_id: z.string(),
      subagent_name: z.string(),
      subagent: optionalString,
      agent_type: z.string(),
      started_at: z.string(),
      icon_url: optionalString,
      tool_category: optionalString,
      parent_subagent_id: optionalString,
    }),
  }),
  z.object({
    type: z.literal("subagent_end"),
    subagent_end: z.object({
      subagent_id: z.string(),
      duration_ms: z.number(),
      token_count: z
        .number()
        .nullish()
        .transform((value) => value ?? null),
    }),
  }),
  z.object({
    type: z.literal("follow_up_actions"),
    follow_up_actions: z.array(z.string()),
  }),
  z.object({
    type: z.literal("todo_progress"),
    todo_progress: z.record(z.string(), z.unknown()),
  }),
]) satisfies z.ZodType<ReplyDeltaFrame["payload"]>;

type StreamPayload = z.infer<typeof StreamPayloadSchema>;

/** Map a tagged delta payload onto the chat stream event the accumulator already folds. */
function toStreamEvent(payload: StreamPayload): ChatStreamEvent {
  switch (payload.type) {
    case "response":
      return { type: "response", chunk: payload.response };
    case "reasoning":
      return { type: "reasoning", ...payload.reasoning };
    case "tool_data":
      return { type: "tool_data", entry: payload.tool_data };
    case "tool_output":
      return { type: "tool_output", output: payload.tool_output };
    case "message_boundary":
      return {
        type: "message_boundary",
        messageId: payload.message_boundary.message_id,
        discarded: payload.message_boundary.discarded,
      };
    case "subagent_start": {
      const { agent_type, ...start } = payload.subagent_start;
      // Nothing emits "handoff" any more; stored rows that carry it still render as one.
      return {
        type: "subagent_start",
        payload: {
          ...start,
          agent_type: agent_type === "handoff" ? "handoff" : "spawned",
        },
      };
    }
    case "subagent_end":
      return { type: "subagent_end", payload: payload.subagent_end };
    case "follow_up_actions":
      return { type: "follow_up_actions", actions: payload.follow_up_actions };
    case "todo_progress":
      // Same open-shape cast as parseChatStreamEvent: the snapshot is a dict[str, Any] on the wire.
      return {
        type: "todo_progress",
        snapshot: payload.todo_progress as TodoProgressSnapshot,
      };
    default: {
      const unhandled: never = payload;
      return unhandled;
    }
  }
}

const seq = z.number().int().min(1);
const index = z.number().int().min(0);
const deltaPayload = StreamPayloadSchema.transform(toStreamEvent);

export const LiveTaskSchema = z.object({
  task_id: z.string(),
  awaiting_approval: z.boolean(),
}) satisfies z.ZodType<LiveTask>;

export const EntryFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.ENTRY),
  seq,
  at: z.iso.datetime({ offset: true }),
  entry: EntrySchema,
}) satisfies z.ZodType<EntryFrame>;

const EntryUpdatedFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.ENTRY_UPDATED),
  seq,
  entry: EntrySchema,
}) satisfies z.ZodType<EntryUpdatedFrame>;

// The payload is checked against its generated union above; these tie the rest of each delta frame.
const ReplyDeltaFields = z.object({
  kind: z.literal(FRAME_KIND.REPLY_DELTA),
  attempt_id: z.string(),
  reply_id: z.string().nullable(),
  index,
}) satisfies z.ZodType<Omit<ReplyDeltaFrame, "payload">>;

const WorkDeltaFields = z.object({
  kind: z.literal(FRAME_KIND.WORK_DELTA),
  task_id: z.string(),
  index,
}) satisfies z.ZodType<Omit<WorkDeltaFrame, "payload">>;

const RetractFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.RETRACT),
  attempt_id: z.string(),
}) satisfies z.ZodType<RetractFrame>;

export const StateFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.STATE),
  head: z.number().int().min(0),
  display: z.enum([
    DISPLAY_STATE.IDLE,
    DISPLAY_STATE.THINKING,
    DISPLAY_STATE.WORKING,
    DISPLAY_STATE.AWAITING_APPROVAL,
  ]),
  work: z.array(LiveTaskSchema),
}) satisfies z.ZodType<StateFrame>;

const ConversationUpdatedFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.CONVERSATION_UPDATED),
  description: z.string(),
}) satisfies z.ZodType<ConversationUpdatedFrame>;

export const ConversationFrameSchema = z.discriminatedUnion("kind", [
  EntryFrameSchema,
  EntryUpdatedFrameSchema,
  ReplyDeltaFields.extend({ payload: deltaPayload }),
  WorkDeltaFields.extend({ payload: deltaPayload }),
  RetractFrameSchema,
  StateFrameSchema,
  ConversationUpdatedFrameSchema,
]);

const ConversationEventSchema = z.object({
  stream_id: z.string().nullable(),
  frame: ConversationFrameSchema,
});

export type FrameParseError =
  | { kind: "invalid_json"; raw: string }
  | { kind: "invalid_frame"; raw: string; issues: string[] };

export type FrameParseResult =
  | { ok: true; event: ConversationStreamEvent }
  | { ok: false; error: FrameParseError };

const readJson = (
  raw: string,
): { ok: true; value: unknown } | { ok: false } => {
  try {
    return { ok: true, value: JSON.parse(raw) };
  } catch {
    return { ok: false };
  }
};

/** Parse one `data:` line of the conversation stream into a typed event or a typed error. */
export function parseConversationEvent(raw: string): FrameParseResult {
  const json = readJson(raw);
  if (!json.ok) return { ok: false, error: { kind: "invalid_json", raw } };
  const parsed = ConversationEventSchema.safeParse(json.value);
  if (!parsed.success) {
    const issues = parsed.error.issues.map(
      (issue) => `${issue.path.join(".")}: ${issue.message}`,
    );
    return { ok: false, error: { kind: "invalid_frame", raw, issues } };
  }
  return {
    ok: true,
    event: { streamId: parsed.data.stream_id, frame: parsed.data.frame },
  };
}

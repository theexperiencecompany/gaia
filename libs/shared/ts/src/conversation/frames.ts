import { z } from "zod";
import { ToolDataEntrySchema } from "../chat/schema";
import type { ChatStreamEvent } from "../chat/streaming";
import type { TodoProgressSnapshot } from "../chat/types";
import { LoggedEntrySchema } from "./entries";

/**
 * Zod mirror of the conversation event stream's frames; the source of truth is
 * apps/api/app/models/conversation_frame_models.py. A delta's payload is parsed
 * straight into the ChatStreamEvent the shared TurnAccumulator folds.
 */

export const FRAME_KIND = {
  ENTRY: "entry",
  ENTRY_UPDATED: "entry_updated",
  DELTA: "delta",
  RETRACT: "retract",
  STATE: "state",
} as const;

export const CONVERSATION_DISPLAY = {
  IDLE: "idle",
  THINKING: "thinking",
  WORKING: "working",
  AWAITING_APPROVAL: "awaiting_approval",
} as const;

export const WORK_PHASE = {
  NONE: "none",
  RUNNING: "running",
  AWAITING_APPROVAL: "awaiting_approval",
} as const;

const optionalString = z
  .string()
  .nullish()
  .transform((value) => value ?? undefined);

// The server's payload union carries no tag, so each member is strict: the keys alone pick it.
const DeltaPayloadSchema = z.union([
  z
    .strictObject({ response: z.string() })
    .transform(
      (p): ChatStreamEvent => ({ type: "response", chunk: p.response }),
    ),
  z.strictObject({ follow_up_actions: z.array(z.string()) }).transform(
    (p): ChatStreamEvent => ({
      type: "follow_up_actions",
      actions: p.follow_up_actions,
    }),
  ),
  z
    .strictObject({ todo_progress: z.record(z.string(), z.unknown()) })
    .transform(
      (p): ChatStreamEvent => ({
        type: "todo_progress",
        // Same open-shape cast as parseChatStreamEvent: the snapshot is a dict[str, Any] on the wire.
        snapshot: p.todo_progress as TodoProgressSnapshot,
      }),
    ),
  z.strictObject({ message_id: z.string(), discarded: z.boolean() }).transform(
    (p): ChatStreamEvent => ({
      type: "message_boundary",
      messageId: p.message_id,
      discarded: p.discarded,
    }),
  ),
  z
    .strictObject({
      tool_call_id: z.string(),
      output: z.string(),
      subagent_id: optionalString,
    })
    .transform((output): ChatStreamEvent => ({ type: "tool_output", output })),
  z
    .strictObject({ content: z.string(), subagent_id: optionalString })
    .transform(
      (p): ChatStreamEvent => ({
        type: "reasoning",
        content: p.content,
        subagent_id: p.subagent_id,
      }),
    ),
  z
    .strictObject({
      subagent_id: z.string(),
      subagent_name: z.string(),
      subagent: z.string().nullish(),
      agent_type: z.enum(["handoff", "spawned"]),
      started_at: z.string(),
      icon_url: optionalString,
      tool_category: optionalString,
      parent_subagent_id: optionalString,
    })
    .transform(
      ({ subagent: _integration, ...payload }): ChatStreamEvent => ({
        type: "subagent_start",
        payload,
      }),
    ),
  z
    .strictObject({
      subagent_id: z.string(),
      duration_ms: z.number(),
      token_count: z.number().nullish(),
    })
    .transform(
      (p): ChatStreamEvent => ({
        type: "subagent_end",
        payload: {
          subagent_id: p.subagent_id,
          duration_ms: p.duration_ms,
          token_count: p.token_count ?? null,
        },
      }),
    ),
  ToolDataEntrySchema.transform(
    (entry): ChatStreamEvent => ({ type: "tool_data", entry }),
  ),
]);

const EntryFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.ENTRY),
  entry: LoggedEntrySchema,
});

const EntryUpdatedFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.ENTRY_UPDATED),
  entry: LoggedEntrySchema,
});

const DeltaFrameSchema = z
  .object({
    kind: z.literal(FRAME_KIND.DELTA),
    attempt_id: z.string(),
    reply_id: z.string().nullable().default(null),
    task_id: z.string().nullable().default(null),
    payload: DeltaPayloadSchema,
  })
  .refine((frame) => (frame.reply_id === null) !== (frame.task_id === null), {
    message: "a delta targets exactly one of reply_id or task_id",
  });

const RetractFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.RETRACT),
  attempt_id: z.string(),
});

const StateFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.STATE),
  head: z.number().int().min(0),
  display: z.enum([
    CONVERSATION_DISPLAY.IDLE,
    CONVERSATION_DISPLAY.THINKING,
    CONVERSATION_DISPLAY.WORKING,
    CONVERSATION_DISPLAY.AWAITING_APPROVAL,
  ]),
  work_phase: z.enum([
    WORK_PHASE.NONE,
    WORK_PHASE.RUNNING,
    WORK_PHASE.AWAITING_APPROVAL,
  ]),
});

const ConversationFrameSchema = z.discriminatedUnion("kind", [
  EntryFrameSchema,
  EntryUpdatedFrameSchema,
  DeltaFrameSchema,
  RetractFrameSchema,
  StateFrameSchema,
]);

export type ConversationFrame = z.infer<typeof ConversationFrameSchema>;
export type DeltaFrame = z.infer<typeof DeltaFrameSchema>;
export type StateFrame = z.infer<typeof StateFrameSchema>;
export type ConversationDisplay = StateFrame["display"];
export type WorkPhase = StateFrame["work_phase"];

export type FrameParseError =
  | { kind: "invalid_json"; raw: string }
  | { kind: "invalid_frame"; raw: string; issues: string[] };

export type FrameParseResult =
  | { ok: true; frame: ConversationFrame }
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

/** Parse one `data:` line of the conversation stream into a typed frame or a typed error. */
export function parseConversationFrame(raw: string): FrameParseResult {
  const json = readJson(raw);
  if (!json.ok) return { ok: false, error: { kind: "invalid_json", raw } };
  const parsed = ConversationFrameSchema.safeParse(json.value);
  if (!parsed.success) {
    const issues = parsed.error.issues.map(
      (issue) => `${issue.path.join(".")}: ${issue.message}`,
    );
    return { ok: false, error: { kind: "invalid_frame", raw, issues } };
  }
  return { ok: true, frame: parsed.data };
}

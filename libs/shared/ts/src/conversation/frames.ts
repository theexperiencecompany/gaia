import { z } from "zod";
import type {
  ConversationUpdatedFrame,
  ItemChange,
  LiveTask,
  ReplyDeltaFrame,
  RetractFrame,
  ScreenFrame,
  ScreenInsertFrame,
  ScreenPatchFrame,
  ScreenUpdateFrame,
  StateFrame,
} from "../api/generated";
import {
  ScreenItemSchema,
  ToolTimelineSchema,
  UnfoldedCardsSchema,
} from "./entries";

/**
 * Zod mirror of the conversation event stream's frames, each tied to its generated
 * API type. A reply delta carries text for a bubble the server already split, or the
 * timeline the server folded the reply's cards to: whole from a server older than wire 2,
 * as the changes since the last one from wire 2.
 */

/** The frame shapes this build reads, sent as the events route's wire parameter. */
export const EVENTS_WIRE = 2;

export const FRAME_KIND = {
  SCREEN: "screen",
  SCREEN_INSERT: "screen_insert",
  SCREEN_UPDATE: "screen_update",
  SCREEN_PATCH: "screen_patch",
  REPLY_DELTA: "reply_delta",
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

const index = z.number().int().min(0);

const ItemChangeSchema = z.object({
  op: z.enum(["set", "append", "remove"]),
  path: z.array(z.union([z.string(), z.number().int()])),
  value: z.json(),
}) satisfies z.ZodType<ItemChange>;

const ReplyDeltaSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("bubble_text"), bubble: index, text: z.string() }),
  z.object({
    type: z.literal("cards"),
    tool_data: UnfoldedCardsSchema,
    timeline: ToolTimelineSchema,
  }),
  z.object({ type: z.literal("timeline"), changes: z.array(ItemChangeSchema) }),
  z.object({
    type: z.literal("follow_up_actions"),
    follow_up_actions: z.array(z.string()),
  }),
]) satisfies z.ZodType<ReplyDeltaFrame["payload"]>;

const LiveTaskSchema = z.object({
  task_id: z.string(),
  awaiting_approval: z.boolean(),
}) satisfies z.ZodType<LiveTask>;

const head = z.number().int().min(0);

const ScreenFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.SCREEN),
  items: z.array(ScreenItemSchema),
  head,
}) satisfies z.ZodType<ScreenFrame>;

const ScreenInsertFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.SCREEN_INSERT),
  item: ScreenItemSchema,
  head,
}) satisfies z.ZodType<ScreenInsertFrame>;

const ScreenUpdateFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.SCREEN_UPDATE),
  item: ScreenItemSchema,
  head,
}) satisfies z.ZodType<ScreenUpdateFrame>;

const ScreenPatchFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.SCREEN_PATCH),
  id: z.string().min(1),
  base: z.number().int().min(0),
  changes: z.array(ItemChangeSchema),
  head,
}) satisfies z.ZodType<ScreenPatchFrame>;

// The payload is checked against its generated union above; these tie the rest of each delta frame.
const ReplyDeltaFields = z.object({
  kind: z.literal(FRAME_KIND.REPLY_DELTA),
  attempt_id: z.string(),
  reply_id: z.string().nullable(),
  index,
}) satisfies z.ZodType<Omit<ReplyDeltaFrame, "payload">>;

const RetractFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.RETRACT),
  attempt_id: z.string(),
}) satisfies z.ZodType<RetractFrame>;

export const StateFrameSchema = z.object({
  kind: z.literal(FRAME_KIND.STATE),
  head,
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
  ScreenFrameSchema,
  ScreenInsertFrameSchema,
  ScreenUpdateFrameSchema,
  ScreenPatchFrameSchema,
  ReplyDeltaFields.extend({ payload: ReplyDeltaSchema }),
  RetractFrameSchema,
  StateFrameSchema,
  ConversationUpdatedFrameSchema,
]);

const ConversationEventSchema = z.object({ frame: ConversationFrameSchema });

export type ConversationFrame = z.infer<typeof ConversationFrameSchema>;

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
  return { ok: true, frame: parsed.data.frame };
}

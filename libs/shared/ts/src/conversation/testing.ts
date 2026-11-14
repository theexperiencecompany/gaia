import founderFrames from "./fixtures/c41f18c5.frames.json";
import { parseConversationEvent } from "./frames";
import type {
  ConversationFrame,
  DisplayState,
  LiveTask,
  ScreenItem,
} from "./types";

/** Builders for conversation frames in tests, shaped as parseConversationEvent returns their frames. */

const AT = "2026-11-12T10:00:00+00:00";

/** Parse a frame the way a client does, from the JSON the server sends. */
export function parsedFrame(event: unknown): ConversationFrame {
  const parsed = parseConversationEvent(JSON.stringify(event));
  if (!parsed.ok) throw new Error(JSON.stringify(parsed.error));
  return parsed.frame;
}

/**
 * The founder's conversation c41f18c5 (three sends, a hand-off, a quick answer, a
 * thank-you, the work's result) as the server streams it: its screen patches, from
 * apps/api's test_screen, which fails when they drift.
 */
export const founderConversationFrames = (): ConversationFrame[] =>
  founderFrames.map(parsedFrame);

const userMessageEntry = (id: string, text: string) => ({
  kind: "user_message",
  id,
  text,
  surface: "web",
});

/** A user item, its message filled in with the defaults the server's model gives it. */
export function userItem(
  id: string,
  seq: number,
  text = `text of ${id}`,
): ScreenItem {
  const frame = parsedFrame({
    frame: {
      kind: "screen_insert",
      item: {
        kind: "user",
        id,
        seq,
        at: AT,
        message: userMessageEntry(id, text),
      },
    },
  });
  if (frame.kind !== "screen_insert") throw new Error(frame.kind);
  return frame.item;
}

/** A reply item; outcome null while it is still being written. */
export const replyItem = (
  id: string,
  seq: number,
  text: string,
  outcome: string | null = null,
): Extract<ScreenItem, { kind: "reply" }> => ({
  kind: "reply",
  id,
  seq,
  at: AT,
  text,
  tool_data: [],
  follow_up_actions: [],
  image: null,
  pinned: false,
  quote: null,
  outcome: outcome as Extract<ScreenItem, { kind: "reply" }>["outcome"],
  failure: null,
  narrates: [],
  files: [],
});

/** A notice item: a proactive message delivered outside a reply. */
export const noticeItem = (
  id: string,
  seq: number,
  text: string,
): Extract<ScreenItem, { kind: "notice" }> => ({
  kind: "notice",
  id,
  seq,
  at: AT,
  text,
  tool_data: [],
  follow_up_actions: [],
});

export const insertFrame = (item: ScreenItem): ConversationFrame => ({
  kind: "screen_insert",
  item,
});

export const updateFrame = (item: ScreenItem): ConversationFrame => ({
  kind: "screen_update",
  item,
});

export const screenFrame = (items: ScreenItem[]): ConversationFrame => ({
  kind: "screen",
  items,
});

export const replyDelta = (
  attemptId: string,
  replyId: string | null,
  index: number,
  chunk: string,
): ConversationFrame => ({
  kind: "reply_delta",
  attempt_id: attemptId,
  reply_id: replyId,
  index,
  payload: { type: "response", chunk },
});

/** A tool-call progress card, as work streams it and as items carry it. */
export const toolCallCard = (callId: string, message: string) => ({
  tool_name: "tool_calls_data",
  tool_category: "gmail",
  data: { tool_name: "send", tool_call_id: callId, message },
  timestamp: AT,
});

export const workCardDelta = (
  taskId: string,
  index: number,
  message: string,
): ConversationFrame => ({
  kind: "work_delta",
  task_id: taskId,
  index,
  payload: {
    type: "tool_data",
    entry: toolCallCard(`${taskId}-${index}`, message),
  },
});

export const retractFrame = (attemptId: string): ConversationFrame => ({
  kind: "retract",
  attempt_id: attemptId,
});

export const liveTask = (
  taskId: string,
  awaitingApproval = false,
): LiveTask => ({
  task_id: taskId,
  awaiting_approval: awaitingApproval,
});

export const stateFrame = (
  head: number,
  display: DisplayState,
  work: LiveTask[] = [],
): ConversationFrame => ({ kind: "state", head, display, work });

type UserItem = Extract<ScreenItem, { kind: "user" }>;
type WorkItem = Extract<ScreenItem, { kind: "work" }>;

/** A user item whose message carries the given fields: a platform id, a reaction, files. */
export function userItemWith(
  id: string,
  seq: number,
  message: Partial<UserItem["message"]>,
): UserItem {
  const item = userItem(id, seq);
  if (item.kind !== "user") throw new Error(item.kind);
  return { ...item, message: { ...item.message, ...message } };
}

/** An approval a work item waits on. */
export const approvalAsked = (
  taskId: string,
  approvalId: string,
  summary: string,
  expiresAt: string | null = null,
): WorkItem["asking"][number] => ({
  kind: "approval_requested",
  id: `${approvalId}:asked`,
  task_id: taskId,
  approval_id: approvalId,
  summary,
  expires_at: expiresAt,
});

export const workItem = (
  taskId: string,
  seq: number,
  status: WorkItem["status"],
  asking: WorkItem["asking"] = [],
  askedSeq = asking.length > 0 ? seq : 0,
): WorkItem => ({
  kind: "work",
  id: `work:${taskId}`,
  seq,
  at: AT,
  task_id: taskId,
  status,
  asking,
  asked_seq: askedSeq,
  handoff: null,
  tool_data: [],
  image: null,
});

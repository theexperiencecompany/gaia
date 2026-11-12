import {
  type ConversationView,
  ENTRY_KIND,
  type UserMessage,
} from "@shared/conversation";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import type { MessageType } from "@/types/features/convoTypes";
import type { LocalSend } from "./liveConversationStore";
import { type LiveBubble, quoteFor, visibleBubbles } from "./selectors";

const STOPPED_WORK: ReadonlySet<string> = new Set(["cancelled", "lost"]);
const FAILED_REPLY_MESSAGE = "GAIA couldn't finish this reply.";
// Far above any one conversation's rows, so a visible row is never evicted.
const MAX_CACHED_ROWS = 2000;

/**
 * Rows keep their object identity while their inputs are unchanged, so the
 * memoized bubbles skip re-rendering on every streamed token of another row.
 */
const rowCache = new Map<string, { inputs: unknown[]; message: MessageType }>();

function stableRow(
  key: string,
  inputs: unknown[],
  build: () => MessageType,
): MessageType {
  const cached = rowCache.get(key);
  if (
    cached &&
    cached.inputs.length === inputs.length &&
    cached.inputs.every((input, at) => Object.is(input, inputs[at]))
  )
    return cached.message;
  const message = build();
  rowCache.delete(key);
  rowCache.set(key, { inputs, message });
  if (rowCache.size > MAX_CACHED_ROWS) {
    const oldest = rowCache.keys().next().value;
    if (oldest !== undefined) rowCache.delete(oldest);
  }
  return message;
}

type Quote = MessageType["replyToMessage"];

function quotedUserMessage(
  messages: ReadonlyMap<string, UserMessage>,
  id: string | null,
): Quote {
  const quoted = id ? messages.get(id) : undefined;
  return quoted
    ? { id: quoted.id, content: quoted.text, role: "user" }
    : undefined;
}

function settledOutcome(view: ConversationView, replyId: string | null) {
  if (!replyId) return null;
  const settled = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY_SETTLED && entry.reply_id === replyId,
  )?.entry;
  return settled?.kind === ENTRY_KIND.REPLY_SETTLED ? settled.outcome : null;
}

interface RowContext {
  view: ConversationView;
  sends: Readonly<Record<string, LocalSend>>;
  userMessages: ReadonlyMap<string, UserMessage>;
  dates: ReadonlyMap<number, string>;
}

function rowFor(bubble: LiveBubble, context: RowContext): MessageType | null {
  const { view, sends, userMessages, dates } = context;
  switch (bubble.kind) {
    case "user": {
      const send = sends[bubble.message.id];
      const replyTo = bubble.message.reply_to;
      return stableRow(
        bubble.key,
        [bubble.message, send, replyTo && userMessages.get(replyTo)],
        () => ({
          type: "user",
          response: bubble.message.text,
          message_id: bubble.message.id,
          seq: bubble.seq,
          date: dates.get(bubble.seq),
          fileIds: bubble.message.file_ids,
          fileData: send?.fileData,
          replyToMessage:
            send?.replyToMessage ?? quotedUserMessage(userMessages, replyTo),
          reaction: bubble.reaction,
        }),
      );
    }
    case "pending": {
      const send = sends[bubble.send.id];
      return stableRow(bubble.key, [bubble.send, send], () => ({
        type: "user",
        response: bubble.send.text,
        message_id: bubble.send.id,
        fileIds: send?.body.file_ids ?? [],
        fileData: send?.fileData,
        replyToMessage: send?.replyToMessage ?? undefined,
        loading: !send?.failed,
        failed: send?.failed ?? false,
      }));
    }
    case "reply": {
      const outcome = settledOutcome(view, bubble.replyId);
      const quoted = bubble.replyId ? quoteFor(view, bubble.replyId) : null;
      return stableRow(
        bubble.key,
        [
          bubble.text,
          bubble.toolData,
          bubble.followUpActions,
          bubble.streaming,
          outcome,
          quoted && userMessages.get(quoted),
        ],
        () => ({
          type: "bot",
          response: bubble.text,
          message_id: bubble.replyId ?? bubble.key,
          seq: bubble.seq ?? undefined,
          date: bubble.seq === null ? undefined : dates.get(bubble.seq),
          // The bubble's registry narrows tool entries by name at render.
          tool_data: bubble.toolData as TypedToolDataEntry[],
          follow_up_actions: [...bubble.followUpActions],
          in_progress: bubble.streaming,
          stopped: outcome === "stopped",
          error:
            outcome === "failed" && !bubble.text
              ? FAILED_REPLY_MESSAGE
              : undefined,
          replyToMessage: quotedUserMessage(userMessages, quoted),
        }),
      );
    }
    case "work":
      return stableRow(bubble.key, [bubble.toolData, bubble.status], () => ({
        type: "bot",
        response: "",
        message_id: bubble.key,
        seq: bubble.seq ?? undefined,
        tool_data: bubble.toolData as TypedToolDataEntry[],
        in_progress:
          bubble.status === "running" || bubble.status === "awaiting_approval",
        stopped: STOPPED_WORK.has(bubble.status),
      }));
    case "notice":
      return stableRow(bubble.key, [bubble.text], () => ({
        type: "bot",
        response: bubble.text,
        message_id: bubble.key,
        seq: bubble.seq,
        date: dates.get(bubble.seq),
      }));
    default: {
      const unhandled: never = bubble;
      return unhandled;
    }
  }
}

/** The chat screen's rows for a live conversation, in the shape the existing bubbles render. */
export function liveMessages(
  view: ConversationView,
  sends: Readonly<Record<string, LocalSend>>,
): MessageType[] {
  const userMessages = new Map<string, UserMessage>();
  const dates = new Map<number, string>();
  for (const { seq, at, entry } of view.entries) {
    dates.set(seq, at);
    if (entry.kind === ENTRY_KIND.USER_MESSAGE)
      userMessages.set(entry.id, entry);
  }
  const context = { view, sends, userMessages, dates };
  return visibleBubbles(view).flatMap(
    (bubble) => rowFor(bubble, context) ?? [],
  );
}

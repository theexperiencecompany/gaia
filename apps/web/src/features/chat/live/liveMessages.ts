import {
  type ConversationView,
  ENTRY_KIND,
  type LiveBubble,
  quoteFor,
  replyFailureMessage,
  type UserMessage,
  visibleBubbles,
} from "@shared/conversation";
import { type ApprovalSettlement, settleApprovalToolData } from "@shared/utils";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import type { MessageType } from "@/types/features/convoTypes";
import type { LocalSend } from "./liveConversationStore";

const STOPPED_WORK: ReadonlySet<string> = new Set(["cancelled", "lost"]);
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

function settlement(view: ConversationView, replyId: string | null) {
  if (!replyId) return null;
  const settled = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY_SETTLED && entry.reply_id === replyId,
  )?.entry;
  return settled?.kind === ENTRY_KIND.REPLY_SETTLED ? settled : null;
}

type Settlements = Readonly<
  Record<string, Omit<ApprovalSettlement, "conversation_id">>
>;

/** The cards with each verdict this device learned outside the log laid over them. */
function settledCards(
  cards: readonly TypedToolDataEntry[],
  settled: Settlements,
): TypedToolDataEntry[] {
  let shown = [...cards];
  for (const card of cards) {
    const approvalId = (card.data as { approval_id?: unknown } | null)
      ?.approval_id;
    const settlement =
      typeof approvalId === "string" ? settled[approvalId] : undefined;
    if (settlement)
      shown = settleApprovalToolData(shown, settlement).entries ?? shown;
  }
  return shown;
}

interface RowContext {
  view: ConversationView;
  sends: Readonly<Record<string, LocalSend>>;
  userMessages: ReadonlyMap<string, UserMessage>;
  dates: ReadonlyMap<number, string>;
  verdicts: Settlements;
}

function rowFor(bubble: LiveBubble, context: RowContext): MessageType | null {
  const { view, sends, userMessages, dates, verdicts } = context;
  switch (bubble.kind) {
    case "user": {
      const { message } = bubble;
      const replyTo = message.reply_to;
      return stableRow(
        bubble.key,
        [message, replyTo && userMessages.get(replyTo)],
        () => ({
          type: "user",
          response: message.text,
          message_id: bubble.messageId,
          seq: bubble.seq,
          date: dates.get(bubble.seq),
          fileIds: message.file_ids,
          fileData: message.files,
          selectedTool: message.selected_tool,
          toolCategory: message.tool_category,
          selectedWorkflow: message.selected_workflow,
          selectedCalendarEvent: message.selected_calendar_event,
          replyToMessage:
            message.reply_to_message ??
            quotedUserMessage(userMessages, replyTo),
          reaction: bubble.reaction,
          pinned: message.pinned,
          todo_run_wake: message.todo_run_wake ?? undefined,
        }),
      );
    }
    case "pending": {
      const send = sends[bubble.send.id];
      return stableRow(bubble.key, [bubble.send, send], () => ({
        type: "user",
        response: bubble.send.text,
        message_id: bubble.messageId,
        fileIds: send?.body.file_ids ?? [],
        fileData: send?.fileData,
        selectedTool: send?.body.selected_tool,
        toolCategory: send?.body.tool_category,
        selectedWorkflow: send?.body.selected_workflow,
        selectedCalendarEvent: send?.body.selected_calendar_event,
        replyToMessage: send?.body.reply_to_message ?? undefined,
        loading: !send?.failed,
        failed: send?.failed ?? false,
      }));
    }
    case "reply": {
      const settled = settlement(view, bubble.replyId);
      const quoted = bubble.replyId ? quoteFor(view, bubble.replyId) : null;
      return stableRow(
        bubble.key,
        [
          bubble.text,
          bubble.toolData,
          verdicts,
          bubble.followUpActions,
          bubble.streaming,
          bubble.image,
          bubble.pinned,
          settled,
          quoted && userMessages.get(quoted),
        ],
        () => ({
          type: "bot",
          response: bubble.text,
          message_id: bubble.messageId,
          seq: bubble.seq ?? undefined,
          date: bubble.seq === null ? undefined : dates.get(bubble.seq),
          // The bubble's registry narrows tool entries by name at render.
          tool_data: settledCards(
            bubble.toolData as TypedToolDataEntry[],
            verdicts,
          ),
          follow_up_actions: [...bubble.followUpActions],
          image_data: bubble.image ?? undefined,
          pinned: bubble.pinned,
          in_progress: bubble.streaming,
          stopped: settled?.outcome === "stopped",
          // With text shown, the bubble words this as the cut-short strip under it.
          error:
            settled?.outcome === "failed"
              ? replyFailureMessage(settled.failure)
              : undefined,
          replyToMessage: quotedUserMessage(userMessages, quoted),
        }),
      );
    }
    case "work":
      return stableRow(
        bubble.key,
        [bubble.toolData, bubble.status, verdicts],
        () => ({
          type: "bot",
          response: "",
          message_id: bubble.messageId,
          seq: bubble.seq ?? undefined,
          tool_data: settledCards(
            bubble.toolData as TypedToolDataEntry[],
            verdicts,
          ),
          in_progress:
            bubble.status === "running" ||
            bubble.status === "awaiting_approval",
          stopped: STOPPED_WORK.has(bubble.status),
        }),
      );
    case "notice":
      return stableRow(
        bubble.key,
        [bubble.text, bubble.toolData, verdicts],
        () => ({
          type: "bot",
          response: bubble.text,
          message_id: bubble.messageId,
          seq: bubble.seq,
          date: dates.get(bubble.seq),
          tool_data: settledCards(
            bubble.toolData as TypedToolDataEntry[],
            verdicts,
          ),
        }),
      );
    // The run's side of the chat: its card alone, as a message with no text.
    case "workflow_fired":
      return stableRow(bubble.key, [bubble.workflow], () => ({
        type: "user",
        response: "",
        message_id: bubble.messageId,
        seq: bubble.seq,
        date: dates.get(bubble.seq),
        selectedWorkflow: bubble.workflow,
      }));
    case "todo_woke":
      return stableRow(bubble.key, [bubble.wake], () => ({
        type: "user",
        response: "",
        message_id: bubble.messageId,
        seq: bubble.seq,
        date: dates.get(bubble.seq),
        todo_run_wake: bubble.wake,
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
  verdicts: Settlements = {},
): MessageType[] {
  const userMessages = new Map<string, UserMessage>();
  const dates = new Map<number, string>();
  for (const { seq, at, entry } of view.entries) {
    dates.set(seq, at);
    if (entry.kind === ENTRY_KIND.USER_MESSAGE)
      userMessages.set(entry.id, entry);
  }
  const context = { view, sends, userMessages, dates, verdicts };
  return visibleBubbles(view).flatMap(
    (bubble) => rowFor(bubble, context) ?? [],
  );
}

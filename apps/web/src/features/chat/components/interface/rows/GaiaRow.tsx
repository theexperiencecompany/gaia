import {
  REPLY_OUTCOME,
  replyFailureMessage,
  SCREEN_ITEM_KIND,
  type ScreenItem,
  type StreamDraft,
} from "@shared/conversation";
import { BASE_MESSAGE_SCHEMA } from "@/config/registries/baseMessageRegistry";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import { type RowActions, type RowLayout, STOPPED_WORK } from "./rows";

type GaiaItem = Extract<ScreenItem, { kind: "reply" | "work" | "notice" }>;

/** What one GAIA row shows, before the conversation's callbacks and its place among its neighbours. */
type GaiaContent = Partial<
  Omit<
    ChatBubbleBotProps,
    "text" | "setImageData" | "setOpenImage" | "onRetry" | "isRetrying"
  >
> & {
  message_id: string;
  bubbles: readonly string[];
  /** The item a retry starts from; null when the server names nothing to retry. */
  retryFrom: string | null;
};

// The bubble's registry narrows tool entries by name at render.
const cards = (entries: readonly unknown[]) => entries as TypedToolDataEntry[];

/** A GAIA bubble's text as one copy or search reads it: its bubbles, a blank line apart. */
const copyText = (bubbles: readonly string[]) => bubbles.join("\n\n");

function itemContent(item: GaiaItem, draft: StreamDraft | null): GaiaContent {
  switch (item.kind) {
    case SCREEN_ITEM_KIND.REPLY: {
      const streamed = draft?.content;
      return {
        message_id: item.id,
        date: item.at,
        bubbles: streamed?.bubbles ?? item.bubbles,
        tool_data: cards(streamed?.tool_data ?? item.tool_data),
        timeline: streamed?.timeline ?? item.timeline,
        follow_up_actions: [
          ...(streamed?.follow_up_actions ?? item.follow_up_actions),
        ],
        image_data: item.image ?? undefined,
        pinned: item.pinned,
        stopped: item.outcome === REPLY_OUTCOME.STOPPED,
        // With text shown, the bubble words this as the cut-short strip under it.
        error:
          item.outcome === REPLY_OUTCOME.FAILED
            ? replyFailureMessage(item.failure)
            : undefined,
        replyToMessage: item.quote ?? undefined,
        retryFrom: item.retry_target === null ? null : item.id,
      };
    }
    case SCREEN_ITEM_KIND.WORK:
      return {
        message_id: item.id,
        bubbles: [],
        tool_data: cards([
          ...(item.handoff ? [item.handoff] : []),
          ...item.tool_data,
          ...item.approvals,
        ]),
        timeline: item.timeline,
        image_data: item.image ?? undefined,
        stopped: STOPPED_WORK.has(item.status),
        retryFrom: item.retry_target === null ? null : item.id,
      };
    case SCREEN_ITEM_KIND.NOTICE:
      return {
        message_id: item.id,
        date: item.at,
        bubbles: item.bubbles,
        tool_data: cards(item.tool_data),
        timeline: item.timeline,
        follow_up_actions: [...item.follow_up_actions],
        retryFrom: null,
      };
    default: {
      const unhandled: never = item;
      return unhandled;
    }
  }
}

const draftContent = (draft: StreamDraft): GaiaContent => ({
  message_id: draft.replyId ?? `draft:${draft.attemptId}`,
  bubbles: draft.content.bubbles,
  tool_data: cards(draft.content.tool_data),
  timeline: draft.content.timeline,
  follow_up_actions: [...draft.content.follow_up_actions],
  retryFrom: null,
});

/** A GAIA row: a reply (settled or still streaming), a piece of work, or a notice. */
export function GaiaRow({
  item,
  draft,
  actions,
  layout,
}: Readonly<{
  item: GaiaItem | null;
  draft: StreamDraft | null;
  actions: RowActions;
  layout: RowLayout;
}>) {
  let content: GaiaContent | null = null;
  if (item) content = itemContent(item, draft);
  else if (draft) content = draftContent(draft);
  if (!content) return null;
  const { retryFrom, ...shown } = content;
  const quiet =
    layout.compact || layout.isGroupedWithNext || layout.suppressForBusy;
  return (
    <ChatBubbleBot
      {...BASE_MESSAGE_SCHEMA}
      {...shown}
      text={copyText(content.bubbles)}
      setImageData={actions.setImageData}
      setOpenImage={actions.setOpenImage}
      onOpenMemoryModal={actions.onOpenMemoryModal}
      isConvoSystemGenerated={actions.isConvoSystemGenerated}
      systemPurpose={actions.systemPurpose}
      onRetry={retryFrom ? () => actions.onRetry(retryFrom) : undefined}
      isRetrying={actions.isRetrying}
      disableActions={quiet}
      follow_up_actions={quiet ? undefined : content.follow_up_actions}
      date={layout.isGroupedWithNext ? undefined : content.date}
      isGroupedWithNext={layout.isGroupedWithNext}
      isGroupedWithPrev={layout.isGroupedWithPrev}
      hideAvatar={layout.compact}
    />
  );
}

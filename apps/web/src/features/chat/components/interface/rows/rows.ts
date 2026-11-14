import {
  REPLY_OUTCOME,
  SCREEN_ITEM_KIND,
  type ScreenItem,
  type ScreenRow,
  type StreamDraft,
  WORK_STATUS,
} from "@shared/conversation";
import type { Dispatch, SetStateAction } from "react";
import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type { OptimisticMessage } from "@/stores/chatStore";
import type { SetImageDataType } from "@/types/features/chatBubbleTypes";

/** A row of the chat: one the server's screen shows, or the first send of a conversation not created yet. */
export type ChatRow =
  | ScreenRow
  | { kind: "optimistic"; message: OptimisticMessage };

export const STOPPED_WORK: ReadonlySet<string> = new Set([
  WORK_STATUS.CANCELLED,
  WORK_STATUS.LOST,
]);

const USER_SIDE: ReadonlySet<string> = new Set([
  SCREEN_ITEM_KIND.USER,
  SCREEN_ITEM_KIND.WORKFLOW_FIRED,
  SCREEN_ITEM_KIND.TODO_WOKE,
]);

/** The row's id: the server item's, the reply a draft writes, or the send's own. */
export function rowId(row: ChatRow): string {
  switch (row.kind) {
    case "item":
      return row.item.id;
    case "draft":
      return row.draft.replyId ?? `draft:${row.draft.attemptId}`;
    case "pending":
      return row.send.id;
    case "optimistic":
      return row.message.id;
    default: {
      const unhandled: never = row;
      return unhandled;
    }
  }
}

/** The screen item kind the row shows: a draft is a reply still streaming, a send is the user's message. */
export function rowKind(row: ChatRow): ScreenItem["kind"] {
  if (row.kind === "item") return row.item.kind;
  return row.kind === "draft" ? SCREEN_ITEM_KIND.REPLY : SCREEN_ITEM_KIND.USER;
}

export const isUserSide = (row: ChatRow): boolean =>
  USER_SIDE.has(rowKind(row));

const hasText = (bubbles: readonly string[]) =>
  bubbles.some((bubble) => bubble.trim().length > 0);

function itemShows(item: ScreenItem, draft: StreamDraft | null): boolean {
  switch (item.kind) {
    case SCREEN_ITEM_KIND.REPLY:
      return (
        hasText(draft?.content.bubbles ?? item.bubbles) ||
        (draft?.content.toolData ?? item.tool_data).length > 0 ||
        item.image !== null ||
        item.outcome === REPLY_OUTCOME.FAILED ||
        item.outcome === REPLY_OUTCOME.STOPPED
      );
    case SCREEN_ITEM_KIND.WORK:
      return (
        item.handoff !== null ||
        item.tool_data.length > 0 ||
        item.approvals.length > 0 ||
        item.image !== null ||
        STOPPED_WORK.has(item.status)
      );
    case SCREEN_ITEM_KIND.NOTICE:
      return hasText(item.bubbles) || item.tool_data.length > 0;
    default:
      return true;
  }
}

/**
 * Whether the row draws anything: a GAIA row with no text, cards, image or
 * ending yet renders nothing, so grouping looks past it. An email-processing
 * conversation always draws its GAIA rows.
 */
export function rowShows(row: ChatRow, alwaysShowsGaia: boolean): boolean {
  if (alwaysShowsGaia && !isUserSide(row)) return true;
  switch (row.kind) {
    case "item":
      return itemShows(row.item, row.draft);
    case "draft":
      return (
        hasText(row.draft.content.bubbles) ||
        row.draft.content.toolData.length > 0
      );
    default:
      return true;
  }
}

/** What every row's bubble can do, the same for the whole conversation. */
export interface RowActions {
  setImageData: Dispatch<SetStateAction<SetImageDataType>>;
  setOpenImage: Dispatch<SetStateAction<boolean>>;
  onOpenMemoryModal: () => void;
  /** Retry from the row's item: its own message, or the one the server names as its retry target. */
  onRetry: (itemId: string) => void;
  isRetrying: boolean;
  isConvoSystemGenerated: boolean;
  systemPurpose?: SystemPurpose;
}

/** Where the row sits among its neighbours, and whether it is the turn still running. */
export interface RowLayout {
  isGroupedWithNext: boolean;
  isGroupedWithPrev: boolean;
  suppressForBusy: boolean;
  compact: boolean;
}

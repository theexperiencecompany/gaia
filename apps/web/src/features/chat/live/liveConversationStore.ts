import type { SendMessageRequest } from "@shared/api/generated";
import {
  addPendingSend,
  applyFrame,
  type ConversationFrame,
  type ConversationView,
  EMPTY_CONVERSATION_VIEW,
  type FrameOutcome,
  type LoggedEntry,
} from "@shared/conversation";
import { create } from "zustand";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

/**
 * A message this device sent: the request it POSTs (resent unchanged on retry, so the
 * server's message id dedup holds) and the attachments' display data, which the
 * request names by id only and the bubble shows before the entry arrives.
 */
/** The request as this device built it: a picked workflow carries every step's id and category. */
type LocalSendBody = Omit<SendMessageRequest, "selected_workflow"> & {
  selected_workflow?: WorkflowData | null;
};

export interface LocalSend {
  body: LocalSendBody;
  fileData: FileData[];
  failed: boolean;
}

export interface LiveConversation {
  view: ConversationView;
  sends: Readonly<Record<string, LocalSend>>;
}

const EMPTY_LIVE: LiveConversation = {
  view: EMPTY_CONVERSATION_VIEW,
  sends: {},
};

/** A frame the view could not apply where the stream must be reopened from the log. */
export type FrameGap = Exclude<FrameOutcome, { status: "applied" }>;

interface LiveConversationState {
  conversations: Readonly<Record<string, LiveConversation>>;
  /** Seed a conversation from its saved log; a conversation already live keeps what it has. */
  hydrate: (
    conversationId: string,
    entries: readonly LoggedEntry[],
    sends: Readonly<Record<string, LocalSend>>,
  ) => void;
  /** Fold frames in order; returns the first gap, after which nothing more is applied. */
  applyFrames: (
    conversationId: string,
    frames: readonly ConversationFrame[],
  ) => FrameGap | null;
  queueSend: (conversationId: string, send: LocalSend) => void;
  setSendFailed: (
    conversationId: string,
    messageId: string,
    failed: boolean,
  ) => void;
  /** Take another window's copy of a conversation as-is (the desktop popup's render-only feed). */
  mirror: (conversationId: string, live: LiveConversation) => void;
}

const fold = (
  view: ConversationView,
  frames: readonly ConversationFrame[],
): { view: ConversationView; gap: FrameGap | null } => {
  let current = view;
  for (const frame of frames) {
    const outcome = applyFrame(current, frame);
    if (outcome.status !== "applied") return { view: current, gap: outcome };
    current = outcome.view;
  }
  return { view: current, gap: null };
};

export const useLiveConversationStore = create<LiveConversationState>()(
  (set, get) => ({
    conversations: {},

    hydrate: (conversationId, entries, sends) => {
      if (get().conversations[conversationId]) return;
      const restored = fold(
        EMPTY_CONVERSATION_VIEW,
        entries.map(
          (logged): ConversationFrame => ({ kind: "entry", ...logged }),
        ),
      ).view;
      // The saved log is as far as this device knew the state; a replayed state frame moves it on.
      const known = { ...restored, head: restored.entries.at(-1)?.seq ?? 0 };
      const view = Object.entries(sends).reduce(
        (current, [id, send]) =>
          addPendingSend(current, { id, text: send.body.text }),
        known,
      );
      set((state) => ({
        conversations: {
          ...state.conversations,
          [conversationId]: { view, sends },
        },
      }));
    },

    applyFrames: (conversationId, frames) => {
      const live = get().conversations[conversationId] ?? EMPTY_LIVE;
      const { view, gap } = fold(live.view, frames);
      if (view !== live.view) {
        set((state) => ({
          conversations: {
            ...state.conversations,
            [conversationId]: { ...live, view },
          },
        }));
      }
      return gap;
    },

    queueSend: (conversationId, send) => {
      const live = get().conversations[conversationId] ?? EMPTY_LIVE;
      const id = send.body.message_id;
      set((state) => ({
        conversations: {
          ...state.conversations,
          [conversationId]: {
            view: addPendingSend(live.view, { id, text: send.body.text }),
            sends: { ...live.sends, [id]: send },
          },
        },
      }));
    },

    setSendFailed: (conversationId, messageId, failed) => {
      const live = get().conversations[conversationId];
      const send = live?.sends[messageId];
      if (!live || !send || send.failed === failed) return;
      set((state) => ({
        conversations: {
          ...state.conversations,
          [conversationId]: {
            ...live,
            sends: { ...live.sends, [messageId]: { ...send, failed } },
          },
        },
      }));
    },

    mirror: (conversationId, live) =>
      set((state) => ({
        conversations: { ...state.conversations, [conversationId]: live },
      })),
  }),
);

export const liveConversation = (conversationId: string): LiveConversation =>
  useLiveConversationStore.getState().conversations[conversationId] ??
  EMPTY_LIVE;

/** The live state of one conversation; the empty view for one not opened. */
export const useLiveConversation = (
  conversationId: string | null,
): LiveConversation =>
  useLiveConversationStore((state) =>
    conversationId
      ? (state.conversations[conversationId] ?? EMPTY_LIVE)
      : EMPTY_LIVE,
  );

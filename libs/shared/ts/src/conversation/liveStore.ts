import { create } from "zustand";
import { type ConversationPage, olderBefore } from "./history";
import type {
  ConversationFrame,
  ConversationView,
  FrameGap,
  ScreenItem,
} from "./types";
import {
  addPendingSend,
  applyFrame,
  applyPage,
  EMPTY_CONVERSATION_VIEW,
} from "./view";

/** A message this device sent: the request it POSTs (resent unchanged on retry, so the server's dedup holds). */
export interface QueuedSend {
  body: { message_id: string; text: string };
  failed: boolean;
}

export interface LiveConversation<Send extends QueuedSend> {
  view: ConversationView;
  sends: Readonly<Record<string, Send>>;
  /** The seq the next older page is read before; null once nothing older exists. */
  olderBefore: number | null;
}

/** What a device keeps of a conversation between sessions: the server's last screen, its head, its cursor and its sends. */
export interface SavedConversation<Send extends QueuedSend> {
  items: readonly ScreenItem[];
  head: number;
  olderBefore: number | null;
  sends: Readonly<Record<string, Send>>;
}

export interface LiveConversationState<Send extends QueuedSend> {
  conversations: Readonly<Record<string, LiveConversation<Send>>>;
  /** Seed a conversation from what this device saved; a conversation already live keeps what it has. */
  restore: (conversationId: string, saved: SavedConversation<Send>) => void;
  /** Take a page of the server's screen (a load, a sync, a page back) into the view. */
  applyPage: (conversationId: string, page: ConversationPage) => void;
  /** Fold frames in order; returns the first gap, after which nothing more is applied. */
  applyFrames: (
    conversationId: string,
    frames: readonly ConversationFrame[],
  ) => FrameGap | null;
  queueSend: (conversationId: string, send: Send) => void;
  setSendFailed: (
    conversationId: string,
    messageId: string,
    failed: boolean,
  ) => void;
  /** Forget a conversation and the sends it held. */
  discard: (conversationId: string) => void;
  /** Take another window's copy of a conversation as-is. */
  mirror: (conversationId: string, live: LiveConversation<Send>) => void;
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

/** One client's live conversations: each one's view from its events, and the sends this device made. */
export function createLiveConversationStore<Send extends QueuedSend>() {
  const empty: LiveConversation<Send> = {
    view: EMPTY_CONVERSATION_VIEW,
    sends: {},
    olderBefore: null,
  };

  const useLiveConversationStore = create<LiveConversationState<Send>>()(
    (set, get) => ({
      conversations: {},

      restore: (conversationId, { items, head, olderBefore, sends }) => {
        if (get().conversations[conversationId]) return;
        // The saved screen is as far as this device knew it; the stream's screen frame moves it on.
        const known = { ...EMPTY_CONVERSATION_VIEW, items, head };
        const view = Object.entries(sends).reduce(
          (current, [id, send]) =>
            addPendingSend(current, { id, text: send.body.text }),
          known,
        );
        set((state) => ({
          conversations: {
            ...state.conversations,
            [conversationId]: { view, sends, olderBefore },
          },
        }));
      },

      applyPage: (conversationId, page) => {
        const live = get().conversations[conversationId] ?? empty;
        const view = applyPage(live.view, page.items, page.state);
        set((state) => ({
          conversations: {
            ...state.conversations,
            [conversationId]: {
              ...live,
              view,
              olderBefore: olderBefore(view, page, live.olderBefore),
            },
          },
        }));
      },

      applyFrames: (conversationId, frames) => {
        const live = get().conversations[conversationId] ?? empty;
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
        const live = get().conversations[conversationId] ?? empty;
        const id = send.body.message_id;
        set((state) => ({
          conversations: {
            ...state.conversations,
            [conversationId]: {
              ...live,
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

      discard: (conversationId) =>
        set((state) => ({
          conversations: Object.fromEntries(
            Object.entries(state.conversations).filter(
              ([id]) => id !== conversationId,
            ),
          ),
        })),

      mirror: (conversationId, live) =>
        set((state) => ({
          conversations: { ...state.conversations, [conversationId]: live },
        })),
    }),
  );

  const liveConversation = (conversationId: string): LiveConversation<Send> =>
    useLiveConversationStore.getState().conversations[conversationId] ?? empty;

  /** The live state of one conversation; the empty view for one not opened. */
  const useLiveConversation = (
    conversationId: string | null,
  ): LiveConversation<Send> =>
    useLiveConversationStore((state) =>
      conversationId ? (state.conversations[conversationId] ?? empty) : empty,
    );

  return { useLiveConversationStore, liveConversation, useLiveConversation };
}

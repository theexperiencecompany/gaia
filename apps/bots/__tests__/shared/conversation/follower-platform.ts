/** The recorded platform and scripted frames every follower test drives. */
import {
  type ConversationFollower,
  type DeliveryCursor,
  type DeliveryRecorder,
  type DeliveryReport,
  type FollowStart,
  type FollowSurface,
  REACTION_OUTCOME,
  type StreamingOptions,
} from "@gaia/shared/bots";
import {
  insertFrame,
  replyDelta,
  replyItem,
  updateFrame,
  userItemWith,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type {
  ConversationFrame,
  Reaction,
} from "../../../../../libs/shared/ts/src/conversation/types";

/** One platform call the follower made. */
export type Call =
  | { op: "send"; id: string; text: string; replyTo: string | null }
  | { op: "edit"; id: string; text: string }
  | { op: "delete"; id: string }
  | { op: "react"; target: string; emoji: string; replaces: string | null }
  | { op: "typing"; state: "start"; on: string | null }
  | { op: "typing"; state: "stop" }
  | { op: "notice"; bubbles: string[] }
  | { op: "dm"; bubbles: string[] }
  | { op: "photo"; url: string; caption: string }
  | { op: "file"; path: string };

export const CONVERSATION_LINK = "https://gaia.test/c/c1";
export const PRICING_LINK = "https://gaia.test/pricing";

/** How the recorded platform behaves: a group chat, a closed message window, refused uploads. */
export interface PlatformBehaviour {
  group?: boolean;
  windowClosed?: boolean;
  refusePhoto?: () => Error;
  refuseFile?: () => Error;
}

/** A platform that records every call, editable and deletable like Telegram. */
export function recorder(behaviour: PlatformBehaviour = {}): {
  surface: FollowSurface;
  calls: Call[];
} {
  const calls: Call[] = [];
  let next = 1;
  const sendNotice = async (bubbles: string[]) => {
    calls.push({ op: "notice", bubbles });
  };
  const surface: FollowSurface = {
    sendNotice,
    sendPhoto: async (url, caption) => {
      if (behaviour.refusePhoto) throw behaviour.refusePhoto();
      calls.push({ op: "photo", url, caption });
    },
    windowClosed: async () => behaviour.windowClosed ?? false,
    links: { pricing: PRICING_LINK },
    requester: {
      sendNotice: behaviour.group
        ? async (bubbles) => {
            calls.push({ op: "dm", bubbles });
          }
        : sendNotice,
      sendPhoto: async (url, caption) => {
        if (behaviour.refusePhoto) throw behaviour.refusePhoto();
        calls.push({ op: "photo", url, caption });
      },
    },
    sendFile: async (_conversationId, file) => {
      if (behaviour.refuseFile) throw behaviour.refuseFile();
      calls.push({ op: "file", path: file.path });
    },
    send: async (text, replyTo) => {
      const id = `m${next++}`;
      calls.push({ op: "send", id, text, replyTo });
      return {
        id,
        edit: async (updated) => {
          calls.push({ op: "edit", id, text: updated });
        },
      };
    },
    reopen: (id) => ({
      id,
      edit: async (updated) => {
        calls.push({ op: "edit", id, text: updated });
      },
      delete: async () => {
        calls.push({ op: "delete", id });
      },
    }),
    react: async (target, emoji, replaces) => {
      calls.push({ op: "react", target, emoji, replaces });
      return REACTION_OUTCOME.ATTACHED;
    },
    startTyping: (on) => {
      calls.push({ op: "typing", state: "start", on });
      return () => calls.push({ op: "typing", state: "stop" });
    },
  };
  return { surface, calls };
}

// A zero edit interval previews every chunk at once, so a run is deterministic.
export const EDITING: StreamingOptions = {
  editIntervalMs: 0,
  streaming: true,
  platform: "telegram",
};
export const NON_EDITING: StreamingOptions = {
  editIntervalMs: 0,
  streaming: false,
  platform: "whatsapp",
};
export const SLACK: StreamingOptions = {
  editIntervalMs: 0,
  streaming: true,
  platform: "slack",
};

/** A follow after floor that keeps no cursor. */
export const startAfter = (floor: number): FollowStart => ({
  floor,
  partialReply: null,
  owedReactions: [],
  placedReactions: [],
  record: async () => undefined,
});
export const NOT_KEPT: DeliveryRecorder = async () => undefined;
export const cursorAt = (seq: number): DeliveryCursor => ({
  delivered_seq: seq,
  partial_reply: null,
  owed_reactions: [],
});
export const reportAt = (seq: number): DeliveryReport => ({
  delivered_seq: seq,
  partial_reply: null,
  placed_reactions: [],
});

export const sent = (calls: Call[]) =>
  calls.flatMap((call) =>
    call.op === "send" ? [{ text: call.text, replyTo: call.replyTo }] : [],
  );

/** What is on screen at the end: each message's last text. */
export function screen(calls: Call[]): string[] {
  const shown = new Map<string, string>();
  for (const call of calls) {
    if (call.op === "send" || call.op === "edit") shown.set(call.id, call.text);
    if (call.op === "delete") shown.delete(call.id);
  }
  return [...shown.values()];
}

/** Every edit that took back text a message already showed. */
export function takenBack(calls: Call[]): Call[] {
  const shown = new Map<string, string>();
  return calls.filter((call) => {
    if (call.op === "send") shown.set(call.id, call.text);
    if (call.op !== "edit") return false;
    const before = shown.get(call.id) ?? "";
    shown.set(call.id, call.text);
    return !call.text.startsWith(before);
  });
}

export async function feed(
  follower: ConversationFollower,
  frames: ConversationFrame[],
): Promise<void> {
  for (const frame of frames) await follower.apply(frame);
}

/** A user's platform message as the server's screen shows it. */
export const inbound = (
  id: string,
  seq: number,
  platformId: string,
  reaction: Reaction | null = null,
) =>
  userItemWith(id, seq, {
    surface: "telegram",
    platform_message_id: platformId,
    reaction,
  });

/** A whole reply: its item inserted with its first words, the rest streamed, then settled. */
export function answer(
  seq: number,
  replyId: string,
  text: string,
  quoteOf: string | null = null,
): ConversationFrame[] {
  const attempt = `a-${replyId}`;
  const quote = quoteOf
    ? { id: quoteOf, content: "", role: "user" as const }
    : null;
  return [
    insertFrame({ ...replyItem(replyId, seq, text.slice(0, 4)), quote }),
    replyDelta(attempt, replyId, 0, text.slice(0, 4)),
    replyDelta(attempt, replyId, 1, text.slice(4)),
    updateFrame({ ...replyItem(replyId, seq, text, "answered"), quote }),
  ];
}

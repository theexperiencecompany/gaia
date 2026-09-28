/**
 * Emoji acks in the shared bot streamer (`streamChat`).
 *
 * The backend never streams the text of a comms `<EMOJI>…</EMOJI>` turn; it
 * sends one `emoji_ack` frame carrying the bare emoji. Per-chunk adapters
 * (Slack `chat.update`, Telegram `editMessageText`) render from `onChunk` and
 * render-at-end ones (Discord, WhatsApp) from `onDone`, so the emoji must reach
 * both. Only the axios transport is faked; the streaming/parsing code is real.
 */
import { Readable } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type {
  ChatStreamClient,
  ReactionHandler,
} from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import { streamChat } from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import type { ChatRequest } from "../../../../../libs/shared/ts/src/bots/types";
import {
  REACTION_OUTCOME,
  type ReactionOutcome,
} from "../../../../../libs/shared/ts/src/bots/utils/reaction-outcome";

const REQUEST: ChatRequest = {
  message: "hi",
  platform: "slack",
  platformUserId: "U123",
  channelId: "C123",
};

function makeDeps(sseBody: string): ChatStreamClient {
  return {
    client: {
      post: vi.fn(async () => ({ data: Readable.from([sseBody]) })),
    } as unknown as ChatStreamClient["client"],
    userHeaders: () => ({}),
    storeSessionToken: vi.fn(),
    clearSessionToken: vi.fn(),
  };
}

/** Drives one scripted SSE body through the real streamer. */
async function drive(sseBody: string, onReaction?: ReactionHandler) {
  const onChunk = vi.fn();
  const onDone = vi.fn();
  const onError = vi.fn();
  await streamChat(
    makeDeps(sseBody),
    REQUEST,
    onChunk,
    onDone,
    onError,
    "/api/v1/bot/chat-stream",
    vi.fn(),
    vi.fn(),
    vi.fn(),
    onReaction,
  );
  return { onChunk, onDone, onError };
}

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

describe("streamChat — emoji acks", () => {
  it("delivers the ack's emoji as the turn's one chunk and its whole reply", async () => {
    const { onChunk, onDone, onError } = await drive(
      frames(
        { emoji_ack: { emoji: "😎", reacts_to_message_id: "u1" } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onError).not.toHaveBeenCalled();
    expect(onChunk.mock.calls.flat()).toEqual(["😎"]);
    expect(onDone).toHaveBeenCalledWith("😎", "c1");
  });

  it("forwards every text frame the moment it arrives", async () => {
    const { onChunk, onDone } = await drive(
      frames(
        { text: "<EM" },
        { text: "PHASIS> is " },
        { text: "your answer." },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onChunk.mock.calls.flat()).toEqual([
      "<EM",
      "PHASIS> is ",
      "your answer.",
    ]);
    expect(onDone.mock.calls[0][0]).toBe("<EMPHASIS> is your answer.");
  });
});

describe("streamChat — emoji ack as a native reaction", () => {
  const ACK_TURN = frames(
    { text: "<EMOJI>😅</EMOJI>" },
    { message_boundary: { message_id: "m1", discarded: false } },
    { emoji_ack: { emoji: "😅", reacts_to_message_id: "u1" } },
    { done: true, conversation_id: "c1" },
  );

  it("delivers no text once the reaction attaches", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

    const { onChunk, onDone, onError } = await drive(ACK_TURN, onReaction);

    expect(onReaction).toHaveBeenCalledExactlyOnceWith("😅");
    expect(onChunk).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledWith("", "c1");
    expect(onError).not.toHaveBeenCalled();
  });

  it.each<ReactionOutcome>([
    "platform_unsupported",
    "unmapped_emoji",
    "attach_failed",
    "no_target",
  ])(
    "delivers the emoji as the turn's text when the reaction ends %s",
    async (outcome) => {
      const { onChunk, onDone } = await drive(ACK_TURN, async () => outcome);

      expect(onChunk.mock.calls.flat()).toEqual(["😅"]);
      expect(onDone).toHaveBeenCalledWith("😅", "c1");
    },
  );

  it("does not ask to react on an ordinary reply", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

    await drive(frames({ text: "Sure." }, { done: true }), onReaction);

    expect(onReaction).not.toHaveBeenCalled();
  });
});

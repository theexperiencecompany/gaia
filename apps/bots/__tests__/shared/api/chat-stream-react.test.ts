/**
 * Reactions in the shared bot streamer (`streamChat`).
 *
 * The backend sends a `reaction` frame when GAIA reacts to the user's message:
 * first the instant pick (`by: "jev"`), then possibly the chat model's, which
 * replaces it. The adapter attaches each natively; the previous emoji travels
 * with the next so the adapter can replace it. Only the axios transport is
 * faked; the streaming/parsing code is real.
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
    onReaction,
  );
  return { onChunk, onDone, onError };
}

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

const reactionFrame = (emoji: string, by: "jev" | "chat_model") => ({
  reaction: { message_id: "u1", emoji, by },
});

describe("streamChat — reactions", () => {
  it("delivers a chat-model reaction as the turn's text when nothing can attach it", async () => {
    const { onChunk, onDone, onError } = await drive(
      frames(reactionFrame("😎", "chat_model"), {
        done: true,
        conversation_id: "c1",
      }),
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

describe("streamChat — native reactions", () => {
  const CHAT_MODEL_TURN = frames(reactionFrame("😅", "chat_model"), {
    done: true,
    conversation_id: "c1",
  });

  it("delivers no text once the chat model's reaction attaches", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

    const { onChunk, onDone, onError } = await drive(
      CHAT_MODEL_TURN,
      onReaction,
    );

    expect(onReaction).toHaveBeenCalledExactlyOnceWith("😅", null);
    expect(onChunk).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledWith("", "c1");
    expect(onError).not.toHaveBeenCalled();
  });

  it("hands the instant reaction to the adapter as the one the chat model replaces", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

    await drive(
      frames(reactionFrame("🔎", "jev"), reactionFrame("👍", "chat_model"), {
        done: true,
        conversation_id: "c1",
      }),
      onReaction,
    );

    expect(onReaction.mock.calls).toEqual([
      ["🔎", null],
      ["👍", "🔎"],
    ]);
  });

  it("keeps the turn's reply after an instant reaction", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

    const { onChunk, onDone } = await drive(
      frames(
        reactionFrame("🔎", "jev"),
        { text: "Found it." },
        {
          done: true,
          conversation_id: "c1",
        },
      ),
      onReaction,
    );

    expect(onChunk.mock.calls.flat()).toEqual(["Found it."]);
    expect(onDone).toHaveBeenCalledWith("Found it.", "c1");
  });

  it("drops an instant reaction the platform refuses instead of sending it as text", async () => {
    const onReaction = vi.fn(async () => REACTION_OUTCOME.ATTACH_FAILED);

    const { onChunk } = await drive(
      frames(
        reactionFrame("🔎", "jev"),
        { text: "Found it." },
        {
          done: true,
          conversation_id: "c1",
        },
      ),
      onReaction,
    );

    expect(onChunk.mock.calls.flat()).toEqual(["Found it."]);
  });

  it.each<ReactionOutcome>([
    "platform_unsupported",
    "unmapped_emoji",
    "attach_failed",
    "no_target",
  ])(
    "delivers the chat model's emoji as the turn's text when the reaction ends %s",
    async (outcome) => {
      const { onChunk, onDone } = await drive(
        CHAT_MODEL_TURN,
        async () => outcome,
      );

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

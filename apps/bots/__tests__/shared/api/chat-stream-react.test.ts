/**
 * Emoji-directive suppression in the shared bot streamer (`streamChat`).
 *
 * The server streams comms' `<EMOJI>…</EMOJI>` control tag as ordinary text,
 * then follows with an `emoji_ack` frame carrying the bare emoji. Per-chunk
 * adapters (Slack `chat.update`, Telegram `editMessageText`) paint every
 * `onChunk` immediately, so forwarding the directive leaks `<EMOJI>😎</EMOJI>` into
 * the chat. The streamer must hold directive-shaped text back and deliver the
 * emoji instead — on every platform, streaming or render-at-end.
 *
 * Only the axios transport is faked; the streaming/parsing code is real.
 */
import { Readable } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type { ChatStreamClient } from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import { streamChat } from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import type { ChatRequest } from "../../../../../libs/shared/ts/src/bots/types";

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
async function drive(sseBody: string) {
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
  );
  return { onChunk, onDone, onError };
}

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

describe("streamChat — emoji directive suppression", () => {
  it("never forwards the directive, split across chunks, and delivers the emoji", async () => {
    const { onChunk, onDone, onError } = await drive(
      frames(
        { text: "<EMO" },
        { text: "JI>😎</EMOJI>" },
        { emoji_ack: { emoji: "😎", reacts_to_message_id: "u1" } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onError).not.toHaveBeenCalled();
    // The only chunk any adapter ever sees is the emoji itself.
    expect(onChunk).toHaveBeenCalledTimes(1);
    expect(onChunk).toHaveBeenCalledWith("😎");
    // Render-at-end platforms (Discord/WhatsApp) deliver from fullText.
    expect(onDone).toHaveBeenCalledWith("😎", "c1");
  });

  it.each(["<EMOJI>👍</EMOJI>", "REACT: 👍"])(
    "suppresses the single-frame directive %j the same way",
    async (directive) => {
      const { onChunk, onDone } = await drive(
        frames(
          { text: directive },
          { emoji_ack: { emoji: "👍", reacts_to_message_id: "u1" } },
          { done: true, conversation_id: "c1" },
        ),
      );

      expect(onChunk).toHaveBeenCalledTimes(1);
      expect(onChunk).toHaveBeenCalledWith("👍");
      expect(onDone).toHaveBeenCalledWith("👍", "c1");
    },
  );

  it("holds a lookalike prefix, then flushes it whole once disambiguated", async () => {
    const { onChunk, onDone } = await drive(
      frames(
        { text: "<EM" },
        { text: "PHASIS> completed" },
        { done: true, conversation_id: "c1" },
      ),
    );

    // "<EM" could still become the directive, so nothing is forwarded until
    // "PHASIS> completed" proves it is an ordinary reply — then all of it at once.
    expect(onChunk.mock.calls.flat()).toEqual(["<EMPHASIS> completed"]);
    expect(onDone.mock.calls[0][0]).toBe("<EMPHASIS> completed");
  });

  it.each(["<EMOJI></EMOJI>", "<EMOJI> </EMOJI><NEW_MESSAGE_BREAK>", "REACT:"])(
    "flushes %j through onChunk at completion — the backend sends it as a reply, with no ack",
    async (text) => {
      const { onChunk, onDone } = await drive(
        frames(
          { text },
          { message_boundary: { message_id: "m1", discarded: false } },
          { done: true, conversation_id: "c1" },
        ),
      );

      expect(onChunk.mock.calls.flat().join("")).toBe(text);
      expect(onDone).toHaveBeenCalledWith(text, "c1");
    },
  );

  it("forwards a directive-shaped later message, since the whole turn is not a directive", async () => {
    const { onChunk } = await drive(
      frames(
        { text: "Sure." },
        { message_boundary: { message_id: "m1", discarded: false } },
        { text: "<EMOJI>👍</EMOJI>" },
        { message_boundary: { message_id: "m2", discarded: false } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onChunk.mock.calls.flat()).toEqual(["Sure.", "<EMOJI>👍</EMOJI>"]);
  });

  it("releases a held lookalike before its boundary, so it stays in its own bubble", async () => {
    const events: string[] = [];
    await streamChat(
      makeDeps(
        frames(
          { text: "Re" },
          { message_boundary: { message_id: "m1", discarded: false } },
          { text: "Sure." },
          { done: true, conversation_id: "c1" },
        ),
      ),
      REQUEST,
      (chunk) => {
        events.push(`chunk:${chunk}`);
      },
      vi.fn(),
      vi.fn(),
      "/api/v1/bot/chat-stream",
      vi.fn(),
      (discarded) => {
        events.push(`boundary:${discarded}`);
      },
      vi.fn(),
    );

    expect(events).toEqual(["chunk:Re", "boundary:false", "chunk:Sure."]);
  });

  it("keeps holding the directive across its kept boundary until the ack replaces it", async () => {
    const { onChunk, onDone } = await drive(
      frames(
        { text: "<EMOJI>👍</EMOJI>" },
        { message_boundary: { message_id: "m1", discarded: false } },
        { emoji_ack: { emoji: "👍", reacts_to_message_id: "u1" } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onChunk.mock.calls.flat()).toEqual(["👍"]);
    expect(onDone).toHaveBeenCalledWith("👍", "c1");
  });

  it("still forwards an ordinary reply untouched", async () => {
    const { onChunk, onDone } = await drive(
      frames(
        { text: "Here is " },
        { text: "your answer." },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onChunk.mock.calls.flat()).toEqual(["Here is ", "your answer."]);
    expect(onDone.mock.calls[0][0]).toBe("Here is your answer.");
  });
});

/**
 * Tests for the bot SSE client's mid-stream failure handling.
 *
 * Regression context: on 2026-08-18 nginx hung up on two Discord turns after
 * 60s of silence. The bot had already received 10 text frames, but the error
 * path discarded them and posted a generic error card instead — and because
 * Discord renders only at `onDone`, the user saw nothing of a reply that had
 * fully arrived.
 */
import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type { BotUserContext, ChatRequest } from "../types";
import { streamChat } from "./chat-stream";

const REQUEST: ChatRequest = {
  message: "hi",
  platform: "discord",
  platformUserId: "u1",
  channelId: "c1",
};

function frame(payload: Record<string, unknown>): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/** A response stream that emits `frames`, then dies with `error` mid-flight. */
function dyingStream(frames: string[], error: Error): PassThrough {
  const stream = new PassThrough();
  setImmediate(() => {
    for (const f of frames) stream.write(f);
    setTimeout(() => stream.emit("error", error), 10);
  });
  return stream;
}

function deps(stream: PassThrough) {
  return {
    client: { post: vi.fn().mockResolvedValue({ data: stream }) },
    userHeaders: (_ctx: BotUserContext) => ({}),
    storeSessionToken: vi.fn(),
    clearSessionToken: vi.fn(),
  } as unknown as Parameters<typeof streamChat>[0];
}

async function run(stream: PassThrough) {
  const onChunk = vi.fn();
  const onDone = vi.fn();
  const onError = vi.fn();
  await streamChat(
    deps(stream),
    REQUEST,
    onChunk,
    onDone,
    onError,
    "/bot/chat-stream",
    undefined,
    0,
  ).catch(() => undefined);
  return { onChunk, onDone, onError };
}

describe("streamChat mid-stream abort", () => {
  it("delivers the text already received when the connection dies", async () => {
    const stream = dyingStream(
      [frame({ text: "Hello " }), frame({ text: "world" })],
      new Error("aborted"),
    );

    const { onDone, onError } = await run(stream);

    expect(onDone).toHaveBeenCalledWith("Hello world", "");
    expect(onError).not.toHaveBeenCalled();
  });

  it("surfaces an error when the connection dies before any content", async () => {
    const stream = dyingStream([], new Error("aborted"));

    const { onDone, onError } = await run(stream);

    expect(onDone).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
  });

  it("still reports a clean end-of-stream with no content as an error", async () => {
    const stream = new PassThrough();
    setImmediate(() => stream.end());

    const { onDone, onError } = await run(stream);

    expect(onDone).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalled();
  });
});

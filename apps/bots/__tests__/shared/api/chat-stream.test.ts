/**
 * The SSE frame contract with `POST /api/v1/bot/chat-stream`.
 *
 * The backend refuses a turn before any work with a single terminal frame —
 * `data: {"error":"<code>"}` — instead of an HTTP status, because bots read the
 * response as a stream. Everything downstream (the auth prompt, the upgrade
 * prompt in handleStreamingChat) switches on that code arriving at `onError`
 * verbatim, so this pins the wire codes against the real parser. Only the axios
 * transport is faked; the streaming/parsing code under test is real.
 */

import { Readable } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import type { ChatStreamClient } from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import { streamChat } from "../../../../../libs/shared/ts/src/bots/api/chat-stream";
import type { ChatRequest } from "../../../../../libs/shared/ts/src/bots/types";

const REQUEST: ChatRequest = {
  message: "hi",
  platform: "imessage",
  platformUserId: "+15550001111",
  channelId: "space-1",
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
  const onApproval = vi.fn();
  const onBoundary = vi.fn();
  const onNotice = vi.fn();
  await streamChat(
    makeDeps(sseBody),
    REQUEST,
    onChunk,
    onDone,
    onError,
    "/api/v1/bot/chat-stream",
    onApproval,
    onBoundary,
    onNotice,
  );
  return { onChunk, onDone, onError, onBoundary, onNotice };
}

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

const NOTICE = "You've reached your chat limit. Please try again later.";

async function driveRefusal(code: string) {
  const onChunk = vi.fn();
  const onDone = vi.fn();
  const onError = vi.fn();
  await streamChat(
    makeDeps(`data: ${JSON.stringify({ error: code })}\n\n`),
    REQUEST,
    onChunk,
    onDone,
    onError,
    "/api/v1/bot/chat-stream",
  );
  return { onChunk, onDone, onError };
}

describe("streamChat — SSE refusal frames", () => {
  it.each(["not_authenticated", "plan_required"])(
    "surfaces the %s code to onError verbatim, with no content delivered",
    async (code) => {
      const { onChunk, onDone, onError } = await driveRefusal(code);

      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
      expect(onError.mock.calls[0][0].message).toBe(code);
      expect(onChunk).not.toHaveBeenCalled();
      expect(onDone).not.toHaveBeenCalled();
    },
  );
});

describe("streamChat — the rate-limit notice", () => {
  it("delivers the notice out of band, never as part of the reply", async () => {
    const { onChunk, onNotice, onDone } = await drive(
      frames(
        { text: "looking that up" },
        { notice: { text: NOTICE } },
        { text: " — here it is" },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onNotice).toHaveBeenCalledWith(NOTICE);
    expect(onChunk.mock.calls.flat()).not.toContain(NOTICE);
    expect(onDone.mock.calls[0][0]).not.toContain(NOTICE);
  });

  it("survives the message it arrived inside being discarded", async () => {
    // The bug: the notice used to ride the stream as a plain {"text"} frame, so
    // it joined whatever assistant message was in flight — and a discarded
    // message (a handoff preamble, a rewritten draft) took the notice down with
    // it. The user hit a limit and was told nothing.
    const { onNotice, onDone } = await drive(
      frames(
        { text: "let me get that set up" },
        { notice: { text: NOTICE } },
        { message_boundary: { message_id: "m1", discarded: true } },
        { text: "all set." },
        { message_boundary: { message_id: "m2", discarded: false } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onNotice).toHaveBeenCalledWith(NOTICE);
    expect(onDone.mock.calls[0][0]).toBe("all set.");
  });
});

describe("streamChat — the 401 session-token retry", () => {
  it("keeps every handler on the retried attempt", async () => {
    // The retry re-invoked the streamer with `onApprovalUpdate` and the
    // boundary handler but not `onNotice`, so a stale session token — routine,
    // the token lives 12 minutes — silently cost that turn its rate-limit
    // notice. Nothing failed; the user just hit a wall and was told nothing.
    const body = frames(
      { notice: { text: NOTICE } },
      { text: "all set." },
      { done: true, conversation_id: "c1" },
    );
    let attempt = 0;
    const deps: ChatStreamClient = {
      client: {
        post: vi.fn(async () => {
          attempt += 1;
          if (attempt === 1) throw { response: { status: 401 } };
          return { data: Readable.from([body]) };
        }),
      } as unknown as ChatStreamClient["client"],
      userHeaders: () => ({}),
      storeSessionToken: vi.fn(),
      clearSessionToken: vi.fn(),
    };

    const onNotice = vi.fn();
    await streamChat(
      deps,
      REQUEST,
      vi.fn(),
      vi.fn(),
      vi.fn(),
      "/api/v1/bot/chat-stream",
      vi.fn(),
      vi.fn(),
      onNotice,
    );

    expect(attempt).toBe(2);
    expect(onNotice).toHaveBeenCalledWith(NOTICE);
  });
});

describe("streamChat — a chunk carrying several frames", () => {
  it("applies every frame in it, even when the stream ends immediately", async () => {
    // SSE frames coalesce into one TCP chunk all the time, and a short reply
    // arrives in a single chunk followed straight away by `end`. Applying a
    // chunk is async — every handler may await — so `end` used to fire mid-loop
    // and flip the done flag, and every frame after the first `await` was
    // dropped on the floor: the notice, the boundary, and the rest of the text.
    const { onChunk, onNotice, onBoundary, onDone } = await drive(
      frames(
        { text: "one" },
        { notice: { text: NOTICE } },
        { text: "two" },
        { message_boundary: { message_id: "m1", discarded: true } },
        { text: "three" },
        { message_boundary: { message_id: "m2", discarded: false } },
        { done: true, conversation_id: "c1" },
      ),
    );

    expect(onChunk.mock.calls.flat()).toEqual(["one", "two", "three"]);
    expect(onNotice).toHaveBeenCalledTimes(1);
    // Both boundaries are announced: the retraction, and the kept one that
    // tells a bot its message is final and may now be split into bubbles.
    expect(onBoundary.mock.calls.flat()).toEqual([true, false]);
    expect(onDone).toHaveBeenCalledWith("three", "c1");
  });
});

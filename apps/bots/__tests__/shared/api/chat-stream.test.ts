/**
 * The SSE refusal contract with `POST /api/v1/bot/chat-stream`.
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

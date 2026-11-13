// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";

const FRAME = '{"stream_id":"1-0","frame":{"kind":"state"}}';

function eventStream(body: string): Response {
  const bytes = new TextEncoder().encode(body);
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

describe("chatApi conversation events", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hands over each data line and never a keepalive comment", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        eventStream(
          `: keepalive\n\nid: 1-0\ndata: ${FRAME}\n\n: keepalive\n\n`,
        ),
      ),
    );
    const received: string[] = [];

    await chatApi.subscribeToConversationEvents(
      "c1",
      0,
      (raw) => received.push(raw),
      new AbortController().signal,
    );

    expect(received).toEqual([FRAME]);
  });
});

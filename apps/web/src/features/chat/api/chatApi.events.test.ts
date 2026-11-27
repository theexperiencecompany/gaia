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
      (raw) => received.push(raw),
      new AbortController().signal,
      null,
    );

    expect(received).toEqual([FRAME]);
  });

  it("asks for wire 2, and for only what changed since the head it reached on a reconnect", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      eventStream(": keepalive\n\n"),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { signal } = new AbortController();

    await chatApi.subscribeToConversationEvents("c1", vi.fn(), signal, null);
    await chatApi.subscribeToConversationEvents("c1", vi.fn(), signal, 41);

    const queries = fetchMock.mock.calls.map(([url]) => new URL(url).search);
    expect(queries).toEqual(["?wire=2", "?wire=2&after=41"]);
  });
});

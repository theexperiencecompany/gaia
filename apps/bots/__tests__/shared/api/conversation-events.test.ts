/**
 * The bot's reader of a conversation's events stream, fed the bytes a
 * connection hands it: whole events, events cut anywhere, and one event far
 * larger than a network chunk.
 */
import { Readable } from "node:stream";
import { describe, expect, it } from "vitest";
import { readConversationEvents } from "../../../../../libs/shared/ts/src/bots/api/conversation-events";
import {
  noticeItem,
  screenFrame,
  stateFrame,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../../libs/shared/ts/src/conversation/types";

const sse = (frame: ConversationFrame): string =>
  `data: ${JSON.stringify({ frame })}\n\n`;

/** The frames the reader yields for a response body delivered as these chunks. */
async function framesOf(chunks: Buffer[]): Promise<ConversationFrame[]> {
  const client = {
    get: async () => ({ data: Readable.from(chunks) }),
  } as unknown as Parameters<typeof readConversationEvents>[0];
  const frames: ConversationFrame[] = [];
  for await (const frame of readConversationEvents(
    client,
    {},
    "conversation-1",
    new AbortController().signal,
  )) {
    frames.push(frame);
  }
  return frames;
}

function cut(bytes: Buffer, size: number): Buffer[] {
  const chunks: Buffer[] = [];
  for (let at = 0; at < bytes.length; at += size) {
    chunks.push(bytes.subarray(at, at + size));
  }
  return chunks;
}

const SCREEN = screenFrame([noticeItem("n1", 3, "Your brief is ready")]);
const IDLE = stateFrame(3, "idle");

describe("readConversationEvents", () => {
  it("yields each frame of a body that arrives whole", async () => {
    const body = Buffer.from(`${sse(SCREEN)}: keepalive\n\n${sse(IDLE)}`);
    expect(await framesOf([body])).toEqual([SCREEN, IDLE]);
  });

  it("yields the same frames wherever the connection cuts the body", async () => {
    const body = Buffer.from(`${sse(SCREEN)}: keepalive\n\n${sse(IDLE)}`);
    for (let size = 1; size <= 7; size += 1) {
      expect(await framesOf(cut(body, size))).toEqual([SCREEN, IDLE]);
    }
  });

  it("reads events a proxy ended with CRLF, cut between the CR and the LF", async () => {
    const body = Buffer.from(
      `${sse(SCREEN)}${sse(IDLE)}`.replaceAll("\n", "\r\n"),
    );
    for (let size = 1; size <= 7; size += 1) {
      expect(await framesOf(cut(body, size))).toEqual([SCREEN, IDLE]);
    }
  });

  it("keeps a character whose bytes arrive in two chunks", async () => {
    const screen = screenFrame([noticeItem("n1", 3, "Café ☕ नमस्ते 🚀")]);
    const body = Buffer.from(sse(screen));
    for (let size = 1; size <= 5; size += 1) {
      expect(await framesOf(cut(body, size))).toEqual([screen]);
    }
  });

  it("reads one large event in time that does not grow with how finely it is cut", async () => {
    const screen = screenFrame([
      noticeItem("n1", 3, "é".repeat(4 * 1024 * 1024)),
    ]);
    const body = Buffer.from(sse(screen));
    const fastest = async (chunks: Buffer[]): Promise<number> => {
      let best = Number.POSITIVE_INFINITY;
      for (let run = 0; run < 3; run += 1) {
        const started = performance.now();
        const frames = await framesOf(chunks);
        best = Math.min(best, performance.now() - started);
        expect(frames).toHaveLength(1);
      }
      return best;
    };
    const whole = await fastest([body]);
    const pieces = await fastest(cut(body, 2048));
    // a reader that rescans what it holds on every chunk takes seconds here, not milliseconds
    expect(pieces).toBeLessThan(5 * whole + 100);
  });
});

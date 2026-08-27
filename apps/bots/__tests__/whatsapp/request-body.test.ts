/**
 * Tests for the bounded webhook body reader (memory-exhaustion DoS guard).
 *
 * Covered behaviors of readBodyBounded:
 * 1.  Returns the decoded string for a body under the cap
 * 2.  Accepts a body whose size is exactly the cap
 * 3.  Returns BODY_TOO_LARGE for a body one byte over the cap
 * 4.  Returns BODY_TOO_LARGE when the overflow spans multiple chunks, and
 *     cancels the stream instead of buffering the rest
 * 5.  Concatenates multiple chunks in order
 * 6.  Decodes UTF-8 byte-for-byte even when a multi-byte char is split across
 *     chunks (required so the raw body re-encodes identically for the HMAC check)
 * 7.  Returns "" when there is no body
 * 8.  Returns BODY_READ_TIMEOUT when a stalled stream blows the read deadline
 */

import {
  BODY_READ_TIMEOUT,
  BODY_TOO_LARGE,
  readBodyBounded,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";

const enc = new TextEncoder();

/** Build a minimal Request-like object streaming the given byte chunks. */
function requestOf(...chunks: Uint8Array[]): Request {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
  return { body: stream } as unknown as Request;
}

describe("readBodyBounded", () => {
  it("returns the decoded string for a body under the cap", async () => {
    const result = await readBodyBounded(requestOf(enc.encode("hello")), 100);
    expect(result).toBe("hello");
  });

  it("accepts a body exactly at the cap", async () => {
    const body = "0123456789"; // 10 bytes
    const result = await readBodyBounded(requestOf(enc.encode(body)), 10);
    expect(result).toBe(body);
  });

  it("rejects a body one byte over the cap", async () => {
    const result = await readBodyBounded(
      requestOf(enc.encode("01234567890")),
      10,
    );
    expect(result).toBe(BODY_TOO_LARGE);
  });

  it("rejects and cancels the stream when overflow spans multiple chunks", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(enc.encode("aaaaaa")); // 6 bytes (under cap)
        controller.enqueue(enc.encode("bbbbbb")); // +6 = 12 (over cap 10)
        controller.enqueue(enc.encode("cccccc")); // must never be read
      },
      cancel,
    });
    const request = { body: stream } as unknown as Request;

    const result = await readBodyBounded(request, 10);

    expect(result).toBe(BODY_TOO_LARGE);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("concatenates multiple chunks in order", async () => {
    const result = await readBodyBounded(
      requestOf(enc.encode("ab"), enc.encode("cd"), enc.encode("ef")),
      100,
    );
    expect(result).toBe("abcdef");
  });

  it("decodes a multi-byte char split across chunks byte-for-byte", async () => {
    // "€" is E2 82 AC. Splitting it across chunks must still decode correctly,
    // because bytes are accumulated and decoded once — not per chunk.
    const euro = enc.encode("€");
    expect(euro).toEqual(new Uint8Array([0xe2, 0x82, 0xac]));

    const result = await readBodyBounded(
      requestOf(euro.slice(0, 2), euro.slice(2)),
      100,
    );

    expect(result).toBe("€");
    // Round-trips to the identical bytes — what the HMAC signature is computed over.
    expect(enc.encode(result as string)).toEqual(euro);
  });

  it("returns an empty string when there is no body", async () => {
    const result = await readBodyBounded(
      { body: null } as unknown as Request,
      100,
    );
    expect(result).toBe("");
  });

  it("returns BODY_READ_TIMEOUT when the stream stalls past the deadline", async () => {
    // A source-less stream never enqueues or closes: read() would block
    // forever. The deadline must cancel the reader and unblock the loop.
    const stream = new ReadableStream<Uint8Array>();
    const request = { body: stream } as unknown as Request;

    const result = await readBodyBounded(request, 1000, 50);

    expect(result).toBe(BODY_READ_TIMEOUT);
  });
});

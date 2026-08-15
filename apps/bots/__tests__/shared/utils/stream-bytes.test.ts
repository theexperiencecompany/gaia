import { readStreamBytesCapped } from "@gaia/shared";
import { describe, expect, it } from "vitest";

function finiteStream(chunks: Uint8Array[]): {
  stream: ReadableStream<Uint8Array>;
  cancelled: () => boolean;
} {
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  return { stream, cancelled: () => cancelled };
}

function endlessStream(chunkSize: number): {
  stream: ReadableStream<Uint8Array>;
  produced: () => number;
  cancelled: () => boolean;
} {
  let produced = 0;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      produced += chunkSize;
      controller.enqueue(new Uint8Array(chunkSize).fill(7));
    },
    cancel() {
      cancelled = true;
    },
  });
  return { stream, produced: () => produced, cancelled: () => cancelled };
}

describe("readStreamBytesCapped", () => {
  it("returns every byte of a stream that fits under the cap", async () => {
    const { stream, cancelled } = finiteStream([
      new Uint8Array([1, 2]),
      new Uint8Array([3]),
    ]);
    const read = await readStreamBytesCapped(stream, 64);
    expect(read.bytes).toEqual(new Uint8Array([1, 2, 3]));
    expect(read.timedOut).toBe(false);
    expect(cancelled()).toBe(false);
  });

  it("stops at the cap and cancels a stream that has more to give", async () => {
    const { stream, produced, cancelled } = endlessStream(256);
    const read = await readStreamBytesCapped(stream, 1000);
    expect(read.bytes.byteLength).toBe(1000);
    expect(cancelled()).toBe(true);
    expect(produced()).toBeLessThanOrEqual(1000 + 2 * 256);
  });

  it("truncates mid-chunk rather than buffering the whole chunk", async () => {
    const { stream } = finiteStream([new Uint8Array(4096).fill(9)]);
    const read = await readStreamBytesCapped(stream, 10);
    expect(read.bytes).toEqual(new Uint8Array(10).fill(9));
  });

  it("releases a still-open stream once the cap is reached exactly", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(64));
      },
      cancel() {
        cancelled = true;
      },
    });
    const read = await readStreamBytesCapped(stream, 64);
    expect(read.bytes.byteLength).toBe(64);
    expect(cancelled).toBe(true);
  });

  it("reports a timeout and cancels when the producer stalls", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });
    const read = await readStreamBytesCapped(stream, 1024, 20);
    expect(read.timedOut).toBe(true);
    expect(read.bytes).toEqual(new Uint8Array(0));
    expect(cancelled).toBe(true);
  });

  it("propagates a rejection from the timeout cancellation", async () => {
    const failure = new Error("cancel exploded");
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        return Promise.reject(failure);
      },
    });
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", onUnhandled);
    try {
      await expect(readStreamBytesCapped(stream, 1024, 20)).rejects.toBe(
        failure,
      );
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", onUnhandled);
    }
  });

  it("propagates a rejection from the at-cap cancellation", async () => {
    const failure = new Error("cancel exploded at the cap");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(64));
      },
      cancel() {
        return Promise.reject(failure);
      },
    });
    await expect(readStreamBytesCapped(stream, 8)).rejects.toBe(failure);
  });

  it("does not arm a deadline when none is given", async () => {
    const { stream } = finiteStream([new Uint8Array([1])]);
    const read = await readStreamBytesCapped(stream, 8);
    expect(read.timedOut).toBe(false);
  });
});

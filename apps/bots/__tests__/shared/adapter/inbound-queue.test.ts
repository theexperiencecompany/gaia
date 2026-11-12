import { PerUserInboundQueue } from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

/** A handler that stays running until release() is called. */
function held(): { handle: () => Promise<void>; release: () => void } {
  let release = (): void => undefined;
  const done = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { handle: () => done, release };
}

/** Lets every already-settled promise callback run. */
const flush = () => new Promise((resolve) => setImmediate(resolve));

describe("PerUserInboundQueue", () => {
  it("handles a /stop behind a held message at once", async () => {
    const queue = new PerUserInboundQueue();
    const work = held();
    const order: string[] = [];

    void queue.enqueue("u1", "do the work", work.handle);
    void queue.enqueue("u1", "/stop", async () => {
      order.push("/stop");
    });
    await flush();

    expect(order).toEqual(["/stop"]);
    work.release();
  });

  it.each(["/stop@gaiabot", "/STOP", "  /stop now"])(
    "reads %j as /stop",
    async (text) => {
      const queue = new PerUserInboundQueue();
      const work = held();
      let stopped = false;

      void queue.enqueue("u1", "do the work", work.handle);
      void queue.enqueue("u1", text, async () => {
        stopped = true;
      });
      await flush();

      expect(stopped).toBe(true);
      work.release();
    },
  );

  it.each(["and then this", "/new", "/stopwatch", "please /stop", undefined])(
    "keeps %j behind the held message",
    async (text) => {
      const queue = new PerUserInboundQueue();
      const work = held();
      const order: string[] = [];

      void queue.enqueue("u1", "do the work", async () => {
        await work.handle();
        order.push("work");
      });
      const next = queue.enqueue("u1", text, async () => {
        order.push("next");
      });
      await flush();
      expect(order).toEqual([]);

      work.release();
      await next;
      expect(order).toEqual(["work", "next"]);
    },
  );

  it("does not hold one sender's messages behind another's", async () => {
    const queue = new PerUserInboundQueue();
    const work = held();
    let handled = false;

    void queue.enqueue("u1", "do the work", work.handle);
    await queue.enqueue("u2", "hello", async () => {
      handled = true;
    });

    expect(handled).toBe(true);
    work.release();
  });

  it("runs the next message after a failed one and reports the failure to its caller", async () => {
    const queue = new PerUserInboundQueue();

    const failed = queue.enqueue("u1", "boom", async () => {
      throw new Error("handler failed");
    });
    let handled = false;
    const next = queue.enqueue("u1", "after", async () => {
      handled = true;
    });

    await expect(failed).rejects.toThrow("handler failed");
    await next;
    expect(handled).toBe(true);
  });

  it("settles once every queued message has been handled", async () => {
    const queue = new PerUserInboundQueue();
    const work = held();
    let settled = false;

    void queue.enqueue("u1", "do the work", work.handle);
    void queue.settled().then(() => {
      settled = true;
    });
    await flush();
    expect(settled).toBe(false);

    work.release();
    await flush();
    expect(settled).toBe(true);
  });
});

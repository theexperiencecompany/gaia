/**
 * One sender's posts reach the API in the order the messages arrived, while
 * only the post itself is held: never a reply, never a command.
 */
import { describe, expect, it } from "vitest";
import { ArrivalOrder } from "../../../../../libs/shared/ts/src/bots/adapter/arrival-order";

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ArrivalOrder", () => {
  it("posts the first message first when its pre-post work outlasts the second's", async () => {
    const order = new ArrivalOrder();
    const posted: string[] = [];
    const welcome = deferred();

    // The first message is still in its link-code check and welcome when the second arrives.
    const first = order.run("u1", async () => {
      await welcome.promise;
      await order.post(async () => {
        posted.push("first");
      });
    });
    const second = order.run("u1", () =>
      order.post(async () => {
        posted.push("second");
      }),
    );
    await flush();
    expect(posted).toEqual([]);

    welcome.resolve();
    await Promise.all([first, second]);
    expect(posted).toEqual(["first", "second"]);
  });

  it("holds the next post only until the earlier post returns, not for its reply", async () => {
    const order = new ArrivalOrder();
    const posted: string[] = [];
    const reply = deferred();

    const first = order.run("u1", async () => {
      await order.post(async () => {
        posted.push("first");
      });
      await reply.promise; // the follow, rendering the reply long after the post
    });
    const second = order.run("u1", () =>
      order.post(async () => {
        posted.push("second");
      }),
    );
    await second;
    expect(posted).toEqual(["first", "second"]);
    reply.resolve();
    await first;
  });

  it("lets a later message past a command that posts nothing, /stop included", async () => {
    const order = new ArrivalOrder();
    const posted: string[] = [];
    const stopping = deferred();

    const stop = order.run("u1", async () => {
      order.release();
      await stopping.promise; // the stop call still in flight
    });
    const next = order.run("u1", () =>
      order.post(async () => {
        posted.push("next");
      }),
    );
    await next;
    expect(posted).toEqual(["next"]);
    stopping.resolve();
    await stop;
  });

  it("frees the place of a message whose post failed", async () => {
    const order = new ArrivalOrder();
    const posted: string[] = [];
    const failed = order.run("u1", () =>
      order.post(async () => {
        throw new Error("503");
      }),
    );
    const next = order.run("u1", () =>
      order.post(async () => {
        posted.push("next");
      }),
    );
    await expect(failed).rejects.toThrow("503");
    await next;
    expect(posted).toEqual(["next"]);
  });

  it("never orders one sender behind another", async () => {
    const order = new ArrivalOrder();
    const posted: string[] = [];
    const slow = deferred();
    const first = order.run("u1", async () => {
      await slow.promise;
      await order.post(async () => {
        posted.push("u1");
      });
    });
    await order.run("u2", () =>
      order.post(async () => {
        posted.push("u2");
      }),
    );
    expect(posted).toEqual(["u2"]);
    slow.resolve();
    await first;
  });
});

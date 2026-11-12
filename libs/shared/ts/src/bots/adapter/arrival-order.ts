/**
 * Posts one sender's messages in the order they arrived.
 *
 * The server numbers a message when it accepts the post, so two quick messages
 * must reach it in arrival order even when the first spends longer before its
 * post (a link-code check, a welcome, a media upload). Only the post is
 * ordered: each message releases its place the moment its post returns, never
 * waiting for a reply, and a command (/stop included) releases it on dispatch.
 *
 * @module
 */
import { AsyncLocalStorage } from "node:async_hooks";

interface Place {
  /** Settles once every earlier message from the sender has posted or given up its place. */
  earlier: Promise<void>;
  release: () => void;
}

export class ArrivalOrder {
  private readonly tails = new Map<string, Promise<void>>();
  private readonly places = new AsyncLocalStorage<Place>();

  /** Handle one arrived message; a post inside it waits for the sender's earlier messages' posts. */
  run<T>(sender: string, handle: () => Promise<T>): Promise<T> {
    const earlier = this.tails.get(sender) ?? Promise.resolve();
    let release: () => void = () => undefined;
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = earlier.then(() => released);
    this.tails.set(sender, tail);
    void tail.then(() => {
      if (this.tails.get(sender) === tail) this.tails.delete(sender);
    });
    return this.places.run({ earlier, release }, async () => {
      try {
        return await handle();
      } finally {
        release();
      }
    });
  }

  /** Run post after the sender's earlier posts, then free this message's place. */
  async post<T>(post: () => Promise<T>): Promise<T> {
    const place = this.places.getStore();
    if (!place) return post();
    await place.earlier;
    try {
      return await post();
    } finally {
      place.release();
    }
  }

  /** The current message will not post (a command): later messages need not wait for it. */
  release(): void {
    this.places.getStore()?.release();
  }
}

/**
 * The "Thinking..." placeholder a streamed reply fills in (`ReplyPlaceholder`).
 *
 * It is posted alongside the chat request, so by the time it fails the request is already
 * running and doing the user's work. These pin that a failed placeholder never strands that
 * reply: edits are told the message is gone, which the streamer answers with a new message.
 */

import { describe, expect, it, vi } from "vitest";
import { isMessageGoneError } from "../../../../../libs/shared/ts/src/bots/utils/delivery-errors";
import { ReplyPlaceholder } from "../../../../../libs/shared/ts/src/bots/utils/placeholder";

describe("ReplyPlaceholder", () => {
  it("lands edits on the placeholder once it is posted", async () => {
    const placeholder = ReplyPlaceholder.post(async () => 42, vi.fn());

    await expect(placeholder.current()).resolves.toBe(42);
    await expect(placeholder.posted()).resolves.toBe(42);
  });

  it("lands edits on the reply's own message once it opened one", async () => {
    const placeholder = ReplyPlaceholder.post(
      () => new Promise<number>(() => undefined),
      vi.fn(),
    );

    placeholder.moveTo(7);

    // No wait on a placeholder that has not landed: the reply's message exists.
    await expect(placeholder.current()).resolves.toBe(7);
  });

  it("tells edits the message is gone when the placeholder could not be posted", async () => {
    const postError = new Error("Forbidden: not enough rights");
    const onPostFailed = vi.fn();
    const placeholder = ReplyPlaceholder.post<number>(
      () => Promise.reject(postError),
      onPostFailed,
    );

    const editError = await placeholder.current().then(
      () => null,
      (error: unknown) => error,
    );

    // The streamer answers a gone message with a new one — the only copy of the reply.
    expect(isMessageGoneError(editError)).toBe(true);
    await expect(placeholder.posted()).resolves.toBeNull();
    expect(onPostFailed).toHaveBeenCalledOnce();
    expect(onPostFailed).toHaveBeenCalledWith(postError);
  });

  it("still lands edits on a message the reply opened after the placeholder failed", async () => {
    const placeholder = ReplyPlaceholder.post<number>(
      () => Promise.reject(new Error("network down")),
      vi.fn(),
    );
    await placeholder.posted();

    placeholder.moveTo(9);

    await expect(placeholder.current()).resolves.toBe(9);
  });
});

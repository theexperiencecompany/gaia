/**
 * A platform send that rejects (Telegram's 400 "chat not found" for a stale chat
 * link) ends that one follow, and never escapes as an unhandled rejection that
 * kills the bot process for every other conversation.
 *
 * The followers, the follower and the delivery machine are real; the events
 * stream is scripted and the platform is a recorder whose stale chat rejects.
 */
import {
  type ConversationEventSource,
  ConversationFollowers,
  type DeliveryCursor,
  type DeliveryRecorder,
  type FollowSurface,
  neverReopened,
  REACTION_OUTCOME,
  type StreamingOptions,
} from "@gaia/shared/bots";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UnreadableFrameError } from "../../../../../libs/shared/ts/src/bots/api/conversation-events";
import { retryTransientPlatformCall } from "../../../../../libs/shared/ts/src/bots/utils/delivery-errors";
import {
  insertFrame,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  updateFrame,
  userItemWith,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../../libs/shared/ts/src/conversation/types";

// A live preview goes out on the edit timer, after the frame that scheduled it rendered.
const EDIT_INTERVAL_MS = 5;
const TELEGRAM: StreamingOptions = {
  editIntervalMs: EDIT_INTERVAL_MS,
  streaming: true,
  platform: "telegram",
  bubblePauseMs: 0,
};
const NOT_KEPT: DeliveryRecorder = async () => undefined;

/** grammY's GrammyError: Telegram's status in error_code, its reason in description. */
function grammyError(status: number, description: string): Error {
  return Object.assign(
    new Error(`Call to 'sendMessage' failed! (${status}: ${description})`),
    { name: "GrammyError", error_code: status, description },
  );
}
const chatNotFound = () => grammyError(400, "Bad Request: chat not found");
const rateLimited = () =>
  Object.assign(grammyError(429, "Too Many Requests: retry after 5"), {
    parameters: { retry_after: 5 },
  });

function surface(sent: string[], refuse: (() => Error) | null): FollowSurface {
  return {
    sendNotice: async () => undefined,
    windowClosed: async () => false,
    links: {
      conversation: "https://gaia.test/c/c1",
      pricing: "https://gaia.test/pricing",
    },
    requester: {
      sendNotice: async () => undefined,
      sendPhoto: async () => undefined,
    },
    sendFile: async () => undefined,
    send: async (text) => {
      if (refuse) throw refuse();
      sent.push(text);
      return {
        id: `m${sent.length}`,
        edit: async (updated) => {
          sent.push(updated);
        },
      };
    },
    reopen: neverReopened("telegram"),
    react: async () => REACTION_OUTCOME.ATTACHED,
    startTyping: () => () => undefined,
  };
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A reply that streams, then goes quiet past the edit timer while the model thinks, then settles. */
async function* conversation(
  replyId: string,
  text: string,
): AsyncGenerator<ConversationFrame> {
  const attempt = `a-${replyId}`;
  yield screenFrame([
    userItemWith("u1", 1, { surface: "telegram", platform_message_id: "11" }),
  ]);
  yield stateFrame(1, "thinking");
  yield insertFrame(replyItem(replyId, 2, text.slice(0, 4)));
  yield replyDelta(attempt, replyId, 0, text.slice(0, 4));
  await pause(EDIT_INTERVAL_MS * 10);
  yield replyDelta(attempt, replyId, 1, text.slice(4));
  yield updateFrame(replyItem(replyId, 2, text, "answered"));
  yield stateFrame(2, "idle");
}

const flushTimers = () => pause(EDIT_INTERVAL_MS * 4);

describe("a send to a chat that no longer exists", () => {
  const unhandled: unknown[] = [];
  const onUnhandled = (reason: unknown) => unhandled.push(reason);
  beforeEach(() => {
    unhandled.length = 0;
    process.on("unhandledRejection", onUnhandled);
  });
  afterEach(() => {
    process.off("unhandledRejection", onUnhandled);
  });

  it("ends that follow without an unhandled rejection, and the other conversation still delivers", async () => {
    const source: ConversationEventSource = async function* (
      _ctx,
      conversationId,
    ) {
      yield* conversation(
        conversationId === "stale" ? "r-stale" : "r-live",
        conversationId === "stale"
          ? "Reminder: call mom."
          : "Your flight is booked.",
      );
    };
    const followers = new ConversationFollowers(source, TELEGRAM, NOT_KEPT);
    const staleSent: string[] = [];
    const liveSent: string[] = [];

    followers.follow(
      { platform: "telegram", platformUserId: "1" },
      "stale",
      1,
      { delivered_seq: 0, partial_reply: null },
      surface(staleSent, chatNotFound),
    );
    followers.follow(
      { platform: "telegram", platformUserId: "2" },
      "live",
      1,
      { delivered_seq: 0, partial_reply: null },
      surface(liveSent, null),
    );
    await followers.idle();
    await flushTimers();

    expect(unhandled).toEqual([]);
    expect(staleSent).toEqual([]);
    expect(liveSent.at(-1)).toBe("Your flight is booked.");
  });

  it("ends the follow on a send that still fails, instead of reopening the stream into a closed follow", async () => {
    let opened = 0;
    const source: ConversationEventSource = async function* () {
      opened += 1;
      yield* conversation("r1", "Reminder: call mom.");
    };
    const followers = new ConversationFollowers(source, TELEGRAM, NOT_KEPT);

    followers.follow(
      { platform: "telegram", platformUserId: "1" },
      "stale",
      1,
      { delivered_seq: 0, partial_reply: null },
      surface([], () => grammyError(502, "Bad Gateway")),
    );
    const ended = await Promise.race([
      followers.idle().then(() => true),
      pause(EDIT_INTERVAL_MS * 40).then(() => false),
    ]);
    await followers.stopAll();

    expect(unhandled).toEqual([]);
    expect(ended).toBe(true);
    expect(opened).toBe(1);
  });
});

describe("a platform outage mid-reply", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Follows c1 from cursor with sends that fail while outage lasts; resolves once the follow ends. */
  async function followThrough(
    outage: (() => Error)[],
    sent: string[],
    from: DeliveryCursor,
    kept: (cursor: DeliveryCursor) => void,
  ): Promise<number[]> {
    const tried: number[] = [];
    const platform = surface(sent, null);
    const send: FollowSurface["send"] = (text, replyTo) =>
      retryTransientPlatformCall(async () => {
        tried.push(Date.now());
        const failure = outage.shift();
        if (failure) throw failure();
        return platform.send(text, replyTo);
      });
    const source: ConversationEventSource = async function* () {
      yield* conversation("r1", "Your flight is booked.");
    };
    const followers = new ConversationFollowers(
      source,
      TELEGRAM,
      async (_ctx, _id, cursor) => kept(cursor),
    );
    followers.resume(
      { platform: "telegram", platformUserId: "1" },
      "c1",
      from,
      {
        ...platform,
        send,
      },
    );
    let ended = false;
    void followers.idle().then(() => {
      ended = true;
    });
    for (let tick = 0; tick < 120 && !ended; tick += 1) {
      await vi.advanceTimersByTimeAsync(1_000);
    }
    expect(ended).toBe(true);
    return tried;
  }

  const badGateway = () => grammyError(502, "Bad Gateway");

  it("retries through a rate limit and bad gateways within the tier, then delivers the reply in order", async () => {
    vi.useFakeTimers();
    const sent: string[] = [];

    const tried = await followThrough(
      [rateLimited, badGateway, badGateway, badGateway],
      sent,
      { delivered_seq: 0, partial_reply: null },
      () => undefined,
    );

    expect(tried).toHaveLength(5);
    // The platform's retry_after is honoured before the first retry.
    expect(tried[1] - tried[0]).toBeGreaterThanOrEqual(5_000);
    expect(sent.at(-1)).toBe("Your flight is booked.");
    expect(sent[0]).toBe("Your");
  });

  it("stops after the tier, and the next poll's follow delivers the reply once from the cursor kept", async () => {
    vi.useFakeTimers();
    const sent: string[] = [];
    let cursor: DeliveryCursor = { delivered_seq: 0, partial_reply: null };
    const keep = (kept: DeliveryCursor) => {
      cursor = kept;
    };

    const tried = await followThrough(
      Array.from({ length: 6 }, () => badGateway),
      sent,
      cursor,
      keep,
    );
    expect(tried).toHaveLength(5);
    expect(sent).toEqual([]);

    await followThrough([badGateway], sent, cursor, keep);

    expect(sent.at(-1)).toBe("Your flight is booked.");
    expect(sent.filter((text) => text === "Your")).toHaveLength(1);
    expect(cursor).toEqual({ delivered_seq: 2, partial_reply: null });
  });
});

describe("a frame this build cannot read", () => {
  it("ends the follow at once instead of reconnecting into the same frame", async () => {
    let opened = 0;
    const source: ConversationEventSource = async function* () {
      opened += 1;
      yield screenFrame([
        userItemWith("u1", 1, {
          surface: "telegram",
          platform_message_id: "11",
        }),
      ]);
      throw new UnreadableFrameError({
        kind: "invalid_frame",
        raw: "{}",
        issues: ["frame.items.1.kind: Invalid input"],
      });
    };
    const followers = new ConversationFollowers(source, TELEGRAM, NOT_KEPT);

    followers.follow(
      { platform: "telegram", platformUserId: "1" },
      "c1",
      1,
      { delivered_seq: 0, partial_reply: null },
      surface([], null),
    );
    await followers.idle();

    expect(opened).toBe(1);
  });
});

describe("an edit during a platform outage", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries the edit within the tier, so the finished text replaces the preview", async () => {
    vi.useFakeTimers();
    const outage = Array.from(
      { length: 4 },
      () => () => grammyError(502, "Bad Gateway"),
    );
    const sent: string[] = [];
    const platform = surface(sent, null);
    const send: FollowSurface["send"] = async (text, replyTo) => {
      const message = await platform.send(text, replyTo);
      return {
        ...message,
        edit: async (updated: string) => {
          const failure = outage.shift();
          if (failure) throw failure();
          await message.edit(updated);
        },
      };
    };
    const source: ConversationEventSource = async function* () {
      yield* conversation("r1", "Your flight is booked.");
    };
    const followers = new ConversationFollowers(source, TELEGRAM, NOT_KEPT);

    followers.follow(
      { platform: "telegram", platformUserId: "1" },
      "c1",
      1,
      { delivered_seq: 0, partial_reply: null },
      {
        ...platform,
        send,
      },
    );
    let ended = false;
    void followers.idle().then(() => {
      ended = true;
    });
    for (let tick = 0; tick < 120 && !ended; tick += 1) {
      await vi.advanceTimersByTimeAsync(1_000);
    }

    expect(ended).toBe(true);
    expect(outage).toEqual([]);
    expect(sent.at(-1)).toBe("Your flight is booked.");
  });
});

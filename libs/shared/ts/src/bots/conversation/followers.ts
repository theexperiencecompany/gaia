/**
 * One follower per active conversation: reuse it while it runs, start one
 * when none does, and keep its events stream connected until the
 * conversation is idle with every posted message answered.
 *
 * A dropped connection resumes after the newest stream id the follower saw
 * (the follower is idempotent, so a replayed frame renders nothing). A server
 * that refuses the stream (4xx) ends the follow; anything else is retried.
 */

import type { ConversationEvent } from "../api/conversation-events";
import type { BotUserContext } from "../types";
import { recordBotFailure } from "../utils/failure-reasons";
import { getHttpStatus, sanitizeErrorForLog } from "../utils/logger";
import { sleep } from "../utils/timeout";
import { wideLog, withWideEvent } from "../utils/wide-events";
import { ConversationFollower } from "./follower";
import type { ConversationSurface, StreamingOptions } from "./follower.types";

/** Opens one connection to a conversation's events stream. */
export type ConversationEventSource = (
  ctx: BotUserContext,
  conversationId: string,
  after: string,
  signal: AbortSignal,
) => AsyncIterable<ConversationEvent>;

/** Reconnect backoff: doubles from the base, capped. */
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;
/** Consecutive failed connections before the follow gives up. */
const MAX_RECONNECTS = 8;

interface Followed {
  follower: ConversationFollower;
  abort: AbortController;
}

export class ConversationFollowers {
  private readonly active = new Map<string, Followed>();
  private readonly runs = new Set<Promise<void>>();

  constructor(
    private readonly events: ConversationEventSource,
    private readonly options: StreamingOptions,
  ) {}

  /**
   * Follow a conversation until message seq is answered: joins the follower already
   * running for it, or starts one replaying from just before seq.
   */
  follow(
    ctx: BotUserContext,
    conversationId: string,
    seq: number,
    surface: ConversationSurface,
  ): void {
    const running = this.active.get(conversationId);
    if (running) {
      running.follower.expect(seq);
      return;
    }
    const follower = new ConversationFollower(seq - 1, this.options, surface);
    follower.expect(seq);
    const followed = { follower, abort: new AbortController() };
    this.active.set(conversationId, followed);
    const run = this.run(ctx, conversationId, seq - 1, followed).finally(() => {
      this.runs.delete(run);
    });
    this.runs.add(run);
  }

  /** Settles once every follow running now has ended. */
  async idle(): Promise<void> {
    while (this.runs.size > 0) await Promise.allSettled([...this.runs]);
  }

  /** End every follow, for shutdown. */
  async stopAll(): Promise<void> {
    for (const { abort } of this.active.values()) abort.abort();
    await this.idle();
  }

  private run(
    ctx: BotUserContext,
    conversationId: string,
    floor: number,
    followed: Followed,
  ): Promise<void> {
    return withWideEvent(
      "conversation_follow",
      {
        platform: this.options.platform,
        component: "follower",
        conversation_id: conversationId,
      },
      async () => {
        try {
          await this.consume(ctx, conversationId, String(floor), followed);
        } finally {
          if (this.active.get(conversationId) === followed)
            this.active.delete(conversationId);
          followed.follower.close();
          const { summary } = followed.follower;
          wideLog.set({
            replies_delivered: summary.repliesDelivered,
            reactions_placed: summary.reactionsPlaced,
            quotes_missed: summary.quotesMissed,
          });
        }
      },
    );
  }

  private async consume(
    ctx: BotUserContext,
    conversationId: string,
    start: string,
    { follower, abort }: Followed,
  ): Promise<void> {
    let cursor = start;
    let failures = 0;
    let reconnects = 0;
    while (!abort.signal.aborted) {
      try {
        for await (const event of this.events(
          ctx,
          conversationId,
          cursor,
          abort.signal,
        )) {
          await follower.apply(event.frame);
          if (event.stream_id) cursor = event.stream_id;
          failures = 0;
          if (follower.finished) {
            // Leave the registry before any await, so a message posted now starts a new follow.
            this.active.delete(conversationId);
            wideLog.set({ reconnects });
            return;
          }
        }
      } catch (error) {
        if (abort.signal.aborted) return;
        const status = getHttpStatus(error);
        failures += 1;
        const refused = status !== undefined && status >= 400 && status < 500;
        if (refused || failures > MAX_RECONNECTS) {
          // The follow is over; its replies stay in the log for the next follow and the web app.
          recordBotFailure("conversation_follow_failed", error, { failures });
          return;
        }
        wideLog.warning("conversation_follow_reconnecting", {
          ...sanitizeErrorForLog(error),
          failures,
        });
      }
      reconnects += 1;
      await sleep(
        Math.min(RECONNECT_BASE_MS * 2 ** failures, RECONNECT_MAX_MS),
      );
    }
  }
}

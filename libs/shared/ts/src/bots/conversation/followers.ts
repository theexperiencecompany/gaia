/**
 * One follower per active conversation: reuse it while it runs, start one
 * when none does, and keep its events stream connected until the
 * conversation is idle with every posted message answered.
 *
 * A dropped connection reconnects and opens on a fresh screen (the follower is
 * idempotent, so an item it already rendered renders nothing). A server
 * that refuses the stream (4xx) ends the follow; anything else is retried.
 */

import { FRAME_KIND } from "../../conversation/frames";
import type { ConversationFrame } from "../../conversation/types";
import type { BotUserContext } from "../types";
import { recordBotFailure } from "../utils/failure-reasons";
import { getHttpStatus, sanitizeErrorForLog } from "../utils/logger";
import { sleep } from "../utils/timeout";
import { wideLog, withWideEvent } from "../utils/wide-events";
import { ConversationFollower } from "./follower";
import type { FollowSurface, StreamingOptions } from "./follower.types";

/** Opens one connection to a conversation's events stream. */
export type ConversationEventSource = (
  ctx: BotUserContext,
  conversationId: string,
  signal: AbortSignal,
) => AsyncIterable<ConversationFrame>;

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
  /** The newest seq a follow of each conversation started from or delivered, so a late wake repeats nothing. */
  private readonly reached = new Map<string, number>();
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
    surface: FollowSurface,
  ): void {
    const running = this.active.get(conversationId);
    if (running) {
      running.follower.expect(seq);
      return;
    }
    this.start(ctx, conversationId, seq - 1, surface).expect(seq);
  }

  /**
   * Follow a conversation after afterSeq until it is idle: one a restarted bot finds
   * still answering, or one the server woke for something logged there. Nothing when
   * a follow runs, and never from before what an earlier follow here reached.
   */
  resume(
    ctx: BotUserContext,
    conversationId: string,
    afterSeq: number,
    surface: FollowSurface,
  ): void {
    if (this.active.has(conversationId)) return;
    const reached = this.reached.get(conversationId) ?? afterSeq;
    this.start(ctx, conversationId, Math.max(afterSeq, reached), surface);
  }

  private start(
    ctx: BotUserContext,
    conversationId: string,
    floor: number,
    surface: FollowSurface,
  ): ConversationFollower {
    this.reach(conversationId, floor);
    const follower = new ConversationFollower(
      floor,
      this.options,
      surface,
      conversationId,
    );
    const followed = { follower, abort: new AbortController() };
    this.active.set(conversationId, followed);
    const run = this.run(ctx, conversationId, followed).finally(() => {
      this.runs.delete(run);
    });
    this.runs.add(run);
    return follower;
  }

  private reach(conversationId: string, seq: number): void {
    if (seq > (this.reached.get(conversationId) ?? 0))
      this.reached.set(conversationId, seq);
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
          await this.consume(ctx, conversationId, followed);
        } finally {
          if (this.active.get(conversationId) === followed)
            this.active.delete(conversationId);
          followed.follower.close();
          const { summary } = followed.follower;
          wideLog.set({
            replies_delivered: summary.repliesDelivered,
            reactions_placed: summary.reactionsPlaced,
          });
        }
      },
    );
  }

  private async consume(
    ctx: BotUserContext,
    conversationId: string,
    { follower, abort }: Followed,
  ): Promise<void> {
    let failures = 0;
    let reconnects = 0;
    while (!abort.signal.aborted) {
      try {
        for await (const frame of this.events(
          ctx,
          conversationId,
          abort.signal,
        )) {
          await follower.apply(frame);
          this.reach(conversationId, newestSeq(frame));
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

/** The newest screen position a frame shows; 0 for a frame that shows no item. */
function newestSeq(frame: ConversationFrame): number {
  switch (frame.kind) {
    case FRAME_KIND.SCREEN:
      return Math.max(0, ...frame.items.map((item) => item.seq));
    case FRAME_KIND.SCREEN_INSERT:
    case FRAME_KIND.SCREEN_UPDATE:
      return frame.item.seq;
    default:
      return 0;
  }
}

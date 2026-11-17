/**
 * One follower per active conversation: reuse it while it runs, start one
 * when none does, and keep its events stream connected until the
 * conversation is idle with every posted message answered.
 *
 * A dropped connection reconnects and opens on a fresh screen (the follower is
 * idempotent, so an item it already rendered renders nothing). A server
 * that refuses the stream (4xx) ends the follow; anything else is retried.
 * Each follower reports how far it delivered through record, which the server
 * keeps, so a restarted bot resumes from that cursor.
 */

import type { ConversationFrame } from "../../conversation/types";
import { isRetryableStatus, RETRY_POLICY, reconnectDelayMs } from "../../retry";
import type { BotUserContext } from "../types";
import { recordBotFailure } from "../utils/failure-reasons";
import {
  getHttpStatus,
  hashLogIdentifier,
  sanitizeErrorForLog,
} from "../utils/logger";
import { sleep } from "../utils/timeout";
import { wideLog, withWideEvent } from "../utils/wide-events";
import { ConversationFollower } from "./follower";
import type {
  AwaitedDecision,
  DeliveryCursor,
  FollowSurface,
  StreamingOptions,
} from "./follower.types";

/** Opens one connection to a conversation's events stream. */
export type ConversationEventSource = (
  ctx: BotUserContext,
  conversationId: string,
  signal: AbortSignal,
) => AsyncIterable<ConversationFrame>;

/** Keeps how far a follower delivered a conversation, where a restarted bot reads it back. */
export type DeliveryRecorder = (
  ctx: BotUserContext,
  conversationId: string,
  cursor: DeliveryCursor,
) => Promise<void>;

interface Followed {
  follower: ConversationFollower;
  abort: AbortController;
}

export class ConversationFollowers {
  private readonly active = new Map<string, Followed>();
  /** The cursor a follow of each conversation started from or delivered to, so a late wake repeats nothing. */
  private readonly reached = new Map<string, DeliveryCursor>();
  private readonly runs = new Set<Promise<void>>();
  /** Waiters woken after a follow renders a frame, so settled re-checks what the follows wait on. */
  private readonly changes = new Set<() => void>();

  constructor(
    private readonly events: ConversationEventSource,
    private readonly options: StreamingOptions,
    private readonly record: DeliveryRecorder,
  ) {}

  /**
   * Follow a conversation until message seq is answered: joins the follower already
   * running for it, or starts one from the server's cursor for that message.
   */
  follow(
    ctx: BotUserContext,
    conversationId: string,
    seq: number,
    from: DeliveryCursor,
    surface: FollowSurface,
  ): void {
    const running = this.active.get(conversationId);
    if (running) {
      running.follower.expect(seq);
      return;
    }
    this.start(ctx, conversationId, from, surface).expect(seq);
  }

  /**
   * Follow a conversation from the server's delivery cursor until it is idle: one a
   * restarted bot finds still answering or undelivered, or one the server woke for
   * something logged there. Nothing when a follow runs.
   */
  resume(
    ctx: BotUserContext,
    conversationId: string,
    from: DeliveryCursor,
    surface: FollowSurface,
  ): void {
    if (this.active.has(conversationId)) return;
    this.start(ctx, conversationId, from, surface);
  }

  /** Start a follow at the server's cursor, never before what an earlier follow here reached. */
  private start(
    ctx: BotUserContext,
    conversationId: string,
    from: DeliveryCursor,
    surface: FollowSurface,
  ): ConversationFollower {
    const reached = this.reached.get(conversationId);
    const start =
      reached && reached.delivered_seq > from.delivered_seq ? reached : from;
    this.reach(conversationId, start);
    const follower = new ConversationFollower(
      {
        floor: start.delivered_seq,
        partialReply: start.partial_reply,
        record: async (cursor) => {
          this.reach(conversationId, cursor);
          await this.record(ctx, conversationId, cursor);
        },
      },
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

  private reach(conversationId: string, cursor: DeliveryCursor): void {
    const reached = this.reached.get(conversationId);
    if (!reached || cursor.delivered_seq >= reached.delivered_seq)
      this.reached.set(conversationId, cursor);
  }

  /** Settles once every follow running now has ended. */
  async idle(): Promise<void> {
    while (this.runs.size > 0) await Promise.allSettled([...this.runs]);
  }

  /**
   * Settles once every follow has ended or waits on approvals it asked the user about,
   * returning those: such a follow ends only after a decision nobody else will make.
   */
  async settled(): Promise<AwaitedDecision[]> {
    while (this.runs.size > 0) {
      const followed = [...this.active.entries()];
      const awaited = followed.map(([conversationId, { follower }]) => ({
        conversationId,
        approvals: follower.awaitingDecision,
      }));
      // A run that already left the registry is still finishing: wait for it.
      if (
        followed.length === this.runs.size &&
        awaited.every(({ approvals }) => approvals.length > 0)
      )
        return awaited;
      const changed = new Promise<void>((resolve) => this.changes.add(resolve));
      await Promise.race([Promise.allSettled([...this.runs]), changed]);
    }
    return [];
  }

  private changed(): void {
    for (const resolve of this.changes) resolve();
    this.changes.clear();
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
          this.changed();
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
        if (follower.deliveryFailed) {
          // The platform refused a send, not the stream: reconnecting replays into the same refusal.
          recordBotFailure("conversation_delivery_failed", error, {
            conversation_id: conversationId,
            user_hash: hashLogIdentifier(ctx.platformUserId),
          });
          return;
        }
        const status = getHttpStatus(error);
        failures += 1;
        const refused = status !== undefined && !isRetryableStatus(status);
        if (refused || failures > RETRY_POLICY.STREAM_RECONNECT.retries) {
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
      await sleep(reconnectDelayMs(failures));
    }
  }
}

/**
 * One follower per active conversation: reuse it while it runs, start one
 * when none does, and keep its events stream connected until the
 * conversation is idle with every posted message answered.
 *
 * A new follower opens after its delivery cursor, and a dropped connection reconnects
 * after the log head the follower's screen reached, so the server sends only what is
 * new or changed since; a change with no place in the screen held reopens on the whole
 * one (an item the follower already rendered, or one from before its cursor, renders
 * nothing). A server
 * that refuses the stream (4xx) ends the follow; anything else is retried. A follow
 * a transient failure ended (a platform outage, a stream that would not reopen)
 * starts again from its delivery cursor under UNTIL_IT_LANDS, so no reply is dropped.
 * Each follower reports how far it delivered through record, which the server
 * keeps, so a restarted bot resumes from that cursor.
 */

import type { ConversationFrame } from "../../conversation/types";
import {
  isRetryableStatus,
  RETRY_POLICY,
  reconnectDelayMs,
  withRetry,
} from "../../retry";
import type { BotUserContext } from "../types";
import {
  classifyBotFailure,
  isTransientBotFailure,
  recordBotFailure,
} from "../utils/failure-reasons";
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

/** Opens one connection to a conversation's events stream; after is the log head the follower opens after, null for the whole screen. */
export type ConversationEventSource = (
  ctx: BotUserContext,
  conversationId: string,
  signal: AbortSignal,
  after: number | null,
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

/** A follow a transient failure ended: what it delivered is on its cursor, and the rest is still owed. */
class FollowInterrupted extends Error {
  constructor(readonly failure: unknown) {
    super("the follow ended on a transient failure");
    this.name = "FollowInterrupted";
  }
}

export class ConversationFollowers {
  private readonly active = new Map<string, Followed>();
  /** The cursor a follow of each conversation started from or delivered to, so a late wake repeats nothing. */
  private readonly reached = new Map<string, DeliveryCursor>();
  private readonly runs = new Set<Promise<void>>();
  /** Waiters woken after a follow renders a frame, so settled re-checks what the follows wait on. */
  private readonly changes = new Set<() => void>();
  /** Aborted on shutdown: ends the waits between a follow's restarts. */
  private readonly stopping = new AbortController();

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

  /**
   * Start a follow at the server's cursor, never before what an earlier follow here reached,
   * and start it again from where it delivered to each time a transient failure ends it.
   */
  private start(
    ctx: BotUserContext,
    conversationId: string,
    from: DeliveryCursor,
    surface: FollowSurface,
  ): ConversationFollower {
    let next: Followed | null = this.open(ctx, conversationId, from, surface);
    const { follower } = next;
    const run = withRetry(
      RETRY_POLICY.UNTIL_IT_LANDS,
      async () => {
        const followed = next ?? this.reopen(ctx, conversationId, surface);
        next = null;
        // A follow a newer message started carries the conversation on.
        if (followed) await this.run(ctx, conversationId, followed);
      },
      {
        transient: (error) => error instanceof FollowInterrupted,
        onRetry: (error, attempt) =>
          wideLog.warning("conversation_follow_restarting", {
            ...sanitizeErrorForLog(
              error instanceof FollowInterrupted ? error.failure : error,
            ),
            conversation_id: conversationId,
            attempt,
          }),
        signal: this.stopping.signal,
      },
    )
      .catch((error: unknown) => {
        if (this.stopping.signal.aborted) return;
        throw error;
      })
      .finally(() => {
        this.runs.delete(run);
      });
    this.runs.add(run);
    return follower;
  }

  /** A follow from where the last one here delivered to; null when another follow already runs. */
  private reopen(
    ctx: BotUserContext,
    conversationId: string,
    surface: FollowSurface,
  ): Followed | null {
    const reached = this.reached.get(conversationId);
    if (this.active.has(conversationId) || !reached) return null;
    return this.open(ctx, conversationId, reached, surface);
  }

  private open(
    ctx: BotUserContext,
    conversationId: string,
    from: DeliveryCursor,
    surface: FollowSurface,
  ): Followed {
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
    return followed;
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
    this.stopping.abort();
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
            notices_delivered: summary.noticesDelivered,
            files_delivered: summary.filesDelivered,
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
          follower.resumeAfter,
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
          // The platform failed a send, not the stream: reconnecting replays into the same failure.
          if (isTransientBotFailure(classifyBotFailure(error)))
            throw new FollowInterrupted(error);
          recordBotFailure("conversation_delivery_failed", error, {
            conversation_id: conversationId,
            user_hash: hashLogIdentifier(ctx.platformUserId),
          });
          return;
        }
        const status = getHttpStatus(error);
        failures += 1;
        if (status !== undefined && !isRetryableStatus(status)) {
          // A refusal is over; its replies stay in the log for the next follow and the web app.
          recordBotFailure("conversation_follow_failed", error, { failures });
          return;
        }
        if (failures > RETRY_POLICY.STREAM_RECONNECT.retries)
          throw new FollowInterrupted(error);
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

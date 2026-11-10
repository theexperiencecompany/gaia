/**
 * Consumes one platform's outbound-message queue and delivers each message via
 * the adapter's platform send primitive.
 *
 * Backend-originated messages (executor replies, reminders) are published to a
 * durable per-platform queue; this consumer renders the platform-native
 * markdown and hands each (chunked) message to the adapter, with a one-retry +
 * dead-letter-queue safety net. A send the platform rate-limits is sent again
 * after the wait it asked for. An envelope carrying an `outbox_message_id` is
 * deduplicated across redeliveries ({@link OutboundDedupeStore}) and reports how
 * it ended on the receipts queue.
 */

import { type Channel, type ConsumeMessage, connect } from "amqplib";
import { z } from "zod";
import {
  DELIVERY_FAILURE_KIND,
  type DeliveryFailure,
  describeErrorForAlert,
  type ReportDeliveryFailure,
} from "../delivery-failures";
import type {
  OutboundNotifications,
  OutboundSendOptions,
  PlatformName,
} from "../types";
import { segmentIntoBubbles } from "../utils/bubbles";
import { retryAfterMs } from "../utils/delivery-errors";
import {
  BOT_FAILURE_REASON,
  classifyBotFailure,
  isTransientBotFailure,
  recordBotFailure,
} from "../utils/failure-reasons";
import { renderForPlatform } from "../utils/formatters";
import {
  type BotLogger,
  createBotLogger,
  hashLogIdentifier,
} from "../utils/logger";
import { chunkResponse } from "../utils/text";
import { wideLog, withWideEvent } from "../utils/wide-events";
import { DEDUPE_STATE, dedupeKey, OutboundDedupeStore } from "./dedupe";
import {
  OUTBOUND_ENVELOPE_VERSION,
  type OutboundAttachment,
  type OutboundMessageEnvelope,
  type OutboundReaction,
  outboundMessageEnvelopeSchemaFor,
} from "./envelope";
import {
  type OutboundReceipt,
  RECEIPT_STATUS,
  type ReceiptStatus,
} from "./receipts";
import {
  dlqName,
  OUTBOUND_DLX,
  OUTBOUND_QUEUES,
  OUTBOUND_RECEIPTS_QUEUE,
  workQueueArguments,
} from "./topology";

/** Messages prefetched per consumer — bounds in-flight work for backpressure. */
const PREFETCH = 8;
const RECONNECT_BASE_MS = 1_000;
/** Lane for a message whose destination can't be read; handle() dead-letters it. */
const UNREADABLE_LANE = "";
const RECONNECT_MAX_MS = 30_000;
/** Template body for a file that cannot be sent free-form until the user writes again. */
const FILE_WAITING_NOTICE =
  "I have a file for you, but I can only send it after you message me. Reply here and ask me for it.";

/**
 * Sends one already-rendered message to a platform destination and returns the
 * platform's id for it (undefined when the platform gives none). `isChannel`
 * tells the adapter whether `destinationId` is a channel/group id (send to the
 * channel) or a user id (open the DM).
 */
type DeliverFn = (
  destinationId: string,
  text: string,
  isChannel: boolean,
  options?: OutboundSendOptions,
) => Promise<string | undefined>;

/**
 * Replaces the text of an already-sent platform message and returns its id. A
 * platform that cannot edit a sent message has no such function.
 */
export type DeliverEditFn = (
  destinationId: string,
  platformMessageId: string,
  text: string,
  isChannel: boolean,
) => Promise<string | undefined>;

/** What a receipt and a dedupe record are filed under; present only on a tracked envelope. */
interface Routing {
  envelopeId: string;
  outboxMessageId: string;
  partIndex: number;
}

const routingSchema = z.object({
  id: z.string().min(1),
  outbox_message_id: z.string().min(1),
  part_index: z.number().int().nonnegative().default(0),
});

/** The routing of an envelope that has not been validated, or null when it is untracked or unreadable. */
function readRouting(raw: unknown): Routing | null {
  const parsed = routingSchema.safeParse(raw);
  return parsed.success
    ? {
        envelopeId: parsed.data.id,
        outboxMessageId: parsed.data.outbox_message_id,
        partIndex: parsed.data.part_index,
      }
    : null;
}

/** What settling a message needs to know about how far its delivery got. */
interface Settlement {
  routing: Routing | null;
  /** Platform message ids sent so far, in order. */
  platformMessageIds: string[];
}

/** One message being handled: the broker delivery, its envelope and its delivery progress. */
interface Attempt extends Settlement {
  channel: Channel;
  msg: ConsumeMessage;
  env: OutboundMessageEnvelope;
  /** Sends that went out, counting those the platform gave no id for. */
  delivered: number;
  /** The dedupe record this attempt holds, when the envelope is tracked. */
  claimKey: string | null;
}

/** Settlement of a message that never reached a send. */
const UNSENT: Settlement = { routing: null, platformMessageIds: [] };

/**
 * Sends one file attachment to a platform destination, addressed like
 * {@link DeliverFn}: a channel/group id when `isChannel`, else a user id.
 */
type DeliverFileFn = (
  destinationId: string,
  attachment: OutboundAttachment,
  isChannel: boolean,
) => Promise<void>;

/**
 * Attaches an emoji reaction to an existing platform message. `isChannel`
 * tells the adapter whether `destinationId` is a channel/group id or a user
 * id, same as the text path.
 */
export type DeliverReactionFn = (
  destinationId: string,
  reaction: OutboundReaction,
  isChannel: boolean,
) => Promise<void>;

export class OutboundConsumer {
  private conn: Awaited<ReturnType<typeof connect>> | null = null;
  private channel: Channel | null = null;
  private stopped = false;
  private reconnectDelayMs = RECONNECT_BASE_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Per-chat delivery chains, so one chat's messages go out in published order. */
  private readonly lanes = new Map<string, Promise<void>>();
  private readonly logger: BotLogger;
  private readonly envelopeSchema: ReturnType<
    typeof outboundMessageEnvelopeSchemaFor
  >;
  private readonly deliverReaction: DeliverReactionFn;
  private readonly dedupe = new OutboundDedupeStore();

  /**
   * `gaiaApiUrl` is what makes a plain-http attachment URL acceptable: a dev or
   * self-hosted API serves step screenshots off its own host, and only that one
   * origin is exempt from the https rule. `reportFailure` alerts on every message
   * this consumer dead-letters. `deliverEdit` is absent on a platform that cannot
   * edit a sent message: an edit envelope then fails instead of sending a second one.
   */
  constructor(
    private readonly platform: PlatformName,
    private readonly url: string,
    private readonly deliver: DeliverFn,
    private readonly deliverFile: DeliverFileFn,
    gaiaApiUrl: string | undefined,
    private readonly reportFailure: ReportDeliveryFailure,
    deliverReaction?: DeliverReactionFn,
    private readonly notifications?: OutboundNotifications,
    private readonly deliverEdit?: DeliverEditFn,
  ) {
    this.logger = createBotLogger(platform, "outbound-consumer");
    this.envelopeSchema = outboundMessageEnvelopeSchemaFor(gaiaApiUrl);
    // Platforms without a native reaction path keep the old behavior: the
    // emoji goes out as a text bubble. Explicit, logged at the call site.
    this.deliverReaction =
      deliverReaction ??
      (async (destinationId, reaction, isChannel) => {
        wideLog.warning("outbound_reaction_fallback_text", {
          platform: this.platform,
        });
        await this.deliver(destinationId, reaction.emoji, isChannel);
      });
  }

  async start(): Promise<void> {
    await this.connect();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    await this.channel?.close().catch(() => undefined);
    await this.conn?.close().catch(() => undefined);
    this.channel = null;
    this.conn = null;
  }

  /**
   * Connects, declares the topology and starts consuming — one unit of work,
   * one canonical event. A bot that never delivers a backend message is almost
   * always failing here, and a broker that is down at boot retries forever, so
   * each attempt has to be individually visible (with its outcome and how long
   * it took) rather than collapsing into a single line at the end.
   */
  private async connect(): Promise<void> {
    if (this.stopped) return;
    const queue = OUTBOUND_QUEUES[this.platform];
    try {
      await withWideEvent(
        "outbound_connect",
        {
          platform: this.platform,
          component: "outbound-consumer",
          queue,
        },
        async () => {
          const conn = await connect(this.url);
          if (this.stopped) {
            // stop() ran while the connection was opening, before there was a
            // connection for it to close: a bot whose boot failed kept consuming.
            await conn.close().catch(() => undefined);
            return;
          }
          this.conn = conn;
          this.conn.on("close", () => this.scheduleReconnect());
          // Keeps the reason diagnosable and stops an unhandled 'error' from killing the
          // process; 'close' still drives the reconnect. Without this the only trace of a
          // broker restart, revoked credentials, or heartbeat timeout is a bare reconnect log.
          this.conn.on("error", (err) =>
            this.logger.error(
              "outbound_consumer_connection_error",
              undefined,
              err,
            ),
          );
          this.channel = await this.conn.createChannel();

          await this.channel.assertExchange(OUTBOUND_DLX, "direct", {
            durable: true,
          });
          await this.channel.assertQueue(dlqName(queue), { durable: true });
          await this.channel.bindQueue(
            dlqName(queue),
            OUTBOUND_DLX,
            dlqName(queue),
          );
          await this.channel.assertQueue(queue, {
            durable: true,
            arguments: workQueueArguments(queue),
          });
          await this.channel.assertQueue(OUTBOUND_RECEIPTS_QUEUE, {
            durable: true,
          });
          await this.channel.prefetch(PREFETCH);
          await this.channel.consume(queue, (msg) => this.dispatch(msg));

          this.reconnectDelayMs = RECONNECT_BASE_MS;
        },
      );
    } catch {
      // withWideEvent already emitted the failure (outcome=failed, errors[]);
      // re-logging it here would double every broker outage in Loki.
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    // Already scheduled — don't stack a second timer. Both conn.close() below (via 'close')
    // and connect()'s own catch block re-enter here; without this guard each path would add
    // its own setTimeout, leaking duplicate connections/consumers on a flapping broker.
    if (this.reconnectTimer) return;
    // Close the (possibly still-open) connection before dropping the reference,
    // so a channel-level failure after connect() succeeded does not leak it.
    this.channel?.close().catch(() => undefined);
    this.conn?.close().catch(() => undefined);
    this.channel = null;
    this.conn = null;
    const delay = this.reconnectDelayMs;
    this.reconnectDelayMs = Math.min(delay * 2, RECONNECT_MAX_MS);
    this.logger.warn("outbound_consumer_reconnecting", { wait_ms: delay });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  /**
   * ack/nack a message on the channel that delivered it. A delivery tag is
   * scoped to its channel; if a reconnect has since replaced the channel the
   * broker already requeued the message, so settling on the old (closed)
   * channel would throw — skip it. The try/catch is a final backstop so a
   * stale-channel error never escapes the fire-and-forget consume callback as
   * an unhandled rejection.
   */
  private settle(channel: Channel, action: () => void): void {
    if (this.channel !== channel) return;
    try {
      action();
    } catch {
      wideLog.warning("outbound_settle_skipped", {
        reason: "channel replaced mid-handle",
      });
    }
  }

  /**
   * Dead-letters a message and alerts on it — the one way this consumer drops a
   * message, so nothing reaches the DLQ unreported. The DLQ keeps it for replay.
   * A tracked message also gets its receipt: `failed` when a send was attempted,
   * `dead_lettered` when the envelope was rejected before any send.
   */
  private deadLetter(
    channel: Channel,
    msg: ConsumeMessage,
    failure: DeliveryFailure,
    settlement: Settlement,
  ): void {
    this.reportFailure(failure);
    this.publishReceipt(
      settlement,
      failure.kind === DELIVERY_FAILURE_KIND.SEND_FAILED
        ? RECEIPT_STATUS.FAILED
        : RECEIPT_STATUS.DEAD_LETTERED,
      failure.reason,
    );
    this.settle(channel, () => channel.nack(msg, false, false));
  }

  /** Acks a message whose every send went out, recording it as sent before the broker forgets it. */
  private ackSent(attempt: Attempt): void {
    if (attempt.claimKey) this.dedupe.markSent(attempt.claimKey);
    this.publishReceipt(attempt, RECEIPT_STATUS.SENT, null);
    this.settle(attempt.channel, () => attempt.channel.ack(attempt.msg));
  }

  /**
   * Hands a message back to the broker for one more attempt. Nothing went out,
   * so the claim is released for that attempt to take.
   */
  private requeue(attempt: Attempt): void {
    this.releaseClaim(attempt);
    this.settle(attempt.channel, () =>
      attempt.channel.nack(attempt.msg, false, true),
    );
  }

  /** Forgets this attempt's claim when nothing went out, so a replay of the message may send. */
  private releaseClaim(attempt: Attempt): void {
    if (attempt.claimKey && attempt.delivered === 0) {
      this.dedupe.release(attempt.claimKey);
    }
  }

  /**
   * Reports how a tracked part ended. A receipt is advisory — the part is
   * already sent or failed — so one that cannot be published is logged, never
   * allowed to fail or redeliver the message it describes.
   */
  private publishReceipt(
    settlement: Settlement,
    status: ReceiptStatus,
    error: string | null,
  ): void {
    const { routing } = settlement;
    if (!routing) return;
    const receipt: OutboundReceipt = {
      envelope_id: routing.envelopeId,
      outbox_message_id: routing.outboxMessageId,
      part_index: routing.partIndex,
      platform: this.platform,
      platform_message_ids: settlement.platformMessageIds,
      status,
      error,
      occurred_at: new Date().toISOString(),
    };
    try {
      if (!this.channel) throw new Error("no open channel");
      this.channel.sendToQueue(
        OUTBOUND_RECEIPTS_QUEUE,
        Buffer.from(JSON.stringify(receipt)),
        { persistent: true, contentType: "application/json" },
      );
    } catch (err) {
      wideLog.error(
        "outbound_receipt_publish_failed",
        { envelope_id: routing.envelopeId, receipt_status: status },
        err,
      );
    }
  }

  /**
   * Hands a message to its chat's lane. Prefetched messages run concurrently, so a
   * slow photo upload let the text published after it arrive first; one chat's
   * messages now go out in published order while other chats proceed.
   */
  private dispatch(msg: ConsumeMessage | null): void {
    if (!msg) {
      void this.handle(msg);
      return;
    }
    const lane = laneKey(msg);
    const previous = this.lanes.get(lane) ?? Promise.resolve();
    const current = previous.then(() => this.handle(msg));
    this.lanes.set(lane, current);
    void current.finally(() => {
      if (this.lanes.get(lane) === current) this.lanes.delete(lane);
    });
  }

  private async handle(msg: ConsumeMessage | null): Promise<void> {
    const channel = this.channel;
    if (!msg || !channel) return;

    await withWideEvent(
      "outbound_message",
      {
        platform: this.platform,
        component: "outbound-consumer",
        queue: OUTBOUND_QUEUES[this.platform],
      },
      async () => {
        const env = this.parseEnvelope(channel, msg);
        if (!env) return;

        wideLog.set({
          envelope_id: env.id,
          destination_hash: hashLogIdentifier(env.destination_id),
          has_attachment: Boolean(env.attachment),
          has_reaction: Boolean(env.reaction),
        });

        const attempt = this.beginAttempt(channel, msg, env);
        if (!attempt) return;

        if (env.reaction) {
          await this.handleReaction(attempt, env.reaction);
          return;
        }

        if (env.attachment) {
          await this.handleAttachment(attempt, env.attachment);
          return;
        }

        await this.handleText(attempt);
      },
    );
  }

  /**
   * Claims the dedupe key of a tracked envelope. A part already `sent` is acked
   * unread; one still `claimed` was begun by an attempt that never finished, so
   * whether it went out is unknown and its text must not be sent twice. Both
   * return `null` after acking.
   */
  private beginAttempt(
    channel: Channel,
    msg: ConsumeMessage,
    env: OutboundMessageEnvelope,
  ): Attempt | null {
    const routing = routingOf(env);
    const attempt: Attempt = {
      channel,
      msg,
      env,
      routing,
      platformMessageIds: [],
      delivered: 0,
      claimKey: null,
    };
    if (!routing) return attempt;

    const key = dedupeKey(routing.outboxMessageId, routing.partIndex);
    const state = this.dedupe.state(key);
    if (state) {
      wideLog.set({
        dedupe_state: state,
        redelivered: msg.fields.redelivered,
      });
      if (state === DEDUPE_STATE.CLAIMED) {
        wideLog.warning("outbound_duplicate_unconfirmed", {
          envelope_id: env.id,
        });
      }
      this.settle(channel, () => channel.ack(msg));
      return null;
    }
    this.dedupe.claim(key);
    attempt.claimKey = key;
    return attempt;
  }

  /**
   * Parse, validate, and platform-check the envelope. Dead-letters and returns
   * `null` on any failure; returns the validated envelope otherwise.
   */
  private parseEnvelope(
    channel: Channel,
    msg: ConsumeMessage,
  ): OutboundMessageEnvelope | null {
    let raw: unknown;
    try {
      raw = JSON.parse(msg.content.toString());
    } catch {
      wideLog.warning("outbound_envelope_unparseable", {
        bytes: msg.content.length,
      });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.ENVELOPE_REJECTED,
          reason: "envelope_unparseable",
        },
        UNSENT,
      );
      return null;
    }

    // Checked before the schema: a newer version may change the shape, and its
    // failure must read as "unsupported", never as a field this consumer lacks.
    const version = versionOf(raw);
    if (version !== OUTBOUND_ENVELOPE_VERSION) {
      const routing = readRouting(raw);
      wideLog.warning("outbound_envelope_unsupported_version", {
        expected: OUTBOUND_ENVELOPE_VERSION,
        got: String(version),
      });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.ENVELOPE_REJECTED,
          reason: "unsupported_envelope_version",
          error_message: `envelope v${String(version)}, consumer supports v${OUTBOUND_ENVELOPE_VERSION}`,
          destination_id: destinationOf(msg),
          envelope_id: routing?.envelopeId,
        },
        { routing, platformMessageIds: [] },
      );
      return null;
    }

    const parsed = this.envelopeSchema.safeParse(raw);
    if (!parsed.success) {
      wideLog.warning("outbound_envelope_invalid", {
        issues: parsed.error.issues.length,
        invalid_fields: parsed.error.issues.map((issue) =>
          issue.path.join("."),
        ),
      });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.ENVELOPE_REJECTED,
          reason: "envelope_invalid",
          error_message: `invalid fields: ${parsed.error.issues.map((issue) => issue.path.join(".")).join(", ")}`,
          destination_id: destinationOf(msg),
        },
        { routing: readRouting(raw), platformMessageIds: [] },
      );
      return null;
    }
    const env = parsed.data;

    // The queue is platform-specific, so a mismatched `platform` means the
    // topology/routing key drifted (or a misrouted publish). Dead-letter it
    // rather than send through the wrong adapter.
    if (env.platform !== this.platform) {
      wideLog.warning("outbound_platform_mismatch", {
        expected: this.platform,
        got: env.platform,
      });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.ENVELOPE_REJECTED,
          reason: "platform_mismatch",
          error_message: `published for ${env.platform}`,
          destination_id: env.destination_id,
          is_channel: env.is_channel,
          envelope_id: env.id,
        },
        { routing: routingOf(env), platformMessageIds: [] },
      );
      return null;
    }

    return env;
  }

  /**
   * File attachment: hand the artifact reference to the platform's file sender
   * (it fetches the bytes and uploads them). No chunking/rendering.
   */
  private async handleAttachment(
    attempt: Attempt,
    attachment: OutboundAttachment,
  ): Promise<void> {
    const { channel, msg, env } = attempt;
    const destinationId = env.destination_id;
    wideLog.set({ attachment_filename: attachment.filename });
    try {
      const notifications = await this.notificationsWhenWindowClosed(
        destinationId,
        env.is_channel,
      );
      if (notifications) {
        wideLog.set({ outbound_mode: "notification" });
        await sendHonouringRateLimit(() =>
          notifications.deliver(destinationId, FILE_WAITING_NOTICE),
        );
      } else {
        await sendHonouringRateLimit(() =>
          this.deliverFile(destinationId, attachment, env.is_channel),
        );
      }
      attempt.delivered = 1;
      this.ackSent(attempt);
    } catch (err) {
      const reason = recordBotFailure("outbound_file_delivery_failed", err, {
        envelope_id: env.id,
        redelivered: msg.fields.redelivered,
      });
      // Never requeue a file (the upload may have landed before the failure) and keep
      // its claim; only a rate limit proves nothing was accepted, and that was retried.
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.SEND_FAILED,
          reason,
          error_message: describeErrorForAlert(err),
          destination_id: destinationId,
          is_channel: env.is_channel,
          envelope_id: env.id,
        },
        attempt,
      );
    }
  }

  /**
   * Reaction path. One idempotent platform call — attaching the same emoji
   * twice is a no-op upstream — so unlike the text path there is no partial
   * state to protect: failure dead-letters for inspection, it never requeues
   * (a redelivered reaction would double-attach nothing, but the ack already
   * failed once and spamming retries at the user is worse than a DLQ entry).
   */
  private async handleReaction(
    attempt: Attempt,
    reaction: OutboundReaction,
  ): Promise<void> {
    const { channel, msg, env } = attempt;
    try {
      if (
        await this.notificationsWhenWindowClosed(
          env.destination_id,
          env.is_channel,
        )
      ) {
        // A reaction to a message the user has not seen answered is meaningless later.
        wideLog.set({ outbound_mode: "reaction_skipped_window_closed" });
      } else {
        await this.deliverReaction(
          env.destination_id,
          reaction,
          env.is_channel,
        );
      }
      wideLog.set({ redelivered: msg.fields.redelivered });
      this.ackSent(attempt);
    } catch (err) {
      wideLog.error(
        "outbound_reaction_failed",
        { envelope_id: env.id, redelivered: msg.fields.redelivered },
        err,
      );
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.SEND_FAILED,
          reason: classifyBotFailure(err),
          error_message: describeErrorForAlert(err),
          destination_id: env.destination_id,
          is_channel: env.is_channel,
          envelope_id: env.id,
        },
        attempt,
      );
    }
  }

  /**
   * Text path. The schema's refine guarantees text, text_parts, attachment, or
   * reaction; a multi-bubble notification arrives as ordered `text_parts`
   * (one logical message) and its bubbles MUST be sent in order, so they are
   * delivered sequentially within this single handle.
   */
  private async handleText(attempt: Attempt): Promise<void> {
    const { channel, msg, env } = attempt;
    const sources = resolveSources(env.text, env.text_parts);
    if (sources.length === 0) {
      wideLog.warning("outbound_envelope_empty", { envelope_id: env.id });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.releaseClaim(attempt);
      this.deadLetter(
        channel,
        msg,
        this.rejection(env, "envelope_empty"),
        attempt,
      );
      return;
    }

    if (env.edit_of_platform_message_id) {
      await this.handleEdit(attempt, sources, env.edit_of_platform_message_id);
      return;
    }

    try {
      const notifications = await this.notificationsWhenWindowClosed(
        env.destination_id,
        env.is_channel,
      );
      if (notifications) {
        await this.deliverAsNotification(notifications, attempt, sources);
      } else {
        await this.deliverSources(attempt, sources);
      }
      wideLog.set({ delivered_count: attempt.delivered });
      // `redelivered` only ever appeared on the error branches, so a duplicate
      // that succeeded — the exact case the at-least-once queue produces — was
      // indistinguishable from a first delivery in Loki.
      wideLog.set({ redelivered: msg.fields.redelivered });
      // Non-empty source text that rendered to nothing on every chunk: don't
      // silently ack it away (the backend recorded it DELIVERED). Dead-letter
      // it so the dropped message is visible for inspection.
      if (attempt.delivered === 0) {
        wideLog.warning("outbound_text_rendered_empty", {
          envelope_id: env.id,
        });
        wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
        this.releaseClaim(attempt);
        this.deadLetter(
          channel,
          msg,
          this.rejection(env, "rendered_empty"),
          attempt,
        );
        return;
      }
      this.ackSent(attempt);
    } catch (err) {
      this.failTextDelivery(attempt, err);
    }
  }

  /**
   * Edits an already-sent message in place. A platform without an edit
   * primitive, or an edit that would not fit one message, fails loudly: the
   * alternative is a second message the sender meant to replace the first.
   */
  private async handleEdit(
    attempt: Attempt,
    sources: string[],
    targetPlatformMessageId: string,
  ): Promise<void> {
    const { channel, msg, env } = attempt;
    wideLog.set({ outbound_mode: "edit" });

    const deliverEdit = this.deliverEdit;
    if (!deliverEdit) {
      wideLog.warning("outbound_edit_unsupported", { envelope_id: env.id });
      wideLog.fail(BOT_FAILURE_REASON.EDIT_UNSUPPORTED);
      this.releaseClaim(attempt);
      this.deadLetter(
        channel,
        msg,
        {
          kind: DELIVERY_FAILURE_KIND.SEND_FAILED,
          reason: BOT_FAILURE_REASON.EDIT_UNSUPPORTED,
          destination_id: env.destination_id,
          is_channel: env.is_channel,
          envelope_id: env.id,
        },
        attempt,
      );
      return;
    }

    const messages = this.renderMessages(sources);
    const [only] = messages;
    if (messages.length !== 1 || only === undefined) {
      wideLog.warning("outbound_edit_not_single_message", {
        envelope_id: env.id,
        messages: messages.length,
      });
      wideLog.fail(BOT_FAILURE_REASON.ENVELOPE_REJECTED);
      this.releaseClaim(attempt);
      this.deadLetter(
        channel,
        msg,
        this.rejection(env, "edit_requires_single_message"),
        attempt,
      );
      return;
    }

    try {
      const editedId = await sendHonouringRateLimit(() =>
        deliverEdit(
          env.destination_id,
          targetPlatformMessageId,
          only,
          env.is_channel,
        ),
      );
      attempt.delivered = 1;
      if (editedId) attempt.platformMessageIds.push(editedId);
      wideLog.set({ delivered_count: attempt.delivered });
      wideLog.set({ redelivered: msg.fields.redelivered });
      this.ackSent(attempt);
    } catch (err) {
      this.failTextDelivery(attempt, err);
    }
  }

  /** The alert for an envelope this consumer refuses to send, before any send. */
  private rejection(
    env: OutboundMessageEnvelope,
    reason: string,
  ): DeliveryFailure {
    return {
      kind: DELIVERY_FAILURE_KIND.ENVELOPE_REJECTED,
      reason,
      destination_id: env.destination_id,
      is_channel: env.is_channel,
      envelope_id: env.id,
    };
  }

  /** Settles a text or edit send that threw: one retry if nothing went out and a retry can help, else the DLQ. */
  private failTextDelivery(attempt: Attempt, err: unknown): void {
    const { channel, msg, env } = attempt;
    wideLog.set({ delivered_count: attempt.delivered });
    const reason = recordBotFailure("outbound_delivery_failed", err, {
      envelope_id: env.id,
      delivered: attempt.delivered,
      redelivered: msg.fields.redelivered,
    });
    // One retry, only for a failure a retry can get past and only if nothing went out:
    // requeue re-delivers the WHOLE envelope, so after a partial send it would duplicate
    // the user. A permanent failure (chat gone, bot blocked) dead-letters at once.
    const requeue =
      isTransientBotFailure(reason) &&
      attempt.delivered === 0 &&
      !msg.fields.redelivered;
    wideLog.set({ requeued: requeue });
    if (requeue) {
      this.requeue(attempt);
      return;
    }
    this.releaseClaim(attempt);
    this.deadLetter(
      channel,
      msg,
      {
        kind: DELIVERY_FAILURE_KIND.SEND_FAILED,
        reason,
        error_message: describeErrorForAlert(err),
        destination_id: env.destination_id,
        is_channel: env.is_channel,
        envelope_id: env.id,
      },
      attempt,
    );
  }

  /** The template sender when free-form sends are refused right now; null otherwise or without a window. */
  private async notificationsWhenWindowClosed(
    destinationId: string,
    isChannel: boolean,
  ): Promise<OutboundNotifications | null> {
    if (!this.notifications) return null;
    return (await this.notifications.windowClosed(destinationId, isChannel))
      ? this.notifications
      : null;
  }

  /**
   * Outside the platform's messaging window: the whole envelope as ONE template
   * message, bubbles joined, so a multi-bubble reply is one notification and
   * never several out of order.
   */
  private async deliverAsNotification(
    notifications: OutboundNotifications,
    attempt: Attempt,
    sources: string[],
  ): Promise<void> {
    const text = sources
      .flatMap((source) => segmentIntoBubbles(source))
      .map((bubble) => renderForPlatform(bubble, this.platform).trim())
      .filter(Boolean)
      .join("\n\n");
    wideLog.set({ outbound_mode: "notification" });
    if (!text) return;
    await sendHonouringRateLimit(() =>
      notifications.deliver(attempt.env.destination_id, text),
    );
    attempt.delivered = 1;
  }

  /**
   * Segments each source into bubbles, chunks them by the platform limit, then renders each
   * chunk so every sent message is valid platform markdown. Segmentation happens HERE (not
   * only in the streamer) because these messages — executor replies, reminders, workflow
   * results — never went through it and used to ship as one wall with `<NEW_MESSAGE_BREAK>`
   * visible. Chunks are sized by RENDERED length, since markdown can expand when rendered
   * (e.g. Telegram tables into `<pre>`) and overflow the platform's message limit.
   */
  private renderMessages(sources: string[]): string[] {
    const render = (chunk: string): string =>
      renderForPlatform(chunk, this.platform);
    return (
      sources
        .flatMap((source) => segmentIntoBubbles(source))
        .flatMap((bubble) => chunkResponse(bubble, this.platform, render))
        .map(render)
        // A chunk made up solely of strippable markup (e.g. a lone horizontal
        // rule) renders to nothing; platform send APIs reject empty text, so
        // skip it instead of throwing and dead-lettering the whole envelope.
        .filter((rendered) => rendered.trim())
    );
  }

  /**
   * Sends the rendered messages one after another, recording each platform id on
   * the attempt as it goes so a throw mid-send still says what already went out.
   * Only the first message quotes the envelope's reply-to target.
   */
  private async deliverSources(
    attempt: Attempt,
    sources: string[],
  ): Promise<void> {
    const { destination_id, is_channel, reply_to_platform_message_id } =
      attempt.env;
    let replyTo = reply_to_platform_message_id ?? undefined;
    // Await each send before the next so the bubbles arrive in the published
    // order — never fan these out concurrently.
    for (const rendered of this.renderMessages(sources)) {
      const quoted = replyTo;
      const platformMessageId = await sendHonouringRateLimit(() =>
        quoted
          ? this.deliver(destination_id, rendered, is_channel, {
              replyToPlatformMessageId: quoted,
            })
          : this.deliver(destination_id, rendered, is_channel),
      );
      replyTo = undefined;
      attempt.delivered += 1;
      if (platformMessageId) attempt.platformMessageIds.push(platformMessageId);
    }
  }
}

/**
 * Sends once and, when the platform rate-limited it, once more after the wait
 * the platform named. A rate limit is the one failure where the platform
 * provably accepted nothing, so the resend cannot duplicate a message.
 */
async function sendHonouringRateLimit<T>(send: () => Promise<T>): Promise<T> {
  try {
    return await send();
  } catch (err) {
    const waitMs = retryAfterMs(err);
    if (waitMs === null) throw err;
    wideLog.set({ rate_limited_wait_ms: waitMs });
    await new Promise((resolve) => setTimeout(resolve, waitMs));
    return await send();
  }
}

/** What a tracked envelope's receipt and dedupe record are filed under; null for an untracked one. */
function routingOf(env: OutboundMessageEnvelope): Routing | null {
  return env.outbox_message_id
    ? {
        envelopeId: env.id,
        outboxMessageId: env.outbox_message_id,
        partIndex: env.part_index,
      }
    : null;
}

/** The version an unvalidated envelope declares; one that declares none is v1. */
function versionOf(raw: unknown): unknown {
  if (raw && typeof raw === "object" && "v" in raw) return raw.v;
  return OUTBOUND_ENVELOPE_VERSION;
}

/** Ordered list of raw markdown sources to send: text_parts wins over text. */
function resolveSources(
  text: string | null | undefined,
  textParts: string[] | null | undefined,
): string[] {
  if (textParts?.length) return textParts;
  if (text) return [text];
  return [];
}

/** Matches the API's limit on a reported destination_id. */
const DESTINATION_ID_MAX_LENGTH = 256;

/**
 * The destination a message is delivered to, read without validating the envelope:
 * only a plausible id, since it is reported as-is and a bad one would fail the report.
 */
function destinationOf(msg: ConsumeMessage): string | undefined {
  try {
    const parsed: unknown = JSON.parse(msg.content.toString());
    if (parsed && typeof parsed === "object" && "destination_id" in parsed) {
      const id = parsed.destination_id;
      if (
        typeof id === "string" &&
        id.length > 0 &&
        id.length <= DESTINATION_ID_MAX_LENGTH
      ) {
        return id;
      }
    }
  } catch {
    // Unparseable: handle() dead-letters it; there is no destination to read.
  }
  return undefined;
}

/** The lane a message waits in, picked before validation. */
function laneKey(msg: ConsumeMessage): string {
  return destinationOf(msg) ?? UNREADABLE_LANE;
}

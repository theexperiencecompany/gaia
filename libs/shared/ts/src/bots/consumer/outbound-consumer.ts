/**
 * Consumes one platform's outbound-message queue and delivers each message via
 * the adapter's platform send primitive.
 *
 * Backend-originated messages (executor replies, reminders) are published to a
 * durable per-platform queue; this consumer renders the platform-native
 * markdown and hands each (chunked) message to the adapter. Fire-and-forget
 * with a one-retry + dead-letter-queue safety net, and a single consumer per
 * platform in Phase 1 (see the idempotency note in {@link OutboundConsumer.handle}).
 */

import { type Channel, type ConsumeMessage, connect } from "amqplib";
import type { PlatformName } from "../types";
import { renderForPlatform } from "../utils/formatters";
import { type BotLogger, createBotLogger } from "../utils/logger";
import { chunkResponse } from "../utils/text";
import { outboundMessageEnvelopeSchema } from "./envelope";
import {
  dlqName,
  OUTBOUND_DLX,
  OUTBOUND_QUEUES,
  workQueueArguments,
} from "./topology";

/** Messages prefetched per consumer — bounds in-flight work for backpressure. */
const PREFETCH = 8;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

/** Sends one already-rendered message to a platform destination. */
type DeliverFn = (destinationId: string, text: string) => Promise<void>;

export class OutboundConsumer {
  private conn: Awaited<ReturnType<typeof connect>> | null = null;
  private channel: Channel | null = null;
  private stopped = false;
  private reconnectDelayMs = RECONNECT_BASE_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly logger: BotLogger;

  constructor(
    private readonly platform: PlatformName,
    private readonly url: string,
    private readonly deliver: DeliverFn,
  ) {
    this.logger = createBotLogger(platform, "outbound-consumer");
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

  private async connect(): Promise<void> {
    if (this.stopped) return;
    try {
      this.conn = await connect(this.url);
      this.conn.on("close", () => this.scheduleReconnect());
      this.conn.on("error", () => undefined); // 'close' drives reconnect
      this.channel = await this.conn.createChannel();

      const queue = OUTBOUND_QUEUES[this.platform];
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
      await this.channel.prefetch(PREFETCH);
      await this.channel.consume(queue, (msg) => void this.handle(msg));

      this.reconnectDelayMs = RECONNECT_BASE_MS;
      this.logger.info("outbound_consumer_started", { queue });
    } catch (err) {
      this.logger.error("outbound_consumer_connect_failed", undefined, err);
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    // Close the (possibly still-open) connection before dropping the reference,
    // so a channel-level failure after connect() succeeded does not leak it.
    void this.channel?.close().catch(() => undefined);
    void this.conn?.close().catch(() => undefined);
    this.channel = null;
    this.conn = null;
    const delay = this.reconnectDelayMs;
    this.reconnectDelayMs = Math.min(delay * 2, RECONNECT_MAX_MS);
    this.logger.warn("outbound_consumer_reconnecting", { wait_ms: delay });
    this.reconnectTimer = setTimeout(() => void this.connect(), delay);
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
      this.logger.warn("outbound_settle_skipped", {
        reason: "channel replaced mid-handle",
      });
    }
  }

  private async handle(msg: ConsumeMessage | null): Promise<void> {
    const channel = this.channel;
    if (!msg || !channel) return;

    // IDEMPOTENCY: none in Phase 1. RabbitMQ is at-least-once and does NOT
    // deduplicate — a message can be redelivered (and re-sent) if this worker
    // delivers successfully but dies before ack. With a SINGLE consumer per
    // platform that window is negligible. BEFORE running multiple workers per
    // platform, add a dedupe check on `env.id` backed by SHARED state (e.g.
    // Redis SETNX with a TTL) here — an in-process cache will not work because
    // duplicates land on a different worker process.
    let raw: unknown;
    try {
      raw = JSON.parse(msg.content.toString());
    } catch {
      this.settle(channel, () => channel.nack(msg, false, false)); // unparseable → DLQ
      return;
    }
    const parsed = outboundMessageEnvelopeSchema.safeParse(raw);
    if (!parsed.success) {
      this.logger.warn("outbound_envelope_invalid", {
        issues: parsed.error.issues.length,
      });
      this.settle(channel, () => channel.nack(msg, false, false)); // schema mismatch → DLQ
      return;
    }
    const env = parsed.data;

    try {
      // Chunk the raw markdown by the platform limit, then render each chunk so
      // every sent message is valid platform markdown.
      for (const chunk of chunkResponse(env.text, this.platform)) {
        await this.deliver(
          env.destination_id,
          renderForPlatform(chunk, this.platform),
        );
      }
      this.settle(channel, () => channel.ack(msg));
    } catch (err) {
      this.logger.error(
        "outbound_delivery_failed",
        { id: env.id, redelivered: msg.fields.redelivered },
        err,
      );
      // One retry via requeue, then dead-letter on the second failure.
      this.settle(channel, () =>
        channel.nack(msg, false, !msg.fields.redelivered),
      );
    }
  }
}

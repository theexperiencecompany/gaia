import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock amqplib at the I/O boundary. Everything else (validation, chunking,
// rendering, ack/nack policy) runs as real production code. The mocks are built
// via vi.hoisted so the hoisted vi.mock factory can reference them safely.
const { connection, channel } = vi.hoisted(() => {
  const channel = {
    assertExchange: vi.fn().mockResolvedValue(undefined),
    assertQueue: vi.fn().mockResolvedValue(undefined),
    bindQueue: vi.fn().mockResolvedValue(undefined),
    prefetch: vi.fn().mockResolvedValue(undefined),
    consume: vi.fn().mockResolvedValue(undefined),
    ack: vi.fn(),
    nack: vi.fn(),
  };
  const connection = {
    on: vi.fn(),
    createChannel: vi.fn().mockResolvedValue(channel),
    close: vi.fn().mockResolvedValue(undefined),
  };
  return { connection, channel };
});

vi.mock("amqplib", () => ({
  connect: vi.fn().mockResolvedValue(connection),
}));

import { OutboundConsumer } from "../../../../../libs/shared/ts/src/bots/consumer/outbound-consumer";

type Handler = (msg: unknown) => unknown;

/** A fake amqplib message carrying ``payload`` (string sent verbatim). */
function msgFor(payload: unknown, redelivered = false) {
  const content =
    typeof payload === "string" ? payload : JSON.stringify(payload);
  return { content: Buffer.from(content), fields: { redelivered } };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

/** Boots a consumer and returns the message handler it registered with consume(). */
async function startAndCaptureHandler(
  platform: "whatsapp" | "discord",
  deliver: (id: string, text: string) => Promise<void>,
): Promise<Handler> {
  const consumer = new OutboundConsumer(platform, "amqp://test", deliver);
  await consumer.start();
  const calls = channel.consume.mock.calls;
  const last = calls[calls.length - 1];
  if (!last) throw new Error("consume() was never called");
  return last[1] as Handler;
}

/** The consume callback is fire-and-forget; drain the microtask chain. */
async function deliverMessage(handle: Handler, msg: unknown): Promise<void> {
  handle(msg);
  await flush();
}

beforeEach(() => {
  vi.clearAllMocks();
  connection.createChannel.mockResolvedValue(channel);
  channel.consume.mockResolvedValue(undefined);
});

describe("OutboundConsumer message handling", () => {
  it("renders to the platform dialect, delivers, and acks a valid message", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      text: "**hi**",
      enqueued_at: "2026-01-01T00:00:00Z",
    });

    await deliverMessage(handle, msg);

    // renderForPlatform("whatsapp") converts CommonMark **hi** → WhatsApp *hi*.
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver).toHaveBeenCalledWith("1555", "*hi*");
    expect(channel.ack).toHaveBeenCalledWith(msg);
    expect(channel.nack).not.toHaveBeenCalled();
  });

  it("dead-letters unparseable JSON without delivering", async () => {
    const deliver = vi.fn();
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    const msg = msgFor("{ not json");

    await deliverMessage(handle, msg);

    expect(deliver).not.toHaveBeenCalled();
    expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ, no requeue
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("dead-letters a schema-invalid envelope (missing destination_id)", async () => {
    const deliver = vi.fn();
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      text: "hi",
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliver).not.toHaveBeenCalled();
    expect(channel.nack).toHaveBeenCalledWith(msg, false, false);
  });

  it("splits a message over the platform limit into multiple sends", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler("discord", deliver); // 2000-char limit
    const big = "word ".repeat(800); // ~4000 chars
    const msg = msgFor({
      id: "1",
      platform: "discord",
      destination_id: "d1",
      text: big,
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliver.mock.calls.length).toBeGreaterThan(1);
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("requeues once when delivery fails on the first attempt", async () => {
    const deliver = vi.fn().mockRejectedValue(new Error("send failed"));
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    const msg = msgFor(
      {
        id: "1",
        platform: "whatsapp",
        destination_id: "1555",
        text: "hi",
        enqueued_at: "t",
      },
      false,
    );

    await deliverMessage(handle, msg);

    expect(channel.nack).toHaveBeenCalledWith(msg, false, true); // requeue
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("dead-letters when delivery fails again after redelivery", async () => {
    const deliver = vi.fn().mockRejectedValue(new Error("send failed"));
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    const msg = msgFor(
      {
        id: "1",
        platform: "whatsapp",
        destination_id: "1555",
        text: "hi",
        enqueued_at: "t",
      },
      true,
    );

    await deliverMessage(handle, msg);

    expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ
  });
});

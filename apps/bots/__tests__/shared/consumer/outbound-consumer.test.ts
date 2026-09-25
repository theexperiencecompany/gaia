import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock amqplib at the I/O boundary. Everything else (validation, chunking,
// rendering, ack/nack policy) runs as real production code. The mocks are built
// via vi.hoisted so the hoisted vi.mock factory can reference them safely.
const { connection, channel, connect } = vi.hoisted(() => {
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
  const connect = vi.fn().mockResolvedValue(connection);
  return { connection, channel, connect };
});

vi.mock("amqplib", () => ({ connect }));

import type {
  OutboundAttachment,
  OutboundReaction,
} from "../../../../../libs/shared/ts/src/bots/consumer/envelope";
import { OutboundConsumer } from "../../../../../libs/shared/ts/src/bots/consumer/outbound-consumer";
import { hashLogIdentifier } from "../../../../../libs/shared/ts/src/bots/utils/logger";
import { captureBotEvents } from "../helpers/capture-bot-event";

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
  platform: "whatsapp" | "discord" | "telegram",
  deliver: (id: string, text: string) => Promise<void>,
  deliverFile: (
    id: string,
    attachment: OutboundAttachment,
    isChannel: boolean,
  ) => Promise<void> = async () => undefined,
  gaiaApiUrl = "https://api.gaia.test",
  deliverReaction: (
    id: string,
    reaction: OutboundReaction,
    isChannel: boolean,
  ) => Promise<void> = async () => undefined,
): Promise<Handler> {
  const consumer = new OutboundConsumer(
    platform,
    "amqp://test",
    deliver,
    deliverFile,
    gaiaApiUrl,
    deliverReaction,
  );
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
    // No is_channel on the envelope → a DM (false).
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver).toHaveBeenCalledWith("1555", "*hi*", false);
    expect(channel.ack).toHaveBeenCalledWith(msg);
    expect(channel.nack).not.toHaveBeenCalled();
  });

  it("passes is_channel through to the deliverer for a channel send", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler("discord", deliver);
    const msg = msgFor({
      id: "1",
      platform: "discord",
      destination_id: "chan-1",
      is_channel: true,
      text: "hi",
      enqueued_at: "2026-01-01T00:00:00Z",
    });

    await deliverMessage(handle, msg);

    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver).toHaveBeenCalledWith("chan-1", expect.any(String), true);
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

  /** A platform send error the way the bots' clients raise it: a status and a reason. */
  function platformError(status: number, description: string) {
    return Object.assign(new Error(`${status}: ${description}`), {
      name: "GrammyError",
      error_code: status,
      description,
    });
  }

  function firstAttempt() {
    return msgFor(
      {
        id: "env-1",
        platform: "telegram",
        destination_id: "5550001",
        text: "hi",
        enqueued_at: "t",
      },
      false,
    );
  }

  it.each([
    ["a server error", platformError(502, "Bad Gateway"), "server_error"],
    [
      "a rate limit",
      platformError(429, "Too Many Requests: retry after 5"),
      "rate_limited",
    ],
    ["a timeout", new Error("Request timed out"), "timeout"],
  ])(
    "requeues once on %s, which a retry can get past",
    async (_label, error, reason) => {
      const handle = await startAndCaptureHandler(
        "telegram",
        vi.fn().mockRejectedValue(error),
      );
      const msg = firstAttempt();

      const [event] = await captureBotEvents("outbound_message", () =>
        deliverMessage(handle, msg),
      );

      expect(channel.nack).toHaveBeenCalledWith(msg, false, true); // requeue
      expect(channel.ack).not.toHaveBeenCalled();
      expect(event).toMatchObject({
        outcome: "failed",
        reason,
        requeued: true,
      });
    },
  );

  it.each([
    [
      "a chat that does not exist",
      platformError(400, "Bad Request: chat not found"),
      "destination_not_found",
    ],
    [
      "a user who blocked the bot",
      platformError(403, "Forbidden: bot was blocked by the user"),
      "destination_blocked",
    ],
    ["a forbidden send", platformError(403, "Forbidden"), "unauthorized"],
    [
      "a request the platform rejects",
      platformError(400, "Bad Request: message text is empty"),
      "client_error",
    ],
  ])(
    "dead-letters %s on the first attempt, since a retry fails the same way",
    async (_label, error, reason) => {
      const handle = await startAndCaptureHandler(
        "telegram",
        vi.fn().mockRejectedValue(error),
      );
      const msg = firstAttempt();

      const [event] = await captureBotEvents("outbound_message", () =>
        deliverMessage(handle, msg),
      );

      expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ
      expect(event).toMatchObject({
        outcome: "failed",
        reason,
        requeued: false,
      });
    },
  );

  it("a send the platform rejects is a failed outbound event naming the reason and the hashed chat", async () => {
    // grammY's GrammyError: Telegram's status in error_code, its reason in description.
    const chatNotFound = Object.assign(
      new Error(
        "Call to 'sendMessage' failed! (400: Bad Request: chat not found)",
      ),
      {
        name: "GrammyError",
        error_code: 400,
        description: "Bad Request: chat not found",
      },
    );
    const handle = await startAndCaptureHandler(
      "telegram",
      vi.fn().mockRejectedValue(chatNotFound),
    );
    const msg = msgFor({
      id: "env-1",
      platform: "telegram",
      destination_id: "5550001",
      text: "hi",
      enqueued_at: "t",
    });

    const [event] = await captureBotEvents("outbound_message", () =>
      deliverMessage(handle, msg),
    );

    expect(event).toMatchObject({
      outcome: "failed",
      reason: "destination_not_found",
      http_status: 400,
      envelope_id: "env-1",
      destination_hash: hashLogIdentifier("5550001"),
    });
    expect(JSON.stringify(event)).not.toContain("5550001");
    expect(event.errors).toEqual([
      expect.objectContaining({
        msg: "outbound_delivery_failed",
        error_type: "GrammyError",
        http_status: 400,
      }),
    ]);
  });

  it("dead-letters when delivery fails again after redelivery", async () => {
    const deliver = vi.fn().mockRejectedValue(new Error("Request timed out"));
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

  it("dead-letters non-empty text that renders to nothing instead of acking", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler("whatsapp", deliver);
    // A lone horizontal rule is non-empty source but renders to "" on WhatsApp,
    // so there is nothing sendable. The backend already recorded it DELIVERED;
    // acking here would lose it silently, so it must dead-letter instead.
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      text: "---",
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliver).not.toHaveBeenCalled();
    expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ, not acked
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("routes an attachment to deliverFile (not the text path) and acks", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "whatsapp",
      deliver,
      deliverFile,
    );
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      attachment: {
        conversation_id: "conv-1",
        path: "artifacts/report.pdf",
        filename: "report.pdf",
      },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverFile).toHaveBeenCalledWith(
      "1555",
      expect.objectContaining({
        conversation_id: "conv-1",
        path: "artifacts/report.pdf",
        filename: "report.pdf",
      }),
      false,
    );
    expect(deliver).not.toHaveBeenCalled(); // file path, never the text sender
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("hands a group's photo to deliverFile addressed to the channel", async () => {
    // A browser run asked for in a group streams its step photos back into
    // that group; dropping is_channel here sent them to a user id instead.
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "discord",
      vi.fn(),
      deliverFile,
    );
    const msg = msgFor({
      id: "1",
      platform: "discord",
      destination_id: "chan-42",
      is_channel: true,
      attachment: {
        url: "https://cdn.example.com/shot-1.png",
        filename: "browser-step-1.png",
      },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverFile).toHaveBeenCalledWith(
      "chan-42",
      expect.objectContaining({ url: "https://cdn.example.com/shot-1.png" }),
      true,
    );
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("delivers a plain-http photo served by the configured GAIA API", async () => {
    // Dev and self-hosted setups serve step screenshots off the API's own host
    // over http; dead-lettering those is how every browser step photo vanished.
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "whatsapp",
      vi.fn(),
      deliverFile,
      "http://localhost:8121",
    );
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      attachment: {
        url: "http://localhost:8121/shots/c0de/1.png",
        filename: "browser-step-1.png",
        caption: "Step 1 \u00b7 open the site",
      },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverFile).toHaveBeenCalledWith(
      "1555",
      expect.objectContaining({
        url: "http://localhost:8121/shots/c0de/1.png",
        caption: "Step 1 \u00b7 open the site",
      }),
      false,
    );
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("dead-letters a plain-http photo from any other origin", async () => {
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "whatsapp",
      vi.fn(),
      deliverFile,
      "http://localhost:8121",
    );
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      attachment: { url: "http://evil.example/x.png", filename: "x.png" },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverFile).not.toHaveBeenCalled();
    expect(channel.nack).toHaveBeenCalledWith(msg, false, false);
  });

  it("dead-letters a failed file delivery WITHOUT requeue, even on first attempt", async () => {
    // A file send isn't idempotent and a failure can surface after the platform
    // already accepted the upload — requeueing would deliver a duplicate. So,
    // unlike the text path, the file path never requeues (requeue=false here).
    const deliver = vi.fn();
    const deliverFile = vi.fn().mockRejectedValue(new Error("upload failed"));
    const handle = await startAndCaptureHandler(
      "whatsapp",
      deliver,
      deliverFile,
    );
    const msg = msgFor(
      {
        id: "1",
        platform: "whatsapp",
        destination_id: "1555",
        attachment: {
          conversation_id: "conv-1",
          path: "artifacts/report.pdf",
          filename: "report.pdf",
        },
        enqueued_at: "t",
      },
      false, // first attempt — the text path WOULD requeue here; the file path must not
    );

    await deliverMessage(handle, msg);

    expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ, no requeue
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("dead-letters a PARTIALLY-sent multi-chunk message without requeue", async () => {
    // First chunk delivers, the second throws. Requeue re-delivers the WHOLE
    // envelope, so once any chunk is out, requeueing would re-send the delivered
    // chunk(s). Policy: requeue only when delivered === 0; here it must DLQ.
    const deliver = vi
      .fn()
      .mockResolvedValueOnce(undefined) // chunk 1 sent
      .mockRejectedValueOnce(new Error("send failed")); // chunk 2 fails
    const handle = await startAndCaptureHandler("discord", deliver); // 2000-char limit
    const big = "word ".repeat(800); // ~4000 chars → multiple chunks
    const msg = msgFor(
      {
        id: "1",
        platform: "discord",
        destination_id: "d1",
        text: big,
        enqueued_at: "t",
      },
      false, // first attempt — but delivered>0 must still prevent requeue
    );

    await deliverMessage(handle, msg);

    expect(deliver.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(channel.nack).toHaveBeenCalledWith(msg, false, false); // DLQ, NOT requeue
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("when an envelope carries BOTH text and attachment, the file path wins (text not double-sent)", async () => {
    // Our producers never set both (file envelopes have no text), but pin the
    // precedence so a future change that starts setting both is a visible
    // decision rather than a silent double-send.
    const deliver = vi.fn().mockResolvedValue(undefined);
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "whatsapp",
      deliver,
      deliverFile,
    );
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      text: "some caption-ish text",
      attachment: {
        conversation_id: "c",
        path: "a/f.pdf",
        filename: "f.pdf",
      },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverFile).toHaveBeenCalledTimes(1);
    expect(deliver).not.toHaveBeenCalled(); // text is not also sent as a message
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("routes a reaction to deliverReaction (not the text path) and acks", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const deliverReaction = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(
      "whatsapp",
      deliver,
      async () => undefined,
      "https://api.gaia.test",
      deliverReaction,
    );
    const msg = msgFor({
      id: "1",
      platform: "whatsapp",
      destination_id: "1555",
      reaction: { target_platform_message_id: "wamid.123", emoji: "👍" },
      enqueued_at: "t",
    });

    await deliverMessage(handle, msg);

    expect(deliverReaction).toHaveBeenCalledWith(
      "1555",
      { target_platform_message_id: "wamid.123", emoji: "👍" },
      false,
    );
    expect(deliver).not.toHaveBeenCalled(); // no text bubble alongside the reaction
    expect(channel.ack).toHaveBeenCalledWith(msg);
  });

  it("dead-letters a failed reaction WITHOUT requeue, even on first attempt", async () => {
    // Attaching is idempotent upstream, but a failure already means the ack
    // did not land — retrying the whole envelope would re-drive the attach
    // against a target the platform just rejected. Dead-letter for inspection.
    const deliverReaction = vi
      .fn()
      .mockRejectedValue(new Error("attach failed"));
    const handle = await startAndCaptureHandler(
      "whatsapp",
      vi.fn().mockResolvedValue(undefined),
      async () => undefined,
      "https://api.gaia.test",
      deliverReaction,
    );
    const msg = msgFor(
      {
        id: "1",
        platform: "whatsapp",
        destination_id: "1555",
        reaction: { target_platform_message_id: "wamid.123", emoji: "👍" },
        enqueued_at: "t",
      },
      false, // first attempt — still no requeue on the reaction path
    );

    await deliverMessage(handle, msg);

    expect(channel.nack).toHaveBeenCalledWith(msg, false, false);
    expect(channel.ack).not.toHaveBeenCalled();
  });

  it("delivers one chat's messages in published order while other chats proceed", async () => {
    const order: string[] = [];
    let releasePhoto: () => void = () => undefined;
    const deliverFile = vi.fn(async (id: string) => {
      await new Promise<void>((resolve) => {
        releasePhoto = resolve;
      });
      order.push(`photo:${id}`);
    });
    const deliver = vi.fn(async (id: string) => {
      order.push(`text:${id}`);
    });
    const handle = await startAndCaptureHandler(
      "telegram",
      deliver,
      deliverFile,
    );
    const photo = msgFor({
      id: "p",
      platform: "telegram",
      destination_id: "chat-a",
      attachment: { url: "https://cdn.test/1.png", filename: "1.png" },
      enqueued_at: "t",
    });
    const recap = msgFor({
      id: "r",
      platform: "telegram",
      destination_id: "chat-a",
      text: "recap",
      enqueued_at: "t",
    });
    const other = msgFor({
      id: "o",
      platform: "telegram",
      destination_id: "chat-b",
      text: "hi",
      enqueued_at: "t",
    });

    handle(photo);
    handle(recap);
    handle(other);
    await flush();
    expect(order).toEqual(["text:chat-b"]);

    releasePhoto();
    await flush();
    await flush();
    expect(order).toEqual(["text:chat-b", "photo:chat-a", "text:chat-a"]);
  });
});

describe("OutboundConsumer lifecycle", () => {
  it("never starts consuming when stopped while still connecting", async () => {
    // A bot whose boot fails (its health port taken) stops the consumer while
    // the broker connection is still opening; the connection then completed and
    // the dead bot kept taking every other process's replies off the queue.
    let opened!: (value: typeof connection) => void;
    connect.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          opened = resolve;
        }),
    );
    const consumer = new OutboundConsumer(
      "telegram",
      "amqp://test",
      async () => undefined,
      async () => undefined,
      "https://api.gaia.test",
    );

    const starting = consumer.start();
    await flush();
    await consumer.stop();
    opened(connection);
    await starting;

    expect(channel.consume).not.toHaveBeenCalled();
    expect(connection.close).toHaveBeenCalled();
  });
});

/**
 * A whole browser run as a bot user sees it: step photos, handoff, result.
 *
 * The API publishes one envelope per card onto the platform's outbound queue;
 * this drives those envelopes through the real OutboundConsumer — segmentation
 * (segmentIntoBubbles), platform rendering, photo routing — with only amqplib
 * and the platform senders faked. If the run stops emitting photos, swallows
 * the handoff link, or ships the result as one wall with a visible sentinel,
 * this goes red.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

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

import type { OutboundAttachment } from "../../../../../libs/shared/ts/src/bots/consumer/envelope";
import { OutboundConsumer } from "../../../../../libs/shared/ts/src/bots/consumer/outbound-consumer";

type Handler = (msg: unknown) => unknown;

function msgFor(payload: unknown) {
  return {
    content: Buffer.from(JSON.stringify(payload)),
    fields: { redelivered: false },
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function startAndCaptureHandler(
  deliver: (id: string, text: string) => Promise<void>,
  deliverFile: (
    id: string,
    attachment: OutboundAttachment,
    isChannel: boolean,
  ) => Promise<void>,
): Promise<Handler> {
  const consumer = new OutboundConsumer(
    "discord",
    "amqp://test",
    deliver,
    deliverFile,
    "https://api.gaia.test",
  );
  await consumer.start();
  const calls = channel.consume.mock.calls;
  const last = calls[calls.length - 1];
  if (!last) throw new Error("consume() was never called");
  return last[1] as Handler;
}

async function deliverMessage(handle: Handler, msg: unknown): Promise<void> {
  handle(msg);
  await flush();
}

const AT = "2026-01-01T00:00:00Z";
const DEST = "user-dm-1";
const LIVE_LINK = "https://gaia.test/live/take-a-look";

function textEnvelope(id: string, text: string) {
  return msgFor({
    id,
    platform: "discord",
    destination_id: DEST,
    text,
    enqueued_at: AT,
  });
}

function photoEnvelope(id: string, url: string, caption: string) {
  return msgFor({
    id,
    platform: "discord",
    destination_id: DEST,
    attachment: { url, filename: `step-${id}.png`, caption },
    enqueued_at: AT,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  connection.createChannel.mockResolvedValue(channel);
  channel.consume.mockResolvedValue(undefined);
});

describe("a browser run delivered to a bot user", () => {
  it("sends step photos, handoff bubbles, and the segmented result in order", async () => {
    const deliver = vi.fn().mockResolvedValue(undefined);
    const deliverFile = vi.fn().mockResolvedValue(undefined);
    const handle = await startAndCaptureHandler(deliver, deliverFile);

    const envelopes = [
      textEnvelope(
        "session",
        `Starting the browser run — watch it live here: ${LIVE_LINK}`,
      ),
      photoEnvelope(
        "step-1",
        "https://cdn.test/shot-1.png",
        "Step 1 · Opening the booking page",
      ),
      photoEnvelope(
        "step-2",
        "https://cdn.test/shot-2.png",
        "Step 2 · Reading the sign-in wall",
      ),
      textEnvelope(
        "handoff",
        `I need you in the browser: sign in and come back. Open this to take over: ${LIVE_LINK}`,
      ),
      textEnvelope(
        "result",
        "The table is booked for 7pm on Friday, confirmed twice with the restaurant.<NEW_MESSAGE_BREAK>Your confirmation code is ABC123 and the host has your name on the booking.",
      ),
    ];
    for (const envelope of envelopes) {
      await deliverMessage(handle, envelope);
    }

    // Step photos ride the file path, in run order, captions attached.
    expect(deliverFile).toHaveBeenCalledTimes(2);
    expect(deliverFile).toHaveBeenNthCalledWith(
      1,
      DEST,
      expect.objectContaining({
        url: "https://cdn.test/shot-1.png",
        caption: "Step 1 · Opening the booking page",
      }),
      false,
    );
    expect(deliverFile).toHaveBeenNthCalledWith(
      2,
      DEST,
      expect.objectContaining({
        url: "https://cdn.test/shot-2.png",
        caption: "Step 2 · Reading the sign-in wall",
      }),
      false,
    );

    // Session + handoff + result bubbles ride the text path.
    const texts = deliver.mock.calls.map((call) => call[1] as string);
    expect(texts.some((text) => text.includes(LIVE_LINK))).toBe(true);
    expect(texts.some((text) => text.includes("sign in and come back"))).toBe(
      true,
    );
    // The result's sentinel became two sends, never a visible token.
    expect(texts.some((text) => text.includes("ABC123"))).toBe(true);
    expect(texts.some((text) => text.includes("confirmed twice"))).toBe(true);
    expect(texts.some((text) => text.includes("<NEW_MESSAGE_BREAK>"))).toBe(
      false,
    );

    // Every envelope acked, none dead-lettered.
    expect(channel.ack).toHaveBeenCalledTimes(envelopes.length);
    expect(channel.nack).not.toHaveBeenCalled();
  });
});

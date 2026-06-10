import { describe, expect, it } from "vitest";
import { outboundMessageEnvelopeSchema } from "../../../../../libs/shared/ts/src/bots/consumer/envelope";

// The schema is the wire contract with apps/api/app/schemas/outbound.py. These
// tests fail loudly if the contract is weakened (e.g. a field made optional).

const valid = {
  id: "uuid-1",
  platform: "whatsapp",
  destination_id: "15551234567",
  text: "hello",
  enqueued_at: "2026-05-30T12:00:00Z",
};

describe("outboundMessageEnvelopeSchema", () => {
  it("accepts a well-formed envelope (the Python wire shape)", () => {
    expect(outboundMessageEnvelopeSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a missing destination_id", () => {
    const missing = {
      id: "1",
      platform: "whatsapp",
      text: "hi",
      enqueued_at: "t",
    };
    expect(outboundMessageEnvelopeSchema.safeParse(missing).success).toBe(
      false,
    );
  });

  it("rejects an empty destination_id", () => {
    expect(
      outboundMessageEnvelopeSchema.safeParse({ ...valid, destination_id: "" })
        .success,
    ).toBe(false);
  });

  it("rejects empty text", () => {
    expect(
      outboundMessageEnvelopeSchema.safeParse({ ...valid, text: "" }).success,
    ).toBe(false);
  });

  it("rejects a non-string text (type confusion across the wire)", () => {
    expect(
      outboundMessageEnvelopeSchema.safeParse({ ...valid, text: 123 }).success,
    ).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { outboundMessageEnvelopeSchemaFor } from "../../../../../libs/shared/ts/src/bots/consumer/envelope";

// The schema is the wire contract with apps/api/app/schemas/outbound.py. These
// tests fail loudly if the contract is weakened (e.g. a field made optional).

const valid = {
  id: "uuid-1",
  platform: "whatsapp",
  destination_id: "15551234567",
  text: "hello",
  enqueued_at: "2026-05-30T12:00:00Z",
};

const OWN_API = "http://localhost:8121";
const schema = outboundMessageEnvelopeSchemaFor(OWN_API);

function photoEnvelope(url: string) {
  return {
    id: "uuid-2",
    platform: "telegram",
    destination_id: "42",
    enqueued_at: "2026-05-30T12:00:00Z",
    attachment: {
      url,
      filename: "browser-step-1.png",
      caption: "Step 1 \u00b7 open the site",
    },
  };
}

describe("outboundMessageEnvelopeSchemaFor", () => {
  it("accepts a well-formed envelope (the Python wire shape)", () => {
    expect(schema.safeParse(valid).success).toBe(true);
  });

  it("rejects a missing destination_id", () => {
    const missing = {
      id: "1",
      platform: "whatsapp",
      text: "hi",
      enqueued_at: "t",
    };
    expect(schema.safeParse(missing).success).toBe(false);
  });

  it("rejects an empty destination_id", () => {
    expect(schema.safeParse({ ...valid, destination_id: "" }).success).toBe(
      false,
    );
  });

  it("rejects empty text", () => {
    expect(schema.safeParse({ ...valid, text: "" }).success).toBe(false);
  });

  it("rejects a non-string text (type confusion across the wire)", () => {
    expect(schema.safeParse({ ...valid, text: 123 }).success).toBe(false);
  });

  it("accepts a plain-http attachment URL served by our own API", () => {
    const parsed = schema.safeParse(
      photoEnvelope(`${OWN_API}/shots/abc/1.png`),
    );
    expect(parsed.success).toBe(true);
  });

  it("accepts our own API on a non-default port regardless of case/trailing slash in the base", () => {
    const lenient = outboundMessageEnvelopeSchemaFor("http://LocalHost:8121/");
    expect(
      lenient.safeParse(photoEnvelope("http://localhost:8121/shots/abc/1.png"))
        .success,
    ).toBe(true);
  });

  it("rejects a plain-http attachment URL on any other origin", () => {
    const parsed = schema.safeParse(photoEnvelope("http://evil.example/x.png"));
    expect(parsed.success).toBe(false);
    expect(parsed.error?.issues[0]?.message).toContain("https");
  });

  it("rejects an http URL whose host merely contains ours", () => {
    expect(
      schema.safeParse(
        photoEnvelope("http://localhost:8121.evil.example/x.png"),
      ).success,
    ).toBe(false);
  });

  it("still accepts any https attachment URL", () => {
    expect(
      schema.safeParse(photoEnvelope("https://cdn.example.com/x.png")).success,
    ).toBe(true);
  });

  it("refuses every http URL when no own-API origin is configured", () => {
    const strict = outboundMessageEnvelopeSchemaFor(undefined);
    expect(
      strict.safeParse(photoEnvelope("http://localhost:8121/shots/abc/1.png"))
        .success,
    ).toBe(false);
  });

  it("accepts a reaction-only envelope (no text body)", () => {
    const { text: _text, ...noText } = valid;
    expect(
      schema.safeParse({
        ...noText,
        reaction: { target_platform_message_id: "wamid.123", emoji: "👍" },
      }).success,
    ).toBe(true);
  });

  it("rejects a reaction without a target", () => {
    const { text: _text, ...noText } = valid;
    expect(
      schema.safeParse({
        ...noText,
        reaction: { target_platform_message_id: "", emoji: "👍" },
      }).success,
    ).toBe(false);
  });
});

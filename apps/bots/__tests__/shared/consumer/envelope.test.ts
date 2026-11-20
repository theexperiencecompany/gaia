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

  it("accepts an artifact attachment as Python sends it (the other source null)", () => {
    const parsed = schema.safeParse({
      ...photoEnvelope("unused"),
      attachment: {
        conversation_id: "conv-1",
        path: "report.pdf",
        url: null,
        filename: "report.pdf",
        content_type: null,
        caption: null,
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects an attachment carrying both sources, or neither", () => {
    const both = photoEnvelope("https://cdn.example.com/x.png");
    const withBoth = {
      ...both,
      attachment: { ...both.attachment, conversation_id: "c", path: "p.pdf" },
    };
    const withNeither = {
      ...both,
      attachment: { filename: "x.png" },
    };
    expect(schema.safeParse(withBoth).success).toBe(false);
    expect(schema.safeParse(withNeither).success).toBe(false);
  });

  it("rejects an envelope whose only content is a reaction", () => {
    const { text: _text, ...noText } = valid;
    expect(
      schema.safeParse({
        ...noText,
        reaction: { target_platform_message_id: "wamid.123", emoji: "👍" },
      }).success,
    ).toBe(false);
  });
});

describe("follow wake partial_reply (mirrors bot_models.PartialReply)", () => {
  const { text: _text, ...noText } = valid;
  function wake(partial_reply: unknown) {
    return {
      ...noText,
      follow: {
        conversation_id: "conv-1",
        platform_user_id: "u1",
        channel_id: null,
        is_dm: true,
        after_seq: 4,
        partial_reply,
      },
    };
  }

  it("keeps the open bubble's message ids so a restarted follower edits instead of reposting", () => {
    const parsed = schema.safeParse(
      wake({ reply_id: "r1", bubbles: 1, open_message_ids: ["m7", "m8"] }),
    );
    expect(parsed.success).toBe(true);
    expect(parsed.data?.follow?.partial_reply?.open_message_ids).toEqual([
      "m7",
      "m8",
    ]);
  });

  it("accepts a reply cut off inside its first bubble", () => {
    const parsed = schema.safeParse(
      wake({ reply_id: "r1", bubbles: 0, open_message_ids: ["m7"] }),
    );
    expect(parsed.success).toBe(true);
    expect(parsed.data?.follow?.partial_reply).toEqual({
      reply_id: "r1",
      bubbles: 0,
      open_message_ids: ["m7"],
    });
  });

  it("rejects a partial reply that delivered nothing, as the server does", () => {
    expect(schema.safeParse(wake({ reply_id: "r1", bubbles: 0 })).success).toBe(
      false,
    );
    expect(
      schema.safeParse(
        wake({ reply_id: "r1", bubbles: -1, open_message_ids: ["m"] }),
      ).success,
    ).toBe(false);
  });
});

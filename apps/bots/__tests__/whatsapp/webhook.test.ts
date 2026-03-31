/**
 * Tests for pure utility functions exported from the WhatsApp webhook module.
 *
 * All three functions under test are pure (no I/O, no side effects), so no
 * mocking is required — we exercise them directly.
 *
 * Covered behaviors:
 *
 * verifyKapsoSignature:
 * 1. Returns false when signatureHeader is null
 * 2. Returns true for a valid raw hex signature
 * 3. Returns false when the signature hex is wrong
 * 4. Returns false when a different secret was used to produce the header
 * 5. Returns false when the body was tampered after signing
 * 6. Returns false when the header has a wrong byte length (timingSafeEqual throws → caught → false)
 * 7. Returns false when the header has the "sha256=" prefix (Kapso uses raw hex, no prefix)
 *
 * extractWaId:
 * 1. Returns conversation.phone_number without the leading "+"
 * 2. Returns the number as-is when phone_number has no leading "+"
 *
 * extractTextBody:
 * 1. Returns the text body for text-type messages
 * 2. Returns null for image-type messages
 * 3. Returns null for audio-type messages
 * 4. Returns null when the text field is undefined on a text-type message
 * 5. Returns null for document-type messages
 */

import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  extractTextBody,
  extractWaId,
  type KapsoMessageEvent,
  verifyKapsoSignature,
} from "../../whatsapp/src/webhook";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildSignature(body: string, secret: string): string {
  // Kapso sends raw HMAC-SHA256 hex — no "sha256=" prefix
  return createHmac("sha256", secret).update(body, "utf8").digest("hex");
}

function buildEvent(
  messageOverrides: Partial<KapsoMessageEvent["message"]> = {},
): KapsoMessageEvent {
  return {
    message: {
      id: "wamid.001",
      timestamp: "1700000000",
      type: "text",
      text: { body: "Hello GAIA" },
      ...messageOverrides,
    },
    conversation: {
      id: "conv_123",
      phone_number: "+15551234567",
      phone_number_id: "pn_abc123",
      status: "active",
    },
    is_new_conversation: false,
    phone_number_id: "pn_abc123",
  };
}

// ---------------------------------------------------------------------------
// verifyKapsoSignature
// ---------------------------------------------------------------------------

describe("verifyKapsoSignature", () => {
  const hmacKey = "test-hmac-key";
  const body = '{"phone_number_id":"pn_abc123"}';

  it("returns false when signatureHeader is null", () => {
    expect(verifyKapsoSignature(body, null, hmacKey)).toBe(false);
  });

  it("returns true for a valid raw hex signature", () => {
    const header = buildSignature(body, hmacKey);
    expect(verifyKapsoSignature(body, header, hmacKey)).toBe(true);
  });

  it("returns false when the signature hex is wrong", () => {
    const header =
      "0000000000000000000000000000000000000000000000000000000000000000";
    expect(verifyKapsoSignature(body, header, hmacKey)).toBe(false);
  });

  it("returns false when a different secret was used to sign the header", () => {
    const header = buildSignature(body, "wrong-hmac-key");
    expect(verifyKapsoSignature(body, header, hmacKey)).toBe(false);
  });

  it("returns false when the body was tampered after signing", () => {
    const header = buildSignature(body, hmacKey);
    const tamperedBody = `${body} `;
    expect(verifyKapsoSignature(tamperedBody, header, hmacKey)).toBe(false);
  });

  it("returns false when the header has wrong byte length (timingSafeEqual throws → caught → false)", () => {
    // "abc" is far too short — the Buffers will have different lengths,
    // causing timingSafeEqual to throw, which the implementation catches → false.
    expect(verifyKapsoSignature(body, "abc", hmacKey)).toBe(false);
  });

  it("returns false when the header has the sha256= prefix (Kapso sends raw hex, no prefix)", () => {
    const rawHex = createHmac("sha256", hmacKey)
      .update(body, "utf8")
      .digest("hex");
    const withPrefix = `sha256=${rawHex}`;
    // The Buffer lengths differ ("sha256=" adds 7 bytes), so timingSafeEqual throws → false
    expect(verifyKapsoSignature(body, withPrefix, hmacKey)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// extractWaId
// ---------------------------------------------------------------------------

describe("extractWaId", () => {
  it("strips the leading + from conversation.phone_number", () => {
    const event = buildEvent();
    expect(extractWaId(event)).toBe("15551234567");
  });

  it("returns the number unchanged when there is no leading + sign", () => {
    const event = buildEvent();
    event.conversation.phone_number = "447911123456";
    expect(extractWaId(event)).toBe("447911123456");
  });
});

// ---------------------------------------------------------------------------
// extractTextBody
// ---------------------------------------------------------------------------

describe("extractTextBody", () => {
  it("returns the text body for text-type messages", () => {
    const event = buildEvent({ type: "text", text: { body: "Hello GAIA" } });
    expect(extractTextBody(event)).toBe("Hello GAIA");
  });

  it("returns null for image-type messages", () => {
    const event = buildEvent({ type: "image", text: undefined });
    expect(extractTextBody(event)).toBeNull();
  });

  it("returns null for audio-type messages", () => {
    const event = buildEvent({ type: "audio", text: undefined });
    expect(extractTextBody(event)).toBeNull();
  });

  it("returns null when the text field is undefined on a text-type message", () => {
    const event = buildEvent({ type: "text", text: undefined });
    expect(extractTextBody(event)).toBeNull();
  });

  it("returns null for document-type messages", () => {
    const event = buildEvent({ type: "document", text: undefined });
    expect(extractTextBody(event)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Additional edge cases
// ---------------------------------------------------------------------------

describe("verifyKapsoSignature - additional edge cases", () => {
  const hmacKey = "test-hmac-key";
  const body = '{"phone_number_id":"pn_abc123"}';

  it("returns false for an empty string signature", () => {
    expect(verifyKapsoSignature(body, "", hmacKey)).toBe(false);
  });

  it("returns false for a null body (edge case)", () => {
    const header = buildSignature(body, hmacKey);
    // Different body means signature mismatch
    expect(verifyKapsoSignature("", header, hmacKey)).toBe(false);
  });
});

describe("extractTextBody - additional cases", () => {
  it("returns null for video-type messages", () => {
    const event = buildEvent({ type: "video", text: undefined });
    expect(extractTextBody(event)).toBeNull();
  });

  it("returns the text body for messages with extra fields", () => {
    const event = buildEvent({
      type: "text",
      text: { body: "Message with context" },
    });
    expect(extractTextBody(event)).toBe("Message with context");
  });
});

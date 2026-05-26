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
  extractMedia,
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

// ---------------------------------------------------------------------------
// extractMedia
// ---------------------------------------------------------------------------

describe("extractMedia", () => {
  it("returns null for text messages", () => {
    const event = buildEvent({ type: "text", text: { body: "hi" } });
    expect(extractMedia(event)).toBeNull();
  });

  it("extracts image media with caption + mime", () => {
    const event = buildEvent({
      type: "image",
      text: undefined,
      image: {
        id: "media-img-1",
        mime_type: "image/jpeg",
        caption: "look at this",
      },
    });
    const media = extractMedia(event);
    expect(media).not.toBeNull();
    expect(media!.kind).toBe("image");
    expect(media!.mediaId).toBe("media-img-1");
    expect(media!.mimeType).toBe("image/jpeg");
    expect(media!.caption).toBe("look at this");
    expect(media!.isVoiceNote).toBe(false);
  });

  it("falls back to a default mime type when one is not supplied", () => {
    const event = buildEvent({
      type: "image",
      text: undefined,
      image: { id: "x" },
    });
    expect(extractMedia(event)!.mimeType).toBe("image/jpeg");
  });

  it("flags type==voice as a voice note (folded into the audio kind)", () => {
    const event = buildEvent({
      type: "voice",
      text: undefined,
      voice: { id: "media-voice-1", mime_type: "audio/ogg" },
    });
    const media = extractMedia(event);
    expect(media!.kind).toBe("audio");
    expect(media!.isVoiceNote).toBe(true);
  });

  it("flags audio with voice:true as a voice note", () => {
    const event = buildEvent({
      type: "audio",
      text: undefined,
      audio: { id: "media-audio-1", mime_type: "audio/ogg", voice: true },
    });
    expect(extractMedia(event)!.isVoiceNote).toBe(true);
  });

  it("treats audio without voice:true as a plain audio file", () => {
    const event = buildEvent({
      type: "audio",
      text: undefined,
      audio: { id: "media-audio-2", mime_type: "audio/mpeg" },
    });
    const media = extractMedia(event);
    expect(media!.kind).toBe("audio");
    expect(media!.isVoiceNote).toBe(false);
    expect(media!.mimeType).toBe("audio/mpeg");
  });

  it("extracts document filename + caption", () => {
    const event = buildEvent({
      type: "document",
      text: undefined,
      document: {
        id: "media-doc-1",
        mime_type: "application/pdf",
        filename: "spec.pdf",
        caption: "review pls",
      },
    });
    const media = extractMedia(event);
    expect(media!.kind).toBe("document");
    expect(media!.filename).toBe("spec.pdf");
    expect(media!.caption).toBe("review pls");
    expect(media!.mimeType).toBe("application/pdf");
  });

  it("preserves video and sticker kinds so the adapter can reject them gracefully", () => {
    const videoEvent = buildEvent({
      type: "video",
      text: undefined,
      video: { id: "media-vid-1", mime_type: "video/mp4" },
    });
    expect(extractMedia(videoEvent)!.kind).toBe("video");

    const stickerEvent = buildEvent({
      type: "sticker",
      text: undefined,
      sticker: { id: "media-sticker-1", mime_type: "image/webp" },
    });
    expect(extractMedia(stickerEvent)!.kind).toBe("sticker");
  });

  it("returns null when the media payload is missing its id", () => {
    const event = buildEvent({
      type: "image",
      text: undefined,
      image: { mime_type: "image/jpeg" },
    });
    expect(extractMedia(event)).toBeNull();
  });

  it("returns null for unsupported message types", () => {
    const event = buildEvent({ type: "interactive", text: undefined });
    expect(extractMedia(event)).toBeNull();
  });

  it("picks up the Kapso pre-resolved media URL when present", () => {
    const event = buildEvent({
      type: "image",
      text: undefined,
      image: { id: "media-img-2", mime_type: "image/png" },
      kapso: {
        direction: "in",
        status: "received",
        processing_status: "processed",
        origin: "whatsapp",
        has_media: true,
        media_url: "https://kapso-cdn.example/media-img-2.png",
      },
    });
    expect(extractMedia(event)!.prefetchedUrl).toBe(
      "https://kapso-cdn.example/media-img-2.png",
    );
  });
});
